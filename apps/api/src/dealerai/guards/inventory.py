"""The inventory guard: never market a car the dealer no longer has.

A sold car offered to a customer costs the sale and the trust, and it is the
most visible way this product can embarrass a dealership — the post stays up,
the comments arrive, and the dealer finds out from a customer.
"""

from __future__ import annotations

from . import Finding, Findings

GUARD = "inventory"

#: The only status a vehicle may be marketed in. `reserved` is excluded on
#: purpose: it is somebody else's car until the deal falls through, and a post
#: about it generates enquiries the dealer has to disappoint.
MARKETABLE = frozenset({"available"})


def check(vehicles: dict[str, str]) -> Findings:
    """`vehicles` maps an identifier a human would recognise to its status.

    Keyed by stock number or id rather than taking a list of rows, so the
    finding can name the car. "A vehicle in this post is sold" is not something
    anyone can act on when the post covers four of them.
    """
    if not vehicles:
        return [Finding(GUARD, "this content references no vehicle at all")]
    return [
        Finding(GUARD, f"vehicle {ref} is {status}, not available", detail=ref)
        for ref, status in sorted(vehicles.items())
        if status not in MARKETABLE
    ]
