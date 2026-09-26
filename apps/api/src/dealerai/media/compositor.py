"""Renders creative from HTML templates with a headless browser.

Deterministic composition, never a generative image model. A model asked to
draw a car draws a car that does not exist, with a badge the dealer does not
sell and a number plate from nowhere. This takes the dealer's own photograph
and puts their own type on it.

What the browser buys us: pixel-exact brand compliance from CSS custom
properties, free RTL from `dir="rtl"` and logical properties, templates a
designer can edit without touching Python, and no model cost per render.

    ponytail: HTML/CSS + Playwright over Pillow/Skia composition. Ceiling is
    ~1-2s and ~150MB RSS per render, plus a browser in the worker image.
    Upgrade trigger: more than 10k renders/day or render p95 above 4s — then
    this moves to its own service with a warm browser pool. Not before.
"""

from __future__ import annotations

import asyncio
import contextlib
import html
import json
import re
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import structlog
from playwright.async_api import Browser, async_playwright

from ..core.errors import AppError

log = structlog.get_logger()

TEMPLATES = Path(__file__).parent.parent / "templates"

Ratio = Literal["1:1", "4:5", "9:16", "16:9"]

#: Rendered at the long edge platforms actually serve, so the compositor is the
#: last place the image is resized. 1080 is Instagram's, and every other surface
#: downscales from it cleanly.
SIZES: dict[str, tuple[int, int]] = {
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
}

#: A render that has not finished by now is a hung font fetch or a photo that
#: will never arrive, and the caller would rather have the error.
TIMEOUT_MS = 15_000

_SLOT = re.compile(r"\{\{(\w+)\}\}")


class TemplateNotFound(AppError):
    status = 404
    slug = "template-not-found"
    title = "No such creative template"


class RatioNotSupported(AppError):
    status = 422
    slug = "ratio-not-supported"
    title = "This template does not support that aspect ratio"


@dataclass(frozen=True, slots=True)
class Manifest:
    key: str
    name: str
    kind: str
    aspect_ratios: tuple[str, ...]
    slots: dict[str, str]


@dataclass(frozen=True, slots=True)
class Rendered:
    ratio: str
    width: int
    height: int
    png: bytes
    ms: int


@dataclass(frozen=True, slots=True)
class Brand:
    """The tokens a template consumes. Anything absent falls back to the
    placeholder in _tokens.css rather than rendering a black rectangle."""

    tokens: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_profile(cls, profile: dict[str, Any]) -> Brand:
        colors = profile.get("colors") or {}
        typography = profile.get("typography") or {}
        tokens = {
            "--brand-primary": colors.get("primary"),
            "--brand-secondary": colors.get("secondary"),
            "--brand-accent": colors.get("accent"),
            "--brand-bg": colors.get("bg"),
            "--brand-text": colors.get("text"),
            "--font-heading": _family(typography.get("heading")),
            "--font-body": _family(typography.get("body")),
            "--font-arabic": _family(typography.get("arabic")),
        }
        return cls({k: v for k, v in tokens.items() if v})

    def css(self) -> str:
        if not self.tokens:
            return ""
        # Sorted so the same brand produces byte-identical HTML, which is what
        # makes a golden comparison mean anything.
        body = " ".join(f"{k}: {v};" for k, v in sorted(self.tokens.items()))
        return f":root{{{body}}}"


def _family(entry: Any) -> str | None:
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict) and isinstance(entry.get("family"), str):
        return str(entry["family"])
    return None


@lru_cache
def manifest(key: str) -> Manifest:
    path = TEMPLATES / key / "manifest.json"
    if not path.is_file():
        raise TemplateNotFound(f"no template named {key!r}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return Manifest(
        key=data["key"],
        name=data["name"],
        kind=data["kind"],
        aspect_ratios=tuple(data["aspect_ratios"]),
        slots=data["slots"],
    )


def keys() -> list[str]:
    return sorted(p.name for p in TEMPLATES.iterdir() if (p / "manifest.json").is_file())


@lru_cache
def _stylesheets() -> str:
    tokens = (TEMPLATES / "_tokens.css").read_text(encoding="utf-8")
    base = (TEMPLATES / "_base.css").read_text(encoding="utf-8")
    return f"<style>\n{tokens}\n{base}\n</style>"


