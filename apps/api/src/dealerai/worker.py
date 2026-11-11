"""Worker entrypoint: python -m dealerai.worker

Same image as the API, different process. A slow agent run must never block an
HTTP request.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal

import structlog

# Imported for its side effects: this is what registers the handlers.
from . import agents as _agents  # noqa: F401  registers the agents
from . import tools as _tools  # noqa: F401  registers the agent tools
from .config import assert_deployable, get_settings
from .core.logging import configure_logging
from .db import session
from .events import handlers as _handlers  # noqa: F401
from .events.worker import Worker
from .sales import clock

log = structlog.get_logger()

CONCURRENCY = 2

#: How often every tenant's next brief and retention pass is checked
#: (sales/clock.py). Two inserts per tenant, which the dedupe key almost
#: always turns into nothing.
CLOCK_EVERY_SECONDS = 3600


async def keep_the_clocks(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await clock.schedule_everyone()
        except Exception:
            # The next pass is the retry. A worker that dies here stops
            # answering customers to protect a morning brief.
            log.exception("clock_pass_failed")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=CLOCK_EVERY_SECONDS)


async def main() -> None:
    configure_logging()
    settings = get_settings()
    assert_deployable(settings)
    await session.init_pool()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, AttributeError):
            # Windows has no add_signal_handler; KeyboardInterrupt covers dev there.
            loop.add_signal_handler(sig, stop.set)

    workers = [Worker(f"worker-{i}") for i in range(CONCURRENCY)]
    log.info("worker_started", env=settings.env, concurrency=CONCURRENCY)
    try:
        await asyncio.gather(*(w.run_forever(stop) for w in workers), keep_the_clocks(stop))
    finally:
        await session.close_pool()
        log.info("worker_stopped")


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
