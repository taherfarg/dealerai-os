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


#: How a reply says a car can be had, as substrings: "متوفر" catches "متوفرة",
#: and "available" catches "not available" too — a retry for an honest reply,
#: which is cheaper than a customer driving over for somebody else's car.
AVAILABLE = ("available", "in stock", "متوفر", "متاح", "موجود", "disponible", "en stock")


def check_held(text: str, *, held: str | None) -> Findings:
    """A reserved car — somebody else's — called available anyway.

    `held` is a reserved car the reply names, or the one they asked about when
    every row matching it is reserved; else None. Checked on the words rather
    than on the name, because the name is what an Arabic reply does not keep:
    the eval's drafts said "متوفر عندنا … لكنها محجوزة" — we have it, but it is
    reserved — about a "باترول" the name match never saw, in four runs of ten.
    """
    if held is None:
        return []
    said = next((word for word in AVAILABLE if word in text.casefold()), None)
    if said is None:
        return []
    return [
        Finding(
            GUARD,
            f"the {held} is reserved for another customer, and this says {said!r}: say that "
            "it is reserved, and offer any other car without that word",
            detail=said,
        )
    ]
