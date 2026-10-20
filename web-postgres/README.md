# web-postgres

A FastAPI app that stores notes in managed Postgres through psycopg 3. It reads the connection
string from `DATABASE_URL`, connects over TLS, and creates its table at startup.

Managed Postgres is in **beta**: small size only.

- Port: **8000**
- User: `1000`
- Files: `main.py` (routes, database access, migration), `security.py` (headers, body limit,
  logs, errors), `requirements.in` → `requirements.txt` (generated, with hashes),
  `Dockerfile`, `.dockerignore`

| Request | Response |
|---|---|
| `GET /` | Always 200 and never connects, so the health check passes before linking and while the database restarts. |
| `GET /notes?limit=20` | The newest notes (`limit` 1–100). 503 if `DATABASE_URL` is not set or the database is unreachable. |
| `POST /notes` with `{"text": "..."}` | 201 and the stored note. `text` is 1–500 characters; unknown fields are rejected. |

## Deploy with the CLI

```bash
guidal deploy ./web-postgres                                 # prints "Image: <ref>"
guidal services create --name web --image <ref> --port 8000
guidal db create --name app-db --type postgresql             # waits until it is running
guidal db link app-db --service web                          # sets DATABASE_URL, restarts web
```

Linking sets exactly one variable, `DATABASE_URL=postgresql://user:password@host:port/db`
(no `sslmode`, no `PG*` variables). The database accepts connections only from inside the
project; from your laptop use `guidal db connect app-db` (psql) or `guidal db proxy app-db`
(a local tunnel), not the URL itself.

## Deploy with the local MCP server

```text
deploy_from_source(path="/absolute/path/to/web-postgres", service_name="web", port=8000)
get_build_status(build_id="...", wait_seconds=55)
create_database(name="app-db", type="postgresql")
call_capability("get_database_info", {"database_id": "...", "wait_seconds": 55})  # until Running
link_database(database_id="...", service_id="...")
get_service(service_id="...", wait_seconds=55)
```

## Verify

```bash
curl https://<service-url>/
# {"status":"ok","database":"DATABASE_URL set (GET /notes checks the connection)"}
curl -X POST https://<service-url>/notes -H 'content-type: application/json' -d '{"text":"hello"}'
# {"id":1,"text":"hello"}
curl https://<service-url>/notes
# [{"id":1,"text":"hello","created_at":"..."}]
guidal logs query --service <service-id> --since 15m   # expect "schema ready"
```

## Update

```bash
guidal deploy ./web-postgres --service web
```

Change the schema by appending statements to `MIGRATIONS` in `main.py` that are safe to run
again (`CREATE TABLE IF NOT EXISTS`, `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`). They run at
every start, inside one transaction holding a Postgres advisory lock, so replicas starting
together apply them one at a time.

## Design notes

- **TLS.** Guidal's Postgres (CloudNativePG) serves TLS with a certificate from a
  cluster-internal CA, but the injected URL has no `sslmode`, and libpq's default (`prefer`)
  would fall back to plaintext. The app adds `sslmode=require` unless the URL or `PGSSLMODE`
  sets one. The CA is not given to apps, so `verify-full` is not possible yet.
- **Connections.** One short-lived connection per request, at most 5 at a time per replica
  (a semaphore; the startup migration takes one of the same 5 slots). This survives database restarts without stale pooled connections and keeps a
  small database's connection slots for other replicas. Move to `psycopg_pool` when the
  per-request connect time starts to matter.
- **Timeouts.** `connect_timeout=5` and `statement_timeout=5000` ms, so a slow database turns
  into a 503 ("database unreachable" or "query timed out") instead of piling up requests.
- **Migration.** Runs in a background thread at startup with retry and backoff, so `GET /`
  answers at once. Requests never wait for it: until the schema is ready, `/notes` answers
  503 "database not ready yet" at once, so a hung database cannot tie up request threads or
  the health check (`GET /` is `async` and never touches the database). `pg_advisory_xact_lock` makes
  it safe with any number of replicas: without it, parallel `CREATE TABLE IF NOT EXISTS` on a
  fresh database fails with duplicate-type errors.
- **Keep:** parameterised SQL only; length limits in the model and a `CHECK` in the table;
  `DATABASE_URL` never logged (it holds the password), errors logged by type only; generic
  503 bodies; everything in `web-fastapi`'s design notes.
- **For a real app:** use a migration tool (Alembic) under the same advisory lock once the
  schema grows; add authentication before writes; paginate with keyset (`WHERE id < $last`).
