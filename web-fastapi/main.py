import os

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field

from security import secure

# API docs are off by default: they map your whole attack surface for anyone who
# asks. ENABLE_API_DOCS=1 (guidal env set) serves the schema at /openapi.json only.
# The Swagger UI page is never served: it loads scripts from a third-party CDN.
DOCS = os.environ.get("ENABLE_API_DOCS") == "1"

app = secure(FastAPI(docs_url=None, redoc_url=None, openapi_url="/openapi.json" if DOCS else None))


@app.get("/")
async def root():
    # The platform health check: 200 within 60 s of start, no dependencies.
    return {"status": "ok", "app": "web-fastapi"}


class EchoIn(BaseModel):
    # Validate every input: type, length, no unknown fields.
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=200)


@app.post("/echo")
def echo(body: EchoIn):
    return {"message": body.message}
