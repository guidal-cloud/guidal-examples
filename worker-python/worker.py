"""A background worker: one short, idempotent unit of work every INTERVAL_SECONDS.

Shutdown: the platform sends SIGTERM on every redeploy, scale-down and node drain.
It allows 30 s before SIGKILL, but today the worker wrapper exits as soon as it
forwards SIGTERM, so the process can be killed almost at once. Keep each unit short
and idempotent: a unit interrupted half-way must be safe to run again.
"""

import json
import signal
import sys
import threading
from datetime import UTC, datetime

INTERVAL_SECONDS = 30
stop = threading.Event()


def log(msg: str, **fields) -> None:
    # One JSON object per line on stdout. Never log secrets, tokens or personal data.
    print(json.dumps({"ts": datetime.now(UTC).isoformat(), "msg": msg, **fields}), flush=True)


def handle_stop(signum, _frame) -> None:
    log("stop requested", signal=signum)
    stop.set()


def do_unit(unit: int) -> None:
    # Replace with your real work. Make it idempotent: derive a key from the input
    # (e.g. a row id) and skip work already recorded as done.
    log("unit done", unit=unit)


def main() -> int:
    signal.signal(signal.SIGTERM, handle_stop)
    signal.signal(signal.SIGINT, handle_stop)
    log("worker started")
    unit = 0
    while not stop.is_set():
        unit += 1
        try:
            do_unit(unit)
        except Exception as exc:
            # Exit non-zero so the platform restarts the worker and the failure shows
            # in `guidal services diagnose`. Log the type, not values that may be secret.
            log("unit failed", unit=unit, error=type(exc).__name__)
            return 1
        stop.wait(INTERVAL_SECONDS)
    log("worker stopped cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
