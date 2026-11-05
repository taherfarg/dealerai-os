"""Sourcing and appraisal (Lifecycle L5): what to buy, and the most to pay.

All of it is for `costs.view`: a bid is what the dealer would pay, and the
valuation is read from what it paid before. The session is cleared for the buy
side for the same callers, through `acquisition._session`.

Nothing here writes. The buying list is read from what customers asked for
(`customer_wants`, filled by the `sourcing.interest_changed` handler); an
appraisal is arithmetic on the dealer's own sales. The bid is a person's to
make, and they make it by buying the car, which L1 records.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field

from ..deps import TenantContext, require_permission
from ..lifecycle import pricing, sourcing
from .acquisition import MoneyOut, _money, _session, _tenant_currency
from .recon import InspectionOut, describe, photos_of, read_photos

router = APIRouter(prefix="/v1/sourcing", tags=["sourcing"])

Viewer = Annotated[TenantContext, Depends(require_permission("costs.view"))]


class AskerOut(BaseModel):
    contact_id: UUID
    name: str | None
    model_year: int | None
    #: The customer's own words that name the car.
    quoted: str
    budget: MoneyOut | None
    destination: str | None
    asked_at: datetime


class WorthOut(BaseModel):
    """The dealer's own sales of this make and model in the last year."""

    sold: int
    price: MoneyOut | None
    landed: MoneyOut | None
    on_top: MoneyOut | None
    days_to_sell: int | None


class BidOut(BaseModel):
    expected_price: MoneyOut
    price_from: sourcing.Source
    target_margin_bps: int
    margin: MoneyOut
    on_top: MoneyOut
    on_top_from: sourcing.Source
    holding: MoneyOut
    days_to_sell: int
    days_from: sourcing.Source
    repairs: MoneyOut
    max_bid: MoneyOut


class WantedOut(BaseModel):
    make: str
    model: str
    askers: list[AskerOut]
    worth: WorthOut
    bid: BidOut | None


class BuyingListOut(BaseModel):
    since: datetime
    days: int
    currency: str
    cars: list[WantedOut]


class AppraiseIn(BaseModel):
    make: str = Field(min_length=1, max_length=60)
    model: str = Field(min_length=1, max_length=80)
    model_year: int | None = Field(default=None, ge=1950, le=2100)
    #: What the dealer expects to sell it at; wins over the history.
    expected_price_minor: int | None = Field(default=None, ge=0)
    #: Freight, customs and fees on top of the purchase; wins over the history.
    on_top_minor: int | None = Field(default=None, ge=0)
    #: The repairs it needs — for a trade-in, the findings a person kept.
    repairs_minor: int = Field(default=0, ge=0)


class AppraisalOut(BaseModel):
    make: str
    model: str
    model_year: int | None
    currency: str
    worth: WorthOut
    bid: BidOut | None


def _worth(worth: sourcing.Worth, currency: str) -> dict[str, Any]:
    return {
        "sold": worth.sold,
        "price": _money(worth.price_minor, currency),
        "landed": _money(worth.landed_minor, currency),
        "on_top": _money(worth.on_top_minor, currency),
        "days_to_sell": worth.days_to_sell,
    }


def _bid(
    bid: sourcing.Bid | None, currency: str, settings: pricing.PricingSettings
) -> dict[str, Any] | None:
    if bid is None:
        return None
    return {
        "expected_price": _money(bid.expected_price_minor, currency),
        "price_from": bid.price_from,
        "target_margin_bps": settings.target_margin_bps,
        "margin": _money(bid.margin_minor, currency),
        "on_top": _money(bid.on_top_minor, currency),
        "on_top_from": bid.on_top_from,
        "holding": _money(bid.holding_minor, currency),
        "days_to_sell": bid.days_to_sell,
        "days_from": bid.days_from,
        "repairs": _money(bid.repairs_minor, currency),
        "max_bid": _money(bid.max_bid_minor, currency),
    }


@router.get("/buying-list", response_model=BuyingListOut)
async def buying_list(ctx: Viewer) -> dict[str, Any]:
    """The cars customers asked for in the last 30 days that the dealer has
    neither in stock nor on its way, with what its own history says each is
    worth and the most to pay."""
    since = datetime.now(UTC) - timedelta(days=sourcing.WANT_DAYS)
    async with _session(ctx) as conn:
        settings = await pricing.settings_for(conn, ctx.tenant_id)
        made = await sourcing.buying_list(conn, ctx.tenant_id, since=since, settings=settings)
    currency = made.currency
    return {
        "since": made.since,
        "days": sourcing.WANT_DAYS,
        "currency": currency,
        "cars": [
            {
                "make": car.make,
                "model": car.model,
                "askers": [
                    {
                        "contact_id": a.contact_id,
                        "name": a.name,
                        "model_year": a.model_year,
                        "quoted": a.quoted,
                        "budget": (
                            _money(a.budget_minor, a.budget_currency or currency)
                            if a.budget_minor is not None
                            else None
                        ),
                        "destination": a.destination,
                        "asked_at": a.asked_at,
                    }
                    for a in car.askers
                ],
                "worth": _worth(car.worth, currency),
                "bid": _bid(car.bid, currency, settings),
            }
            for car in made.cars
        ],
    }


@router.post("/appraise", response_model=AppraisalOut)
async def appraise(body: AppraiseIn, ctx: Viewer) -> dict[str, Any]:
    """What one car is worth to this dealer and the most to pay for it: from
    its own sales of the same make and model, with what a person typed winning."""
    async with _session(ctx) as conn:
        settings = await pricing.settings_for(conn, ctx.tenant_id)
        currency = await _tenant_currency(conn, ctx.tenant_id)
        worth = await sourcing.worth(conn, ctx.tenant_id, currency, body.make, body.model)
    bid = sourcing.bid_from(
        worth,
        currency=currency,
        settings=settings,
        expected_price_minor=body.expected_price_minor,
        on_top_minor=body.on_top_minor,
        repairs_minor=body.repairs_minor,
    )
    return {
        "make": body.make.strip(),
        "model": body.model.strip(),
        "model_year": body.model_year,
        "currency": currency,
        "worth": _worth(worth, currency),
        "bid": _bid(bid, currency, settings),
    }


@router.post("/inspect", response_model=InspectionOut)
async def inspect(
    ctx: Viewer,
    files: Annotated[list[UploadFile], File()],
    make: Annotated[str | None, Form(max_length=60)] = None,
    model: Annotated[str | None, Form(max_length=80)] = None,
    model_year: Annotated[int | None, Form(ge=1950, le=2100)] = None,
    mileage_km: Annotated[int | None, Form(ge=0)] = None,
) -> dict[str, Any]:
    """A trade-in's photographs read into the repairs it needs, priced from the
    dealer's rates or history — L3's reader, for a car not yet in stock.
    Stores nothing: the person keeps the findings that are real."""
    photos = await photos_of(files)
    hint = describe(make, model, model_year, mileage_km) + " It is offered as a trade-in."
    return await read_photos(ctx, photos, hint, keep=False)
