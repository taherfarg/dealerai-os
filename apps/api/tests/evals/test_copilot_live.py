"""The gates the copilot has to pass — docs/sales/04-ai-copilot.md § 9.

Everything else in this suite proves the code does what it was told. This
proves the drafts are any good, which no unit test can, and it is the exit
criterion for the slice.

It drives the **real handler**, not the agent, because what is being measured
is the product. Roughly USD 0.60 a run and about four minutes. Needs
GOOGLE_API_KEY; opt in with `npm run eval:sales`.

Real customer conversations never enter git. The labelled set from Pollux's
history lives in sales/private/, gitignored. What is committed is 40 synthetic
bursts in the same format, over a fixed inventory and three fixed policies.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from sales import fixtures
from sales.judge import AXES, Judged, judge, why, worst

from dealerai.agents.sales.intent import Read, classify
from dealerai.db.session import tenant_session
from dealerai.events.bus import Event
from dealerai.events.handlers import copilot
from dealerai.guards import price as price_guard

pytestmark = pytest.mark.eval

HERE = Path(__file__).parent / "sales"

GATES: dict[str, float] = {
    "intent_accuracy": 0.95,
    "intent_accuracy_per_language": 0.90,
    "wrong_price_or_availability": 0,
    "judge_mean": 4.0,
    "judge_accuracy_floor": 3,
    "latency_p95_seconds": 10.0,
    "cost_p95_usd": 0.015,
}


def _items() -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in (HERE / "synthetic.jsonl").read_text("utf-8").splitlines()
        if line.strip()
    ]


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(int(len(ordered) * 0.95), len(ordered) - 1)]


def _allowed_prices() -> set[Decimal]:
    """Every price in the fixed inventory, in the units a reply writes."""
    return {Decimal(row[4]) / 100 for row in fixtures.VEHICLES.values()}


def _facts_for(item: dict[str, Any]) -> str:
    """What the judge is told the copilot was allowed to know."""
    lines = []
    for key, (make, model, trim, year, price, status, colour, km) in fixtures.VEHICLES.items():
        lines.append(
            f"- {make} {model} {trim} {year}: AED {price // 100:,}, {status}, {colour}, {km:,} km"
            + ("  <- the car they asked about" if key == item.get("vehicle") else "")
        )
    # The policies as well as the stock. Without them the judge marks every
    # correct export or finance answer as stating facts it was never given —
    # which is what the first full run did, five times, at accuracy 1.
    policies = "\n\n".join(
        path.read_text("utf-8") for path in sorted((HERE / "policies").glob("*.md"))
    )
    return (
        f"The customer's name: {fixtures.NAMES[item['language']]}\n\n"
        "The dealership's stock:\n"
        + "\n".join(lines)
        + "\n\nThe dealership's own policy documents, which the copilot can quote:\n"
        + policies
    )


async def _run_one(world: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    """One item, through the real draft handler, timed.

    The conversation is committed before the handler runs, in its own session:
    `tenant_session` opens a transaction, and the handler takes a different
    connection out of the pool. Holding the inserts open means it sees no
    conversation at all — which is what production does too, where the webhook
    commits before the worker claims the event.
    """
    async with tenant_session(world["tenant"]) as conn:
        conversation_id, message_id = await fixtures.a_conversation(conn, world, item)

    started = time.perf_counter()
    await copilot.on_draft_requested(
        Event(
            id=1,
            tenant_id=world["tenant"],
            event_type="copilot.draft_requested",
            payload={
                "conversation_id": str(conversation_id),
                "message_id": str(message_id),
            },
            attempts=1,
            dedupe_key=None,
        )
    )
    latency = time.perf_counter() - started

    async with tenant_session(world["tenant"]) as conn:
        row = await conn.fetchrow(
            """select s.status, s.text, s.template, s.confidence, s.intent, s.sources,
                      s.needs_human, s.blocked_reason, r.cost_usd
                 from ai_suggestions s left join agent_runs r on r.id = s.run_id
                where s.conversation_id = $1 order by s.created_at desc limit 1""",
            conversation_id,
        )
    return {
        "item": item,
        "row": dict(row) if row else None,
        "latency": latency,
        "conversation": conversation_id,
    }


async def test_the_gates(db: None, su: asyncpg.Connection) -> None:
    items = _items()
    world = await fixtures.build(su)

    results: list[dict[str, Any]] = []
    for item in items:
        results.append(await _run_one(world, item))

    # --- intent ------------------------------------------------------------
    intent_hits: dict[str, list[bool]] = {}
    for result in results:
        row, item = result["row"], result["item"]
        got = (row or {}).get("intent")
        if got is None and item.get("expect_no_draft"):
            # An opt-out is classified and then stops the run before a draft.
            got = await _reclassify(world["tenant"], item)
        wanted = {item["intent"], *item.get("intent_alt", [])}
        hit = got in wanted
        intent_hits.setdefault(item["language"], []).append(hit)
        intent_hits.setdefault("all", []).append(hit)
        result["intent_hit"] = hit
        result["intent_got"] = got

    # --- facts, by the real guards rather than an opinion -------------------
    wrong_facts: list[str] = []
    for result in results:
        text = _sent_text(result["row"])
        if not text:
            continue
        # Prices generically — a figure not in the stock is always wrong. Cars
        # only through each item's must_not_contain: "We don't currently have
        # a BMW X5 in stock" names a sold car and is exactly right, so a check
        # that flags any mention of one measures the wrong thing. It did, on
        # the first full run.
        findings = [*price_guard.check(text, allowed=_allowed_prices())]
        for phrase in result["item"].get("must_not_contain", []):
            if phrase.casefold() in text.casefold():
                findings.append(price_guard.Finding("eval", f"says {phrase!r}, which it must not"))
        if findings:
            wrong_facts.append(f"{result['item']['id']}: {findings[0].message}")

    # --- the judge ---------------------------------------------------------
    judged: list[tuple[str, Any]] = []
    judge_cost = 0.0
    for result in results:
        text = _sent_text(result["row"])
        item = result["item"]
        if not text or item.get("expect_no_draft"):
            continue
        answer: Judged = await judge(
            tenant_id=world["tenant"],
            customer=item["messages"][-1]["text"],
            facts=_facts_for(item),
            draft=text,
            reference=item.get("reference", ""),
        )
        judge_cost += answer.cost_usd
        if answer.scores is not None:
            judged.append((item["id"], answer.scores))

    # --- the numbers -------------------------------------------------------
    rate = lambda rows: (sum(rows) / len(rows)) if rows else 0.0  # noqa: E731
    per_language = {
        language: rate(rows) for language, rows in sorted(intent_hits.items()) if language != "all"
    }
    means = [scores.mean for _, scores in judged]
    accuracy_floor = min((scores.accuracy for _, scores in judged), default=5)
    latencies = [result["latency"] for result in results]
    costs = [float(result["row"]["cost_usd"] or 0) for result in results if result["row"]]

    report = _report(
        results=results,
        intent_overall=rate(intent_hits.get("all", [])),
        per_language=per_language,
        wrong_facts=wrong_facts,
        judged=judged,
        means=means,
        accuracy_floor=accuracy_floor,
        latencies=latencies,
        costs=costs,
        judge_cost=judge_cost,
    )
    (HERE / "last-report.md").write_text(report, encoding="utf-8")
    # A Windows console is cp1252 and the report is full of ≥ and —; printing
    # it must not be what fails the run. The file above is the real output.
    encoding = sys.stdout.encoding or "utf-8"
    print("\n" + report.encode(encoding, "replace").decode(encoding))

    # --- the gates ---------------------------------------------------------
    assert rate(intent_hits["all"]) >= GATES["intent_accuracy"], report
    for language, value in per_language.items():
        assert value >= GATES["intent_accuracy_per_language"], f"{language}: {value:.0%}\n{report}"
    assert not wrong_facts, report
    assert statistics.mean(means) >= GATES["judge_mean"], report
    assert accuracy_floor >= GATES["judge_accuracy_floor"], report
    assert _p95(latencies) <= GATES["latency_p95_seconds"], report
    assert _p95(costs) <= GATES["cost_p95_usd"], report


async def _reclassify(tenant_id: uuid.UUID, item: dict[str, Any]) -> str:
    """An opt-out never reaches a suggestion row, but it was still classified."""
    classified = await classify(
        tenant_id=tenant_id,
        run_id=None,
        conversation_tail=[(m["direction"], m["text"]) for m in item["messages"]],
    )
    read: Read = classified.read
    return read.intent


def _sent_text(row: dict[str, Any] | None) -> str:
    if row is None or row["status"] != "ready":
        return ""
    if row["text"]:
        return str(row["text"])
    template = json.loads(row["template"]) if isinstance(row["template"], str) else row["template"]
    return " ".join(str(value) for value in (template or {}).get("variables", []))


def _report(**data: Any) -> str:
    results = data["results"]
    judged = data["judged"]
    means = data["means"]
    blocked = [r["item"]["id"] for r in results if (r["row"] or {}).get("status") == "blocked"]
    no_draft = [r["item"]["id"] for r in results if not (r["row"] or {}).get("text")]

    def verdict(value: float, gate: float, higher_is_better: bool = True) -> str:
        ok = value >= gate if higher_is_better else value <= gate
        return "PASS" if ok else "FAIL"

    languages = " ".join(f"{k} {v:.0%}" for k, v in data["per_language"].items())
    intent_verdict = (
        "PASS"
        if data["intent_overall"] >= GATES["intent_accuracy"]
        and all(v >= GATES["intent_accuracy_per_language"] for v in data["per_language"].values())
        else "FAIL"
    )
    mean = statistics.mean(means) if means else 0.0
    lines = [
        f"# Sales copilot eval — {len(results)} items — {time.strftime('%Y-%m-%d %H:%M')}",
        "",
        "| gate | result | bar | |",
        "|---|---|---|---|",
        f"| intent accuracy | {data['intent_overall']:.1%} ({languages}) | ≥95% / ≥90% each |"
        f" {intent_verdict} |",
        f"| wrong price or stock | {len(data['wrong_facts'])} | 0 |"
        f" {'PASS' if not data['wrong_facts'] else 'FAIL'} |",
        f"| judge mean | {mean:.2f} | ≥4.0 | {verdict(mean, GATES['judge_mean'])} |",
        f"| judge accuracy floor | {data['accuracy_floor']} | ≥3 |"
        f" {verdict(data['accuracy_floor'], GATES['judge_accuracy_floor'])} |",
        f"| latency p95 | {_p95(data['latencies']):.1f}s | ≤10s |"
        f" {verdict(_p95(data['latencies']), GATES['latency_p95_seconds'], False)} |",
        f"| cost p95 | ${_p95(data['costs']):.4f} | ≤$0.015 |"
        f" {verdict(_p95(data['costs']), GATES['cost_p95_usd'], False)} |",
        "",
        f"Total spend this run: ${sum(data['costs']) + data['judge_cost']:.2f} "
        f"(drafts ${sum(data['costs']):.2f}, judge ${data['judge_cost']:.2f})",
        "",
    ]

    if data["wrong_facts"]:
        lines += ["## Wrong facts — the one gate that is zero", ""]
        lines += [f"- {row}" for row in data["wrong_facts"]] + [""]

    misread = [
        f"- {r['item']['id']}: wanted {r['item']['intent']}, read {r['intent_got']}"
        for r in results
        if not r["intent_hit"]
    ]
    if misread:
        lines += ["## Misread intents", ""] + misread + [""]

    # By name, with the judge's reason: a failing floor that does not say which
    # draft failed it cost a whole run to find out.
    floor = GATES["judge_accuracy_floor"]
    under = [(i, s) for i, s in judged if s.accuracy < floor]
    if under:
        lines += [f"## Under the accuracy floor of {floor}", ""]
        lines += [f"- **{i}** {s.accuracy}: {why(s, 'accuracy')}" for i, s in under] + [""]

    weak = sorted(judged, key=lambda pair: pair[1].mean)[:5]
    lines += ["## Weakest five, by the judge", ""]
    for item_id, scores in weak:
        axis, value = worst(scores)
        lines.append(f"- **{item_id}** {scores.mean:.1f} — {axis} {value}: {why(scores, axis)}")
    lines.append("")

    # Calibration: acceptance is not measurable in an eval, so the proxy is the
    # judge's own mean per band. If these are not ordered, the thresholds in
    # sales/confidence.py are wrong and this is where it shows.
    by_band: dict[str, list[float]] = {}
    scores_by_id = dict(judged)
    for result in results:
        band = (result["row"] or {}).get("confidence")
        if band and result["item"]["id"] in scores_by_id:
            by_band.setdefault(band, []).append(scores_by_id[result["item"]["id"]].mean)
    if by_band:
        ordered = " > ".join(
            f"{band} {statistics.mean(values):.2f}"
            for band, values in sorted(by_band.items(), key=lambda pair: -statistics.mean(pair[1]))
        )
        lines += [f"**Confidence calibration** (judge mean by band): {ordered}", ""]

    if blocked:
        lines += [f"**Blocked**: {', '.join(blocked)}", ""]
    if no_draft:
        lines += [f"**No draft**: {', '.join(no_draft)}", ""]
    by_axis = {
        axis: statistics.mean([getattr(scores, axis) for _, scores in judged])
        for axis in AXES
        if judged
    }
    if by_axis:
        lines.append(
            "**By axis**: " + " · ".join(f"{axis} {value:.2f}" for axis, value in by_axis.items())
        )
    return "\n".join(lines)
