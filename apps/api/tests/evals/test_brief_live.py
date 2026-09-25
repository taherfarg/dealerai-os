"""Live eval: the morning brief's headline, written by the real model.

Excluded from the default run: `npm run eval:brief` (about $0.002).

tests/test_brief.py fakes the model, and a fake always obeys the facts guard.
This is where the real one writes three mornings' headlines, in both
languages, and has to use only the numbers it was given.
"""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from conftest import TENANT_A
from dealerai.agents.sales import brief
from dealerai.config import get_settings
from dealerai.guards import facts as facts_guard
from dealerai.sales.dashboard import render_facts
from dealerai.sales.runs import agent_run

pytestmark = [
    pytest.mark.eval,
    pytest.mark.skipif(not get_settings().google_api_key, reason="GOOGLE_API_KEY not set"),
]

ARABIC = re.compile(r"[؀-ۿ]")
#: Where each morning's headline is written in full; gitignored.
REPORTS = Path(__file__).parent / "sales"
#: A Thursday, so the block says "Yesterday, Thursday 24 September".
DAY = date(2026, 9, 24)


def _facts(**overrides: Any) -> dict[str, Any]:
    return {
        "new_conversations": 23,
        "waiting_now": 3,
        "waiting_past_target": 2,
        "missed_targets": 2,
        "new_leads": 6,
        "hot_leads": 4,
        "hot_without_next_step": 1,
        "won": 1,
        "lost": 0,
        "overdue_tasks": 7,
        "replies_inbox": 41,
        "replies_phone": 3,
        "median_first_response_seconds": 245,
        "first_response_target_seconds": 300,
    } | overrides


def _rep(name: str, *, median: int, missed: int, overdue: int, won: int) -> dict[str, Any]:
    return {
        "name": name,
        "median_first_response_seconds": median,
        "missed_targets": missed,
        "overdue_tasks": overdue,
        "won_this_month": won,
    }


MORNINGS = {
    "busy": render_facts(
        DAY,
        _facts(),
        [
            _rep("Ahmed Nasser", median=180, missed=0, overdue=1, won=2),
            _rep("Salem Bousaid", median=420, missed=2, overdue=4, won=0),
        ],
        [("Toyota Land Cruiser 4.0 2024", 5), ("BYD Seal 05 2025", 3)],
    ),
    "quiet": render_facts(
        DAY,
        _facts(
            new_conversations=2,
            waiting_now=0,
            waiting_past_target=0,
            missed_targets=0,
            new_leads=0,
            hot_without_next_step=0,
            overdue_tasks=0,
            replies_inbox=2,
            replies_phone=0,
            median_first_response_seconds=120,
        ),
        [_rep("Ahmed Nasser", median=120, missed=0, overdue=0, won=0)],
        [],
    ),
    "slipping": render_facts(
        DAY,
        _facts(missed_targets=6, waiting_past_target=5, median_first_response_seconds=1260),
        [
            _rep("Salem Bousaid", median=1500, missed=5, overdue=9, won=0),
            _rep("Mohamed Riad", median=240, missed=1, overdue=0, won=1),
        ],
        [],
    ),
}


@pytest.mark.parametrize("morning", sorted(MORNINGS))
async def test_a_headline_uses_only_the_facts(db: None, seeded: None, morning: str) -> None:
    block = MORNINGS[morning]
    async with agent_run(TENANT_A, goal="brief", goal_input={"eval": morning}) as run:
        written = await brief.write(tenant_id=TENANT_A, run_id=run.id, facts=block)
    headline = written.headline
    report = f"[{morning}]\n  en: {headline and headline.en}\n  ar: {headline and headline.ar}\n"
    (REPORTS / f"last-brief-{morning}.md").write_text(report, encoding="utf-8")
    # A Windows console is cp1252: printing Arabic must not be what fails the
    # run. The file above is the real output.
    encoding = sys.stdout.encoding or "utf-8"
    print("\n" + report.encode(encoding, "replace").decode(encoding))

    assert headline is not None, "no headline came back"
    en, ar = headline.en.strip(), headline.ar.strip()
    assert en and ar
    assert ARABIC.search(ar), f"the Arabic line is not Arabic: {ar!r}"
    invented = facts_guard.check(f"{en}\n{ar}", facts=block)
    assert invented == [], f"a number the facts do not hold: {[f.detail for f in invented]}"
    assert len(en) <= 200 and len(ar) <= 200
