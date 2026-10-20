"""A scheduled job: do one thing, log a JSON result line, exit.

Exit 0 means the run succeeded; any other code marks it failed. A run can be
stopped (timeout, node drain): on SIGTERM it stops and exits 143, so the run is
recorded as failed rather than silently half-done. Make the work idempotent so a
retried or overlapping run cannot double-apply it.
"""

import json
import signal
import sys
from datetime import UTC, datetime


def log(msg: str, **fields) -> None:
    # One JSON object per line on stdout. Never log secrets, tokens or personal data.
    print(json.dumps({"ts": datetime.now(UTC).isoformat(), "msg": msg, **fields}), flush=True)


def handle_stop(signum, _frame) -> None:
    log("stopped before finishing", signal=signum)
    sys.exit(128 + signum)


def main() -> int:
    signal.signal(signal.SIGTERM, handle_stop)
    started = datetime.now(UTC)
    try:
        # Replace this with your real job.
        total = sum(range(1, 101))
    except Exception as exc:
        log("job failed", error=type(exc).__name__)
        return 1
    log("job done", job="cron-python", started=started.isoformat(), result=total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
