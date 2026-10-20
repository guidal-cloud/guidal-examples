# Instructions for coding agents

Work in four steps, in order: **DESIGN → BUILD → DEPLOY → VERIFY**. Do not write code before
the design answers are written down, and do not say "done" before VERIFY passes. The commands
here are the whole flow; do not invent flags.

## Pick an example

| The user wants | Start from | Port |
|---|---|---|
| A web page or site (Node) | `web-nextjs/` | 3000 |
| An HTTP/JSON API (Python) | `web-fastapi/` | 8000 |
| An HTTP app that stores data | `web-postgres/` (managed Postgres, beta) | 8000 |
| A long-running background loop | `worker-python/` | none |
| A task on a schedule | `cron-python/` | none |

Copy the whole directory, then change the app code. Keep the Dockerfile shape, `security.py`,
the headers and the limits; each README's "Design notes" says what must stay.

## 1. DESIGN: answer these in your reply or plan before writing code

1. **Workload shape.** Which parts are web (answers HTTP), worker (loops forever) or cron (runs
   and exits)? One process per service: no supervisord, no web server plus a worker in one
   container. A queue consumer is a worker; a nightly report is a cron job.
2. **State.** The container filesystem is ephemeral and replaced on every deploy; there are no
   persistent volumes. Durable data goes in managed Postgres (beta, small). Redis only as a
   cache you can rebuild. There is **no object storage yet**: do not design file uploads or
   user media that must persist; say so and propose an alternative (store small files in
   Postgres, or keep that part outside Guidal for now).
3. **Config vs secrets.** List every setting. Non-secret config → `guidal env set`. Passwords,
   API keys, tokens → `guidal secrets` (encrypted, never in the image, never in git, never in
   logs). `DATABASE_URL` is injected by `guidal db link`; do not set it yourself.
4. **Plan and resources.** Each service gets 100m CPU / 128Mi requested and at most 500m CPU /
   512Mi. The Free plan has 1 vCPU in total including the database and one project. Count your
   services: if the design does not fit, tell the user before building.
5. **Statelessness and replicas.** Assume two replicas and restarts at any time: no in-memory
   sessions, no local files as a cache of record, no in-process schedulers (use a cron job).
6. **Migrations.** Run at startup, idempotent, and safe when two replicas start at once
   (`CREATE ... IF NOT EXISTS` inside a Postgres advisory lock; see `web-postgres/main.py`).
