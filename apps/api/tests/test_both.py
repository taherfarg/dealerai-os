"""`python -m dealerai.both`: the API and the worker in one container.

For a host that will only run one thing. Nothing here starts a real process or
opens a port: the child is a stand-in, and uvicorn is watched, not run.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence

import pytest

from dealerai import both
from dealerai.config import Settings


class Child:
    """A process, as far as `keep_running` can tell."""

    def __init__(self, ends_with: int | None) -> None:
        self.ends_with = ends_with
        self.terminated = False

    def poll(self) -> int | None:
        return self.ends_with

    def terminate(self) -> None:
        self.terminated = True


def test_a_worker_that_ends_is_started_again() -> None:
    stop = threading.Event()
    children: list[Child] = []

    def start(command: Sequence[str]) -> Child:
        assert tuple(command) == both.WORKER
        children.append(Child(ends_with=1))
        if len(children) == 3:
            stop.set()
        return children[-1]

    assert both.keep_running(stop=stop, pause=0, start=start) == 3  # type: ignore[arg-type]
    assert not any(child.terminated for child in children), "they had already ended"


def test_told_to_stop_it_ends_the_worker_and_starts_no_other() -> None:
    stop = threading.Event()
    children: list[Child] = []

    def start(command: Sequence[str]) -> Child:
        children.append(Child(ends_with=None))  # still running, however often it is asked
        stop.set()
        return children[-1]

    assert both.keep_running(stop=stop, pause=0, start=start) == 1  # type: ignore[arg-type]
    assert children[0].terminated


def unfit() -> Settings:
    """Outside a laptop, with nothing a deployment needs."""
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        env="staging",
        database_url="postgresql://dealerai_app:secret@pooler.supabase.com:5432/postgres",
        supabase_url=None,
        supabase_jwt_secret=None,
        storage_dir=None,
    )


def test_an_unfit_configuration_stops_both_before_either_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Said once, by name, as the container stops — not every five seconds by
    a worker in a loop."""
    started: list[str] = []
    monkeypatch.setattr(both, "get_settings", unfit)
    monkeypatch.setattr(both, "keep_running", lambda **_: started.append("worker"))
    monkeypatch.setattr(both.uvicorn, "run", lambda *_, **__: started.append("api"))

    with pytest.raises(RuntimeError, match="SUPABASE_URL"):
        both.main()
    assert started == []


def test_it_listens_where_the_host_says_and_keeps_the_worker_beside_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    served: dict[str, object] = {}
    beside = threading.Event()
    stops: list[threading.Event] = []

    def keep_running(*, stop: threading.Event) -> int:
        stops.append(stop)
        beside.set()
        return 0

    def run(app: str, *, host: str, port: int) -> None:
        # The worker's thread is under way before the API takes the process.
        assert beside.wait(2)
        served.update(app=app, host=host, port=port)

    monkeypatch.setenv("PORT", "10000")  # what Render gives a web service
    monkeypatch.setattr(both, "keep_running", keep_running)
    monkeypatch.setattr(both.uvicorn, "run", run)

    both.main()

    assert served == {"app": "dealerai.main:app", "host": "0.0.0.0", "port": 10000}
    # When the API ends, the worker is told to.
    assert stops[0].is_set()
