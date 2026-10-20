# web-fastapi

A FastAPI JSON API served by uvicorn. `GET /` returns `{"status":"ok","app":"web-fastapi"}`
with HTTP 200; `POST /echo` shows input validation.

- Port: **8000** (`ENV PORT=8000`, `EXPOSE 8000`, uvicorn binds `0.0.0.0:8000`)
- User: `1000` (numeric, so the pod runs hardened)
- Files: `main.py` (routes), `security.py` (headers, body limit, logs, errors),
  `requirements.in` (top-level pins) → `requirements.txt` (generated, with hashes),
  `Dockerfile`, `.dockerignore`

## Deploy with the CLI

```bash
guidal deploy ./web-fastapi                                  # prints "Image: <ref>"
guidal services create --name web --image <ref> --port 8000
```

## Deploy with the local MCP server

```text
deploy_from_source(path="/absolute/path/to/web-fastapi", service_name="web", port=8000)
get_build_status(build_id="...", wait_seconds=55)
get_service(service_id="...", wait_seconds=55)
```

## Verify

```bash
curl -i https://<service-url>/
# HTTP 200, content-security-policy, x-content-type-options, x-frame-options; no "server" header
# {"status":"ok","app":"web-fastapi"}
curl https://<service-url>/docs        # 404: docs are off by default
```

## Update

Edit `main.py`. To add a package, add `name==version` to `requirements.in` and regenerate
`requirements.txt` with the command at the top of `requirements.in`. A new Python file must
also be added to the `COPY` line of the `Dockerfile`. Then:

```bash
guidal deploy ./web-fastapi --service web
```

## Design notes

- **Why it is built this way.** The final image holds only Python, a virtualenv installed
  from hash-checked wheels and two source files; pip itself is removed. The code is owned by
  root and the app runs as user 1000 with a read-only root filesystem, so a compromised process
  cannot change the app or install tools.
- **Keep:** `security.py` (security headers including a CSP for JSON, a 64 KiB body limit,
  one JSON access-log line per request with the path only, generic 500 responses that still
  carry the headers, uvicorn's own log lines switched to JSON);
  `docs_url`/`openapi_url` off unless `ENABLE_API_DOCS=1` (which serves `/openapi.json` only);
  uvicorn's `--no-server-header`, `--limit-concurrency` and default proxy trust.
- **`--limit-concurrency 100`** counts open connections (idle keep-alive ones included), not
  running handlers: past 100, new requests get 503. Raise it with the memory limit, not alone.
- **Forwarded headers.** TLS ends at the platform edge, which forwards to the app over plain
  HTTP. uvicorn trusts `X-Forwarded-For`/`-Proto` only from `127.0.0.1` by default, so a client
  cannot spoof its IP or scheme. Do not widen `--forwarded-allow-ips` to `*`: any client could
  then claim any address.
- **For a real app:** raise `max_body_bytes` in `secure(...)` only for the routes that need
  it; add authentication before any write endpoint; serve HTML from `web-nextjs/` or relax the
  CSP for that route only; keep secrets in `guidal secrets`, read from `os.environ`.
