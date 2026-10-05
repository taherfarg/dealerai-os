"""Both processes in one container: python -m dealerai.both

For a host that will run only one thing — Render's free plan has web services
and no background workers (docs/sales/10-staging.md § 4). Everywhere else the
API and the worker are two processes from the one image, started separately,
and that is better: there the host restarts whichever stops. Here a loop does.

The API is this process itself, so the host sees it start, stop and fail. The
worker is a child, kept running beside it.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from collections.abc import Callable, Sequence

import uvicorn

from .config import assert_deployable, get_settings

WORKER = (sys.executable, "-m", "dealerai.worker")

#: Long enough that a worker which cannot start does not spin; short enough
#: that one which fell over is back before anybody has waited on it.
RESTART_AFTER_SECONDS = 5.0


def keep_running(
    command: Sequence[str] = WORKER,
    *,
    stop: threading.Event,
    pause: float = RESTART_AFTER_SECONDS,
    start: Callable[[Sequence[str]], subprocess.Popen[bytes]] = subprocess.Popen,
) -> int:
    """Start the command again every time it ends, until told to stop.

    Returns how many times it was started.
    """
    started = 0
    while not stop.is_set():
        child = start(command)
        started += 1
        while (code := child.poll()) is None:
            if stop.wait(0.5):
                child.terminate()
                return started
        if stop.is_set():
            break
        print(
            f"worker ended with {code}; starting it again in {pause:g} s",
            file=sys.stderr,
            flush=True,
        )
        stop.wait(pause)
    return started


def main() -> None:
    # Before either starts: an unfit configuration should stop the container
    # once, by name — not be announced every few seconds by a worker in a loop.
    assert_deployable(get_settings())
    stop = threading.Event()
    threading.Thread(target=keep_running, kwargs={"stop": stop}, daemon=True).start()
    try:
        # The host says where to listen (Render: PORT, 10000).
        uvicorn.run("dealerai.main:app", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
    finally:
        stop.set()


if __name__ == "__main__":
    main()
