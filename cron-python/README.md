# cron-python

A scheduled job: it runs once, logs a JSON result line to stdout and exits 0. An exception
exits 1, and SIGTERM (timeout, node drain) exits 143; both mark the run as failed.

- Port: none
- User: `1000`
- Command: `python job.py` (the cron job's command replaces the image's `ENTRYPOINT`)
- Files: `job.py`, `requirements.in` / `requirements.txt` (empty; hashes once you add
  packages), `Dockerfile`, `.dockerignore`

A cron job cannot be linked to a database yet. Runs time out after 3600 seconds by default.

## Deploy with the CLI

Cron jobs run a prebuilt image. Build it, then create the schedule:

```bash
guidal deploy ./cron-python --name my-job                    # prints "Image: <ref>"
guidal cron create --name my-job --slug my-job --image <ref> \
  --command "python job.py" --schedule "*/15 * * * *" --timezone UTC --concurrency-policy Forbid
```

## Deploy with the local MCP server

```text
deploy_from_source(path="/absolute/path/to/cron-python", service_name="my-job", deploy=False)
get_build_status(build_id="...", wait_seconds=55)            # gives the image ref
call_capability("create_cron_job", {"name": "my-job", "slug": "my-job", "image": "<ref>",
  "command": "python job.py", "schedule": "*/15 * * * *"})
```

## Verify

```bash
guidal cron trigger <cron-job-id>     # run once now
guidal cron history <cron-job-id>     # expect Succeeded
guidal logs query --cron-job <cron-job-id> --since 1h
# {"ts": "...", "msg": "job done", "job": "cron-python", "started": "...", "result": 5050}
```

## Update

Edit `main()` in `job.py`, then build a new image and point the job at it:

```bash
guidal deploy ./cron-python --name my-job                    # prints the new "Image: <ref>"
guidal cron update <cron-job-id> --image <ref>
```

## Design notes

- **Exit codes are the result.** 0 is success; anything else is a failed run in
  `guidal cron history`. Do not catch and swallow errors.
- **Idempotent runs.** A run can be retried, stopped half-way, or (without
  `--concurrency-policy Forbid`) overlap the next one. Make the work safe to repeat: process
  "everything not yet marked done", not "everything since the last run".
- **Keep:** the SIGTERM handler, JSON logs without secrets or personal data, user 1000, the
  pinned base image, a read-only filesystem (write scratch files to `/tmp` only).
- **For a real app:** keep the run well under the timeout; for long work, have the cron job
  enqueue it and let a worker process it.
