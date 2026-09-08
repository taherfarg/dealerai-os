"""Guardrails as code. See docs/01-system-architecture.md § 8.

Prompts are not a security boundary. Every guard here is a function that runs on
generated output, after the model and before the connector, and can block it.

They are pure: facts in, findings out. The caller has already loaded the vehicle
it is writing about, so a guard that fetched its own would be both slower and
harder to trust — a guard you cannot exercise from a unit test is a guard nobody
verifies.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Finding:
    """One reason the output cannot go out.

    `detail` names the offending thing — the figure, the word, the vehicle.
    A guard that says "brand violation" and nothing else cannot be acted on by
    an agent retrying, or by the human who gets it after that.
    """

    guard: str
    message: str
    detail: str | None = None


#: An empty list is a pass. There is no GuardResult wrapper: `if findings:` is
#: what every caller wants to write anyway.
Findings = list[Finding]
