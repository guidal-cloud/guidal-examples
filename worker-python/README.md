# worker-python

A background worker: it does one unit of work every 30 seconds, logs each one as a JSON line,
and stops cleanly on SIGTERM. No port, no URL, no third-party packages.

- Port: none (a worker service has no ingress)
- User: `1000`
- Command: `python worker.py`
- Files: `worker.py`, `requirements.in` / `requirements.txt` (empty; hashes once you add
  packages), `Dockerfile`, `.dockerignore`

The platform wraps the worker's command in a heartbeat script that needs `/bin/sh`, `date` and
a writable `/tmp`; the `python:3.12-slim` base has all three.

## Deploy with the CLI

`guidal deploy` cannot create a worker. Build the image first, then create the service from it:

```bash
guidal deploy ./worker-python --name my-worker               # prints "Image: <ref>"
guidal services create --name my-worker --type worker --image <ref> --command "python worker.py"
```

## Deploy with the local MCP server

```text
deploy_from_source(path="/absolute/path/to/worker-python", service_name="my-worker", deploy=False)
get_build_status(build_id="...", wait_seconds=55)            # gives the image ref
create_service(name="my-worker", type="worker", image="<ref>", command="python worker.py")
```

## Verify

```bash
guidal logs query --service <service-id> --since 10m
# {"ts": "...", "msg": "worker started"}
# {"ts": "...", "msg": "unit done", "unit": 1}
guidal services diagnose <service-id>                       # if it keeps restarting
```

## Update

Put your work in `do_unit()` in `worker.py`, then:

```bash
guidal deploy ./worker-python --service my-worker
```

## Design notes

- **Shutdown.** Every redeploy, scale-down and node drain sends SIGTERM. The platform allows
  30 s before SIGKILL, but today the worker wrapper exits as soon as it forwards SIGTERM, so the
  process can be killed almost at once. Keep each unit short and idempotent: a unit
  interrupted half-way must be safe to redo (record completion by a key, e.g. a row id, and
  skip done work).
- **Failures.** An exception in a unit exits with code 1, so the platform restarts the worker
  and the failure shows in `guidal services diagnose`. The log line carries the error type
  only, not values that may contain secrets or personal data.
- **No local state.** The filesystem is read-only except `/tmp`, and `/tmp` is lost on every
  restart. Keep queues and progress in Postgres (or Redis, if losing it is acceptable).
- **Keep:** the SIGTERM handler, JSON logs on stdout, user 1000, the pinned base image.
- **For a real app:** pull work from a durable queue (a Postgres table with
  `SELECT ... FOR UPDATE SKIP LOCKED` works well) instead of a timer; secrets via
  `guidal secrets`, read from `os.environ`.
