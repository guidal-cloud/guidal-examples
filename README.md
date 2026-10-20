# Guidal examples

Small, working apps you can copy and deploy on [Guidal](https://guidal.ai) by building from
source. Each directory is one app with a root `Dockerfile`, locked dependencies and a README
with the exact deploy commands and the design choices behind it.

**Coding agents: start with [AGENTS.md](AGENTS.md).** It is the whole flow: design questions
to answer first, the build rules, the deploy commands and how to verify.

## Examples

| Directory | What it is | Port | Guidal resource |
|---|---|---|---|
| [`web-nextjs/`](web-nextjs/) | Next.js 15 App Router, standalone output, one page + `/api/health` | 3000 | web service |
| [`web-fastapi/`](web-fastapi/) | FastAPI JSON API with security headers, body limit and validation | 8000 | web service |
| [`worker-python/`](worker-python/) | Background loop: one short, idempotent unit of work every 30 s | none | worker service |
| [`cron-python/`](cron-python/) | Script that does one job, logs a JSON result and exits 0 | none | cron job |
| [`web-postgres/`](web-postgres/) | FastAPI + psycopg 3: a notes table in managed Postgres (beta), TLS required | 8000 | web service + database |

## Secure by default

Every example is built and tested in CI the way Guidal runs it, or stricter:

- base images pinned by tag and digest; multi-stage builds with no package manager, compiler
  or cache in the final image;
- dependencies locked with integrity hashes (`pip --require-hashes`, `npm ci`, install
  scripts off);
- a numeric non-root user, app files owned by root, and a read-only root filesystem with only
  `/tmp` writable (`docker run --read-only --tmpfs /tmp --cap-drop ALL`);
- security headers, no server banner, request size limits, generic errors, validated input,
  parameterised SQL, structured logs without secrets;
- a Trivy scan that fails on fixable HIGH or CRITICAL vulnerabilities.

`scripts/smoke-test.sh <example> <image>` runs the same checks locally.

## Updating a pinned base image

```bash
docker buildx imagetools inspect python:<new-tag>   # copy the top-level "Digest"
```

Replace both `FROM` lines of the Dockerfile with `python:<new-tag>@sha256:<digest>`, then run
the smoke test. The same applies to `node:` images.

## What the platform expects

- **Build from source.** `guidal deploy <dir>` uploads the directory and builds it on Guidal's
  `linux/amd64` builders, using the root `Dockerfile` when there is one. No build arguments.
- **Upload filter.** `.guidalignore` (or `.dockerignore`) decides what is uploaded. `.git`,
  editor folders and secret-looking files (`.env*`, `*.pem`, `*.key`) are withheld unless you
  opt back in with a `!` pattern.
- **Ports.** No `PORT` is injected. Bind a fixed port of 1024 or higher on `0.0.0.0`, state it
  with `ENV PORT` and `EXPOSE`, and pass the same number with `--port`.
- **Health check.** `GET /` must return HTTP 200 within 60 seconds of start.
- **Hardening.** Every pod runs with the default seccomp profile, no privilege escalation and
  no service-account token. With a numeric `USER` and a port of 1024 or higher it also runs as
  non-root with all capabilities dropped.
- **Resources.** 100m CPU / 128Mi requested, 500m CPU / 512Mi at most per container. The Free
  plan has 1 vCPU in total, including the database.
- **Storage.** The container filesystem is ephemeral. Durable data goes in managed Postgres
  (beta). There is no object storage or persistent volume yet.
- **Config and secrets.** `guidal env set` for configuration, `guidal secrets` for credentials.
  Linking a database sets `DATABASE_URL`.
- **TLS** ends at the platform edge; apps serve plain HTTP behind it.
- **Shutdown.** Pods get 30 s; web services spend the first 5 s draining traffic, leaving
  about 25 s after SIGTERM. Workers are allowed 30 s after SIGTERM, but today the worker wrapper exits as
  soon as it forwards the signal, so keep units of work short and safe to redo.

## License

[MIT](LICENSE)
