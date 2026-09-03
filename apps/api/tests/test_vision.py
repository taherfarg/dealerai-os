"""Photo QA logic. No model calls — ranking and hero selection are pure.

The accuracy of the model's judgement is a separate question, checked by the
live eval in tests/evals/test_vision_live.py.
"""

from __future__ import annotations

import uuid

import pytest

from dealerai.media.vision import (
    HERO_PREFERENCE,
    MIN_USABLE_SCORE,
    Angle,
    PhotoAssessment,
    rank,
)

ANGLES: tuple[Angle, ...] = (
    "front",
    "front_three_quarter",
    "side",
    "rear_three_quarter",
    "rear",
    "interior_front",
    "interior_rear",
    "dashboard",
    "detail",
    "engine",
    "wheel",
    "unknown",
)


def photo(
    angle: Angle = "front_three_quarter",
    score: float = 0.8,
    *,
    rejected: bool = False,
    branding: bool = False,
) -> PhotoAssessment:
    return PhotoAssessment(
        angle=angle,
        quality_score=score,
        rejected=rejected,
        rejection_reason="blurry" if rejected else None,
        shows_other_branding=branding,
    )


def ids(n: int) -> list[uuid.UUID]:
    return [uuid.UUID(int=i) for i in range(1, n + 1)]


# --------------------------------------------------------------------------
# the schema is the contract with the database
# --------------------------------------------------------------------------


def test_angle_literal_matches_the_database_constraint() -> None:
    """A value the schema allows and the CHECK constraint does not is an insert
    failure at 2am, on a code path nobody watches."""
    import pathlib
    import re

    sql = (
        pathlib.Path(__file__)
        .parents[3]
        .joinpath("supabase/migrations/0001_init.sql")
        .read_text(encoding="utf-8")
    )
    start = sql.index("check (angle in")
    block = sql[start : sql.index("))", start)]
    in_db = set(re.findall(r"'([a-z_]+)'", block))
    assert in_db, "could not parse the angle CHECK constraint"
    assert set(ANGLES) == in_db, f"schema/DB angle mismatch: {set(ANGLES) ^ in_db}"


def test_quality_score_is_bounded_like_the_column() -> None:
    with pytest.raises(ValueError):
        PhotoAssessment(angle="front", quality_score=1.5, rejected=False)
    with pytest.raises(ValueError):
        PhotoAssessment(angle="front", quality_score=-0.1, rejected=False)


# --------------------------------------------------------------------------
# hero selection
# --------------------------------------------------------------------------


def test_exactly_one_hero() -> None:
    """Two heroes or none is a broken vehicle page. Decided in code because a
    per-photo model call cannot see the other photos."""
    a, b, c = ids(3)
    ranked = rank({a: photo("side"), b: photo("front_three_quarter"), c: photo("rear")})
    assert sum(p.is_hero for p in ranked) == 1


def test_hero_prefers_front_three_quarter_over_a_higher_scoring_side() -> None:
    """The automotive convention, and it beats raw score: a stunning side shot
    still does not show the car's face."""
    side, threequarter = ids(2)
    ranked = rank({side: photo("side", 0.95), threequarter: photo("front_three_quarter", 0.6)})
    hero = next(p for p in ranked if p.is_hero)
    assert hero.media_id == threequarter


def test_score_breaks_ties_within_the_same_angle() -> None:
    low, high = ids(2)
    ranked = rank({low: photo("front_three_quarter", 0.5), high: photo("front_three_quarter", 0.9)})
    assert next(p for p in ranked if p.is_hero).media_id == high


def test_a_vehicle_with_only_rejected_photos_gets_no_hero() -> None:
    """Promoting the least-bad rejected shot would put a blurry car on
    Instagram, which is the outcome this module exists to prevent."""
    a, b = ids(2)
    ranked = rank({a: photo(rejected=True), b: photo(rejected=True, score=0.4)})
    assert not any(p.is_hero for p in ranked)
    assert len(ranked) == 2, "rejected photos are kept, not dropped"


