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
from .config import get_settings
from .core.logging import configure_logging
from .db import session
from .events import handlers as _handlers  # noqa: F401
from .events.worker import Worker

log = structlog.get_logger()

CONCURRENCY = 2


async def main() -> None:
    configure_logging()
    settings = get_settings()
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
        await asyncio.gather(*(w.run_forever(stop) for w in workers))
    finally:
        await session.close_pool()
        log.info("worker_stopped")


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