7. **Exposure.** Web services get a public HTTPS URL; TLS ends at the platform edge and the app
   serves plain HTTP. Expose no admin, debug or docs endpoints by default. Do not trust client
   `X-Forwarded-*` headers (keep uvicorn's default `--forwarded-allow-ips` of 127.0.0.1).
8. **Not available yet.** Object storage, custom domains, private networking between projects,
   persistent volumes, build arguments, linking a database to a cron job. Do not design around
   them; say which the user's request needs.
9. **Egress.** Outbound internet works; cluster-internal and private address ranges do not.
   Call external APIs over HTTPS with timeouts.
10. **Logging.** stdout only, one JSON object per line, no secrets, tokens, passwords or
    personal data, no full URLs with query strings.
11. **Health.** `GET /` must return 200 within 60 s of start and must not depend on the
    database or another service; a dependency outage must not restart your app.
12. **Shutdown.** Pods get 30 s in total. Web services first wait 5 s for traffic to drain,
    so the app has about 25 s after SIGTERM to finish requests. Workers are allowed 30 s, but today the worker wrapper exits as soon as it forwards SIGTERM, so the process can
    be killed almost at once: keep units of work short and idempotent (a unit interrupted
    half-way must be safe to redo).

## 2. BUILD: rules every app MUST follow

Platform contract:

1. A regular file named exactly `Dockerfile` at the root of the deployed directory (not a
   symlink). Guidal's builders are `linux/amd64`; there are no build arguments.
2. Bind `0.0.0.0` on a fixed port of 1024 or higher, written as `ENV PORT=<n>` and
   `EXPOSE <n>`, and passed again as `--port <n>` when the service is created. No `PORT` is
   injected.
3. A numeric non-root `USER` (`USER 1000`). With that and a port of 1024 or higher the pod runs
   as non-root with all capabilities dropped; `USER node` or root is not hardened.
4. Workers need `/bin/sh`, `date` and a writable `/tmp` (no distroless for workers).
5. Cron jobs exit 0 on success and non-zero on failure.

Security by default (keep these when you change the example):

6. Base images pinned by tag **and** digest: `FROM python:3.12.15-slim@sha256:...`. Get a
   digest with `docker buildx imagetools inspect <image:tag>`.
7. Multi-stage build. The final stage holds the runtime, the dependencies and the app only:
   no compilers, no pip/npm caches, no package managers, no tests, no `.env`.
8. Locked dependencies with integrity checks. Python: edit `requirements.in`, regenerate
   `requirements.txt` with `uv pip compile --generate-hashes` (command in the file), install
   with `pip install --require-hashes`. Node: `npm ci` from `package-lock.json`, install scripts
   off (`.npmrc`). Use releases at least two weeks old unless they fix a vulnerability.
9. App files owned by root and not writable by the app. The app must run with a read-only root
   filesystem and only `/tmp` writable; point any cache or temp dir at `/tmp`.
10. Security headers on every response (`nosniff`, frame denial, `Referrer-Policy`, a CSP),
    no `Server`/`X-Powered-By` banner, a request body size limit, generic JSON errors (no stack
    traces to clients), input validated with types and maximum lengths.
11. SQL is parameterised (`%s` placeholders), never built with f-strings or `+`. Set connect
    and statement timeouts. Never log `DATABASE_URL`; it contains the password.
12. Keep `.dockerignore` excluding `.env*`, keys, `node_modules`, `.next`, `__pycache__`,
    `.venv`. Never commit secrets.

Check before deploying (from the repo root):

```bash
docker build --platform linux/amd64 -t my-app ./web-fastapi
scripts/smoke-test.sh web-fastapi my-app    # read-only FS, --cap-drop ALL, user 1000
```

## 3. DEPLOY

```bash
pip install guidal
guidal login
guidal context set --org <org-slug> --project <project-slug>
```

Web service (first time), then every later change:

```bash
guidal deploy ./web-fastapi                       # build only; prints "Image: <ref>"
guidal services create --name web --image <ref> --port 8000
guidal deploy ./web-fastapi --service web         # later changes: rebuild and roll out
```

Always pass `--port`; without it the service is created on 8080. `guidal deploy` cannot create
a service and has no `--port`. `--service` and `--name` cannot be used together.

Worker and cron job:

```bash
guidal deploy ./worker-python --name my-worker    # build only; prints "Image: <ref>"
guidal services create --name my-worker --type worker --image <ref> --command "python worker.py"
guidal deploy ./worker-python --service my-worker # later updates

guidal deploy ./cron-python --name my-job         # build only; prints "Image: <ref>"
guidal cron create --name my-job --slug my-job --image <ref> \
  --command "python job.py" --schedule "*/15 * * * *" --timezone UTC --concurrency-policy Forbid
```

Postgres (beta):

```bash
guidal db create --name app-db --type postgresql
guidal db link app-db --service web               # sets DATABASE_URL, restarts the service
```

Config and secrets. `env` and `secrets link` take the **service ID** (from
`guidal services list`), not the name. Each change restarts the service.

```bash
guidal env set <service-id> LOG_LEVEL=info FEATURE_X=1     # non-secret config
guidal env list <service-id>

guidal secrets import --file ./secrets.env        # KEY=value lines; keeps values off argv
guidal secrets link STRIPE_API_KEY --service <service-id>  # injected as env var STRIPE_API_KEY
guidal secrets list                               # names only; values are never shown
```

Secrets belong to the project; linking one to a service injects it as an environment variable
of the same name. Avoid `guidal secrets set KEY --value ...`: the value lands in shell history.
Do not handle a user's secret values yourself when you can avoid it: give the user the command
to run, and delete any `secrets.env` file afterwards (it is never uploaded, never commit it).

Local MCP server (Claude Code plugin):

```text
deploy_from_source(path="/absolute/path/to/web-fastapi", service_name="web", port=8000)
get_build_status(build_id="...", wait_seconds=55)   # repeat until it finishes
get_service(service_id="...", wait_seconds=55)
create_database(name="app-db", type="postgresql")
link_database(database_id="...", service_id="...")
set_env_vars(service_id="...", env_vars={"LOG_LEVEL": "info"})   # one restart for all keys
call_capability("set_secret", {"key": "STRIPE_API_KEY", "value": "..."})
call_capability("link_secret", {"key": "STRIPE_API_KEY", "service_id": "..."})
```

A value passed to `set_secret` is visible in the conversation; prefer asking the user to run
`guidal secrets import`. `deploy_from_source` creates a web service or rolls a new image onto
it. For a worker or cron job, build with `deploy=False`, take the image from
`get_build_status`, then `create_service(type="worker", command=...)` or
`call_capability("create_cron_job", {...})`. The hosted MCP server cannot read your disk: there,
run `guidal deploy` in a terminal.

## 4. VERIFY

```bash
guidal services list                              # service IDs and URLs
curl -i https://<service-url>/                    # 200, the README's JSON, security headers
guidal logs query --service <service-id> --since 15m
guidal logs query --service <service-id> --level error --since 1h
guidal services diagnose <service-id>             # why a service is failing, with next steps
guidal builds logs <build-id>                     # when the build failed
guidal cron trigger <cron-job-id> && guidal cron history <cron-job-id>
```

For a web UI, also open the live URL in a headless browser (for example the Playwright MCP
server): the page renders, and the console shows no errors and no CSP violations.

### Before you say done

- [ ] The DESIGN answers are written down, including what does not fit or is unavailable.
- [ ] The image passes `scripts/smoke-test.sh`-style checks: read-only FS, user 1000.
- [ ] `GET /` on the live URL returns 200; the main user flow works end to end.
- [ ] Logs show no errors and contain no secrets or connection strings.
- [ ] Every secret is a Guidal secret, linked to the service; none is in git or the image.
- [ ] You told the user the URL, what you deployed, and any limits that apply (beta Postgres,
      Free plan CPU).

## Common failures

| Symptom | Cause | Fix |
|---|---|---|
| Health check fails, logs say the app started | Port mismatch, or listening on `127.0.0.1` | Same port in the app, `EXPOSE` and `--port`; bind `0.0.0.0` |
| Service created on 8080 | `--port` was not passed | `guidal services update <service-id> --port <n>` |
| Health check fails, app is up | `/` returns 404, a redirect or 500 | `GET /` returns 200 without touching the database |
| Pod not hardened, or refused with `--hardening on` | `USER` is a name or root, or port < 1024 | `USER 1000` and a port of 1024 or higher |
| `Read-only file system` | The app writes outside `/tmp` | Point caches and temp files at `/tmp` |
| Build used language detection | No regular root `Dockerfile` | Put a regular `Dockerfile` at the root |
| Build fails on `COPY` of a file that exists | Excluded by `.guidalignore`/`.dockerignore`, or secret-looking | Remove the pattern, or add `!<path>` |
| `pip` says hashes are required / do not match | `requirements.txt` edited by hand | Regenerate it from `requirements.in` |
| `npm ci` fails | `package-lock.json` out of date | `npm install`, commit the lockfile |
| `/notes` 503 "database unreachable" or "not ready yet" | Database starting, not linked, or TLS refused | `guidal db get app-db`; check the link; keep the default `sslmode` |
| Worker loses work on deploy | A unit of work is long or not idempotent | Short, idempotent units |
| `exec format error` | Image built on ARM | Let Guidal build it, or `--platform linux/amd64` |
| Out of memory (exit 137) | Over 512Mi | Smaller runtime, or `guidal services update <service-id> --memory 1Gi` |