def build_html(
    key: str, slots: dict[str, str], *, brand: Brand | None = None, locale: str = "en"
) -> str:
    """Fill a template. Every value is escaped.

    A caption is model output shaped by a customer's message, and a headline
    containing `</div><script>` would otherwise break the layout at best. The
    escaping is not a nicety — it is the boundary between untrusted text and a
    document we then screenshot and publish.
    """
    template = (TEMPLATES / key / "index.html").read_text(encoding="utf-8")
    if not (TEMPLATES / key / "manifest.json").is_file():
        raise TemplateNotFound(f"no template named {key!r}")

    rtl = locale.split("-")[0] in ("ar", "he", "fa", "ur")
    values = {
        **{name: "" for name in manifest(key).slots},
        **{k: str(v) for k, v in slots.items()},
        "dir": "rtl" if rtl else "ltr",
        "lang": locale.split("-")[0],
    }

    def fill(match: re.Match[str]) -> str:
        return html.escape(values.get(match.group(1), ""), quote=True)

    filled = _SLOT.sub(fill, template)
    # Stylesheets are inlined rather than linked: set_content has no base URL,
    # so a relative <link> silently loads nothing and the poster renders as
    # unstyled text on white. Inlining makes that impossible.
    filled = re.sub(r'\s*<link rel="stylesheet"[^>]*>', "", filled)
    injected = _stylesheets() + (f"<style>{brand.css()}</style>" if brand else "")
    return filled.replace("</head>", f"{injected}\n</head>", 1)


#: Browsers, keyed by the event loop that launched them.
#:
#: Playwright's connection is bound to its loop, so a browser reused across two
#: loops fails with "NoneType has no attribute send" — the same trap the model
#: client hit in ai/gateway.py, for the same reason. One loop lives for the life
#: of the worker, so production has exactly one browser.
_browsers: dict[int, tuple[Any, Browser]] = {}
#: Keyed by loop for the same reason the browsers are. A module-level Lock binds
#: to the first loop that awaits it and raises "bound to a different event loop"
#: on the second — which reads like a threading bug and is not one.
_locks: dict[int, asyncio.Lock] = {}


def _loop_key() -> int:
    try:
        return id(asyncio.get_running_loop())
    except RuntimeError:  # pragma: no cover - render is always called from a loop
        return 0


async def get_browser() -> Browser:
    """One browser per loop, many pages.

    Launching Chromium costs about a second; doing it per render would be most
    of the render budget spent on process startup.
    """
    key = _loop_key()
    async with _locks.setdefault(key, asyncio.Lock()):
        existing = _browsers.get(key)
        if existing is not None and existing[1].is_connected():
            return existing[1]
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(
            args=["--force-color-profile=srgb", "--font-render-hinting=none"]
        )
        _browsers[key] = (playwright, browser)
        return browser


async def close_browser() -> None:
    """Close this loop's browser and stop its driver.

    Stopping the driver matters: leaving it to the garbage collector is what
    produces "I/O operation on closed pipe" long after the code that opened it
    has finished.
    """
    key = _loop_key()
    _locks.pop(key, None)
    entry = _browsers.pop(key, None)
    if entry is None:
        return
    playwright, browser = entry
    with contextlib.suppress(Exception):
        await browser.close()
    with contextlib.suppress(Exception):
        await playwright.stop()


async def render(
    key: str,
    slots: dict[str, str],
    *,
    ratios: list[str] | None = None,
    brand: Brand | None = None,
    locale: str = "en",
) -> list[Rendered]:
    """Render one template at each requested ratio."""
    spec = manifest(key)
    wanted = ratios or list(spec.aspect_ratios)
    unsupported = [r for r in wanted if r not in spec.aspect_ratios]
    if unsupported:
        raise RatioNotSupported(
            f"{key} supports {', '.join(spec.aspect_ratios)}, not {', '.join(unsupported)}"
        )

    document = build_html(key, slots, brand=brand, locale=locale)
    browser = await get_browser()
    out: list[Rendered] = []
    for ratio in wanted:
        width, height = SIZES[ratio]
        started = time.perf_counter()
        page = await browser.new_page(viewport={"width": width, "height": height})
        try:
            page.set_default_timeout(TIMEOUT_MS)
            await page.set_content(document, wait_until="load")
            # A photograph that has not decoded yet screenshots as empty space,
            # and the render succeeds while producing a poster with no car in it.
            await page.evaluate(
                "() => document.fonts.ready.then(() => "
                "Promise.all(Array.from(document.images).map(i => "
                "i.complete ? null : i.decode().catch(() => null))))"
            )
            png = await page.screenshot(type="png")
        finally:
            await page.close()
        out.append(
            Rendered(
                ratio=ratio,
                width=width,
                height=height,
                png=png,
                ms=int((time.perf_counter() - started) * 1000),
            )
        )

    log.info(
        "creative_rendered",
        template=key,
        locale=locale,
        ratios=wanted,
        ms=[r.ms for r in out],
    )
    return out
