"""Importing this package registers every handler.

Handlers register themselves with a decorator at import time, so a module
nobody imports is a handler nobody has. Until this file existed the worker
started with an empty registry and dead-lettered every event after its retries
ran out — silently, because an unregistered type looks exactly like a
mid-deploy race.

Adding a handler module means adding it here. The test in test_events.py
asserts the registry is non-empty for that reason.
"""

from __future__ import annotations

from . import inventory, runs

__all__ = ["inventory", "runs"]
