import os
import threading
from contextlib import asynccontextmanager, contextmanager

import psycopg
from fastapi import FastAPI, HTTPException, Query
from psycopg.conninfo import conninfo_to_dict
from pydantic import BaseModel, ConfigDict, Field

from security import get_logger, secure

log = get_logger("app")

# Injected by `guidal db link <db> --service <service>`. Absent until then.
# NEVER log this value: it contains the database password.
DATABASE_URL = os.environ.get("DATABASE_URL")

# Guidal's managed Postgres serves TLS, but the injected URL carries no sslmode.
# libpq's default ("prefer") silently falls back to plaintext, so require TLS unless
# the URL or PGSSLMODE says otherwise. The server certificate comes from a
# cluster-internal CA that is not given to apps, so verify-full is not possible yet.
CONNECT_ARGS = {
    "connect_timeout": 5,
    "application_name": "web-postgres",
    # A runaway query is cancelled by the server instead of holding a connection.
    "options": "-c statement_timeout=5000",
}

# One short-lived connection per request, at most MAX_CONNECTIONS at a time per
# replica. Simple and robust to database restarts (no stale pooled connections), and
# the cap keeps a small database's connection slots for the other replicas. Switch to
# psycopg_pool when the per-request connect time (a few ms in-cluster) starts to matter.
MAX_CONNECTIONS = 5
slots = threading.BoundedSemaphore(MAX_CONNECTIONS)

# Arbitrary constant naming "this app's schema migration" for pg_advisory_xact_lock.
MIGRATION_LOCK_ID = 7_340_001
MIGRATIONS = [
    "CREATE TABLE IF NOT EXISTS notes ("
    " id bigserial PRIMARY KEY,"
    " text text NOT NULL CHECK (char_length(text) <= 500),"
    " created_at timestamptz NOT NULL DEFAULT now())",
]
schema_ready = threading.Event()
stopping = threading.Event()


def connect_kwargs() -> dict:
    try:
        url_params = conninfo_to_dict(DATABASE_URL)
    except psycopg.ProgrammingError:
        # The message could echo the URL, so it is not logged.
        raise RuntimeError("DATABASE_URL is not a valid connection string") from None
    kwargs = dict(CONNECT_ARGS)
    if "sslmode" not in url_params and "PGSSLMODE" not in os.environ:
        kwargs["sslmode"] = "require"
    return kwargs


@contextmanager
def connection():
    if not DATABASE_URL:
        raise HTTPException(503, "DATABASE_URL not set: link a database to this service")
    if not slots.acquire(timeout=5):
        raise HTTPException(503, "too many concurrent database requests, retry shortly")
    try:
        with psycopg.connect(DATABASE_URL, **connect_kwargs()) as conn:
            yield conn
    except psycopg.errors.QueryCanceled:
        # statement_timeout fired. Checked first: it is a subclass of OperationalError.
        log.warning("query timed out")
        raise HTTPException(503, "query timed out") from None
    except psycopg.OperationalError as exc:
        log.warning("database unreachable", extra={"fields": {"error": type(exc).__name__}})
        raise HTTPException(503, "database unreachable") from None
    finally:
        slots.release()


def migrate() -> None:
    """Idempotent and safe with any number of replicas starting at once: the advisory
    lock serialises them, and every statement is safe to run again. It takes one of
    the connection slots, so a replica never holds more than MAX_CONNECTIONS."""
    with slots, psycopg.connect(DATABASE_URL, **connect_kwargs()) as conn, conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (MIGRATION_LOCK_ID,))
        for statement in MIGRATIONS:
            conn.execute(statement)
    schema_ready.set()
    log.info("schema ready")


def migrate_in_background() -> None:
    # The only caller of migrate(). Requests never wait for it: until the schema is
    # ready they get a quick 503, so a hung database cannot pile up request threads.
    delay = 1.0
    while not stopping.is_set() and not schema_ready.is_set():
        try:
            migrate()
        except Exception as exc:
            log.warning(
                "migration not done yet, retrying", extra={"fields": {"error": type(exc).__name__, "retry_s": delay}}
            )
            stopping.wait(delay)
            delay = min(delay * 2, 30.0)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Migrate at startup without blocking it: GET / answers at once, and a database
    # that is still starting (or not linked yet) only delays the /notes endpoints.
    if DATABASE_URL:
        threading.Thread(target=migrate_in_background, daemon=True).start()
    yield
    stopping.set()


app = secure(FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan))


class NoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    text: str = Field(min_length=1, max_length=500)


def ready_connection():
    if DATABASE_URL and not schema_ready.is_set():
        raise HTTPException(503, "database not ready yet, retry shortly")
    return connection()


@app.get("/")
async def root():
    # The platform health check: always 200 and never touches the database, so it
    # passes before a database is linked and while the database restarts. async, so
    # it runs on the event loop and never waits behind database calls in the
    # thread pool.
    if not DATABASE_URL:
        return {"status": "ok", "database": "DATABASE_URL not set"}
    return {"status": "ok", "database": "DATABASE_URL set (GET /notes checks the connection)"}


@app.get("/notes")
def list_notes(limit: int = Query(20, ge=1, le=100)):
    with ready_connection() as conn:
        rows = conn.execute("SELECT id, text, created_at FROM notes ORDER BY id DESC LIMIT %s", (limit,)).fetchall()
    return [{"id": r[0], "text": r[1], "created_at": r[2].isoformat()} for r in rows]


@app.post("/notes", status_code=201)
def add_note(note: NoteIn):
    # Parameterised SQL only: never format user input into a query string.
    with ready_connection() as conn:
        note_id = conn.execute("INSERT INTO notes (text) VALUES (%s) RETURNING id", (note.text,)).fetchone()[0]
    return {"id": note_id, "text": note.text}