def test_any_exterior_beats_an_interior_however_good() -> None:
    """A listing that leads with a photo of the steering wheel is a listing
    nobody clicks. Every exterior angle outranks every interior one."""
    interior, exterior = ids(2)
    ranked = rank({interior: photo("interior_front", 0.99), exterior: photo("rear", 0.4)})
    assert next(p for p in ranked if p.is_hero).media_id == exterior


def test_interior_becomes_hero_only_when_no_exterior_exists() -> None:
    interior, dash = ids(2)
    ranked = rank({interior: photo("interior_front", 0.8), dash: photo("dashboard", 0.6)})
    assert next(p for p in ranked if p.is_hero).media_id == interior


def test_a_lone_detail_shot_still_becomes_hero() -> None:
    """Better a wheel close-up than an empty vehicle page."""
    only = ids(1)[0]
    ranked = rank({only: photo("wheel", 0.7)})
    assert ranked[0].is_hero


# --------------------------------------------------------------------------
# exclusion
# --------------------------------------------------------------------------


def test_rejected_photos_are_never_usable_or_hero() -> None:
    good, bad = ids(2)
    ranked = rank(
        {good: photo("side", 0.5), bad: photo("front_three_quarter", 0.99, rejected=True)}
    )
    assert next(p for p in ranked if p.is_hero).media_id == good


def test_another_dealers_branding_excludes_a_photo_however_good() -> None:
    """These are usually scraped from a previous seller's listing. Publishing
    one advertises a competitor from the dealer's own account."""
    branded, plain = ids(2)
    ranked = rank(
        {
            branded: photo("front_three_quarter", 0.99, branding=True),
            plain: photo("rear", 0.4),
        }
    )
    assert next(p for p in ranked if p.is_hero).media_id == plain


def test_photos_below_the_usable_score_are_excluded() -> None:
    weak, ok = ids(2)
    ranked = rank(
        {weak: photo("front_three_quarter", MIN_USABLE_SCORE - 0.01), ok: photo("rear", 0.9)}
    )
    assert next(p for p in ranked if p.is_hero).media_id == ok


def test_a_photo_exactly_on_the_threshold_is_usable() -> None:
    only = ids(1)[0]
    ranked = rank({only: photo("side", MIN_USABLE_SCORE)})
    assert ranked[0].is_hero


# --------------------------------------------------------------------------
# ordering
# --------------------------------------------------------------------------


def test_sort_order_is_dense_and_starts_at_zero() -> None:
    a, b, c = ids(3)
    ranked = rank({a: photo("rear"), b: photo("front_three_quarter"), c: photo(rejected=True)})
    assert [p.sort_order for p in ranked] == [0, 1, 2]


def test_rejected_photos_sort_after_every_usable_one() -> None:
    """A human should still be able to see what was dropped and why."""
    good, bad = ids(2)
    ranked = rank({bad: photo(rejected=True, score=0.9), good: photo("rear", 0.4)})
    assert ranked[0].media_id == good
    assert ranked[-1].media_id == bad
    assert ranked[-1].assessment.rejection_reason == "blurry"


def test_ranking_is_deterministic() -> None:
    """Two runs over the same assessments must not reshuffle a dealer's gallery."""
    assessments = {mid: photo(a, 0.7) for mid, a in zip(ids(len(ANGLES)), ANGLES, strict=True)}
    first = [(p.media_id, p.sort_order, p.is_hero) for p in rank(assessments)]
    second = [(p.media_id, p.sort_order, p.is_hero) for p in rank(assessments)]
    assert first == second


def test_no_photos_at_all_is_not_an_error() -> None:
    assert rank({}) == []


def test_every_hero_preference_is_a_real_angle() -> None:
    assert set(HERO_PREFERENCE) <= set(ANGLES)
