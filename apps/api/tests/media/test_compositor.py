"""The compositor.

Two kinds of test here, for two kinds of regression.

The structural ones run everywhere and catch what actually breaks a poster: a
headline that overflows its box, a template that ignores `dir="rtl"`, a slot
nobody filled, a caption that closes a div. They are cheap and they are the net.

The golden comparison catches what structure cannot — the logo moved forty
pixels, the scrim went the wrong way. It is bound to the machine that generated
it, because text layout depends on which fonts are installed, and comparing a
Windows render against a Linux one measures the font stack rather than the
template. It self-skips elsewhere and says so; see `npm run creative:goldens`.
"""

from __future__ import annotations

import base64
import io
import json
import platform
import statistics
from pathlib import Path

import pytest
import pytest_asyncio
from PIL import Image

from dealerai.media import compositor
from dealerai.media.compositor import Brand, RatioNotSupported, TemplateNotFound

#: One event loop for the whole module, so one Chromium for the whole module.
#: Without it pytest-asyncio gives each test its own loop, the cached browser
#: belongs to a dead one, and every render after the first fails.
renders = pytest.mark.asyncio(loop_scope="module")

GOLDENS = Path(__file__).parent / "goldens"
#: Compared downsampled: at this width a one-pixel antialiasing difference is
#: gone and a shifted logo is not.
GOLDEN_WIDTH = 220
GOLDEN_TOLERANCE = 0.02
CHANNEL_TOLERANCE = 12

SLOTS = {
    "headline": "Nissan Patrol Platinum",
    "subhead": "2023 · 18,000 km · one owner",
    "price": "AED 310,000",
    "was_price": "AED 335,000",
    "cta": "DM to book a viewing",
    "badge": "This month",
    "eyebrow": "Interior",
    "index": "2/5",
    "body": "A used import costs less up front, and the paperwork is done before you collect.",
    "disclaimer": "Prices exclude registration and insurance.",
    "spec_1_label": "Engine",
    "spec_1_value": "5.6L V8",
    "spec_2_label": "Power",
    "spec_2_value": "400 hp",
    "spec_3_label": "Mileage",
    "spec_3_value": "18,000 km",
    "spec_4_label": "Year",
    "spec_4_value": "2023",
    "left_label": "Patrol",
    "right_label": "Land Cruiser",
    "left_value": "400 hp",
    "right_value": "409 hp",
}

ARABIC = {
    **SLOTS,
    "headline": "نيسان باترول بلاتينيوم",
    "subhead": "٢٠٢٣ · ١٨٬٠٠٠ كم · مالك واحد",
    "cta": "راسلنا لحجز معاينة",
    "badge": "هذا الشهر",
    "eyebrow": "المقصورة",
    "body": "السيارة المستوردة المستعملة أقل تكلفة، وأوراق التسجيل تُنجز قبل الاستلام.",
    "disclaimer": "الأسعار لا تشمل التسجيل والتأمين.",
    "spec_1_label": "المحرك",
    "spec_2_label": "القوة",
    "spec_3_label": "الممشى",
    "spec_4_label": "السنة",
}

EVERY = [
    (key, ratio) for key in compositor.keys() for ratio in compositor.manifest(key).aspect_ratios
]


def photo() -> str:
    """A stand-in photograph as a data URI. A real one would make the test
    depend on the network, and an empty slot would not exercise the scrim."""
    img = Image.new("RGB", (600, 600), (34, 38, 44))
    for y in range(200, 460):
        for x in range(60, 540, 1):
            img.putpixel((x, y), (150, 160, 175))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=70)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


@pytest.fixture(scope="module")
def picture() -> str:
    return photo()


def filled(picture: str, arabic: bool = False) -> dict[str, str]:
    base = ARABIC if arabic else SLOTS
    return {**base, "photo_url": picture, "left_photo_url": picture, "right_photo_url": picture}


@pytest_asyncio.fixture(autouse=True, scope="module", loop_scope="module")
async def _shutdown():  # type: ignore[no-untyped-def]
    yield
    await compositor.close_browser()


# --------------------------------------------------------------------------
# building the document — no browser
# --------------------------------------------------------------------------


def test_every_template_declares_a_manifest() -> None:
    assert len(compositor.keys()) == 8
    for key in compositor.keys():
        spec = compositor.manifest(key)
        assert spec.key == key, "a manifest whose key does not match its folder"
        assert spec.aspect_ratios
        assert spec.slots


def test_every_slot_the_html_uses_is_declared() -> None:
    """A slot the compositor is never asked for renders empty, and the poster
    ships with a blank where the price should be."""
    for key in compositor.keys():
        html = (compositor.TEMPLATES / key / "index.html").read_text(encoding="utf-8")
        used = set(compositor._SLOT.findall(html)) - {"dir", "lang"}
        declared = set(compositor.manifest(key).slots)
        assert used <= declared, f"{key} uses undeclared slots: {sorted(used - declared)}"


def test_an_unfilled_slot_renders_as_nothing_not_as_its_placeholder() -> None:
    html = compositor.build_html("hero", {"headline": "Just this"})
    assert "{{price}}" not in html
    assert "Just this" in html


def test_a_caption_cannot_inject_markup() -> None:
    """A headline is model output shaped by a customer's message. This is the
    boundary between untrusted text and a document we screenshot and publish."""
    html = compositor.build_html("hero", {"headline": "</div><script>alert(1)</script>"})
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_arabic_sets_the_document_direction() -> None:
    html = compositor.build_html("hero", {"headline": "مرحبا"}, locale="ar")
    assert 'dir="rtl"' in html
    assert 'lang="ar"' in html


def test_english_stays_ltr() -> None:
    assert 'dir="ltr"' in compositor.build_html("hero", {}, locale="en-AE")


def test_stylesheets_are_inlined_not_linked() -> None:
    """`set_content` has no base URL, so a relative <link> loads nothing and the
    poster renders as unstyled text on white — successfully."""
    html = compositor.build_html("hero", {})
    assert '<link rel="stylesheet"' not in html
    assert "--brand-primary" in html


def test_brand_tokens_override_the_placeholder_palette() -> None:
    brand = Brand.from_profile({"colors": {"primary": "#123456"}, "typography": {}})
    assert "--brand-primary: #123456;" in compositor.build_html("hero", {}, brand=brand)


def test_a_brand_with_nothing_set_falls_back_rather_than_rendering_black() -> None:
    assert Brand.from_profile({}).css() == ""


def test_typography_is_read_in_either_shape() -> None:
    """The profile holds `{"family": ...}` objects; a hand-written one holds
    strings. Both reach the same token."""
    objects = Brand.from_profile({"typography": {"heading": {"family": "Cairo"}}})
    strings = Brand.from_profile({"typography": {"heading": "Cairo"}})
    assert objects.tokens["--font-heading"] == strings.tokens["--font-heading"] == "Cairo"


def test_templates_use_logical_properties_only() -> None:
    """`margin-left` in a template is an Arabic poster with its price on the
    wrong side, and nobody notices until a customer does."""
    physical = (
        "margin-left",
        "margin-right",
        "padding-left",
        "padding-right",
        "border-left",
        "border-right",
        "left:",
        "right:",
        "text-align: left",
        "text-align: right",
    )
    import re

    for path in list(compositor.TEMPLATES.rglob("*.css")) + list(
        compositor.TEMPLATES.rglob("*.html")
    ):
        # Comments stripped first: the rule is about the CSS, and the comment
        # that explains the rule necessarily names what it forbids.
        text = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
        found = [p for p in physical if p in text]
        assert not found, f"{path.name} uses physical directions: {found}"


def test_an_unknown_template_is_a_404() -> None:
    with pytest.raises(TemplateNotFound):
        compositor.manifest("no_such_template")


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------


@pytest.mark.parametrize(("key", "ratio"), EVERY, ids=[f"{k}-{r}" for k, r in EVERY])
@renders
async def test_every_template_renders_at_every_declared_ratio(
    key: str, ratio: str, picture: str
) -> None:
    rendered = await compositor.render(key, filled(picture), ratios=[ratio])
    assert len(rendered) == 1
    image = Image.open(io.BytesIO(rendered[0].png))
    assert (image.width, image.height) == compositor.SIZES[ratio]


@pytest.mark.parametrize("key", compositor.keys())
@renders
async def test_every_template_renders_in_arabic(key: str, picture: str) -> None:
    ratio = compositor.manifest(key).aspect_ratios[0]
    rendered = await compositor.render(
        key, filled(picture, arabic=True), ratios=[ratio], locale="ar"
    )
    assert len(rendered[0].png) > 5000, "an Arabic render produced a near-empty image"


@renders
async def test_a_ratio_the_template_does_not_support_is_refused(picture: str) -> None:
    """story_teaser is 9:16 only. Rendering it square would crop the headline
    out and succeed."""
    with pytest.raises(RatioNotSupported, match="9:16"):
        await compositor.render("story_teaser", filled(picture), ratios=["1:1"])


@renders
async def test_nothing_important_overflows_the_frame(picture: str) -> None:
    """A headline that grows past its box pushes the price off the canvas, and
    a render nobody looks at is a render that ships."""
    long_slots = {
        **filled(picture),
        "headline": "Nissan Patrol Platinum Titanium Edition With A Very Long Name Indeed",
        "subhead": "Every option, every package, and a paragraph nobody asked for " * 3,
    }
    browser = await compositor.get_browser()
    page = await browser.new_page(viewport={"width": 1080, "height": 1350})
    try:
        await page.set_content(compositor.build_html("hero", long_slots), wait_until="load")
        overflow = await page.evaluate(
            "() => Array.from(document.querySelectorAll('.headline, .price, .cta, .sub'))"
            ".filter(el => { const r = el.getBoundingClientRect();"
            " return r.bottom > window.innerHeight + 1 || r.top < -1; }).map(el => el.className)"
        )
    finally:
        await page.close()
    assert overflow == [], f"pushed outside the frame: {overflow}"


@renders
async def test_the_arabic_headline_is_laid_out_right_to_left(picture: str) -> None:
    """The one property `dir="rtl"` is supposed to buy, asserted rather than
    assumed."""
    browser = await compositor.get_browser()
    page = await browser.new_page(viewport={"width": 1080, "height": 1080})
    try:
        await page.set_content(
            compositor.build_html(
                "hero", {**filled(picture, arabic=True), "headline": "باترول"}, locale="ar"
            ),
            wait_until="load",
        )
        direction = await page.evaluate(
            "() => getComputedStyle(document.querySelector('.headline')).direction"
        )
        # The element fills the content width whichever way the text runs, so
        # measure the text itself with a Range. Asserting on the element's box
        # would pass on a left-aligned headline.
        box = await page.evaluate(
            "() => { const el = document.querySelector('.headline');"
            " const range = document.createRange(); range.selectNodeContents(el);"
            " const r = range.getBoundingClientRect();"
            " const e = el.getBoundingClientRect();"
            " return {gapStart: r.left - e.left, gapEnd: e.right - r.right}; }"
        )
    finally:
        await page.close()
    assert direction == "rtl"
    assert box["gapEnd"] < box["gapStart"], f"the Arabic headline is left-aligned: {box}"


@renders
async def test_a_spec_value_keeps_its_own_direction_inside_an_arabic_frame(
    picture: str,
) -> None:
    """ "400 hp" inside an RTL paragraph renders "hp 400" unless the run resolves
    its own direction. It is the kind of wrong that looks like a typo."""
    browser = await compositor.get_browser()
    page = await browser.new_page(viewport={"width": 1080, "height": 1080})
    try:
        await page.set_content(
            compositor.build_html("specs_card", filled(picture, arabic=True), locale="ar"),
            wait_until="load",
        )
        bidi = await page.evaluate(
            "() => getComputedStyle(document.querySelector('.specs dd')).unicodeBidi"
        )
    finally:
        await page.close()
    assert bidi == "plaintext"


@renders
async def test_render_time_is_well_inside_the_budget(picture: str) -> None:
    """The plan's bar is a p95 under 4 s, which is also the documented upgrade
    trigger for moving the compositor to its own service."""
    rendered = await compositor.render("hero", filled(picture))
    times = sorted(r.ms for r in rendered)
    p95 = times[max(0, int(len(times) * 0.95) - 1)]
    assert p95 < 4000, f"p95 render {p95}ms (times: {times})"
    assert statistics.mean(times) < 4000


# --------------------------------------------------------------------------
# goldens
# --------------------------------------------------------------------------


def _platform() -> str:
    return f"{platform.system().lower()}-{platform.machine().lower()}"


def _meta() -> dict[str, str]:
    path = GOLDENS / "meta.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def difference(a: bytes, b: bytes) -> float:
    """Fraction of pixels that differ, compared downsampled.

    Full-resolution comparison measures font hinting. At 220px wide a stray
    antialiased edge is gone and a moved logo is not — which is the difference
    the test is for.
    """
    first = Image.open(io.BytesIO(a)).convert("RGB")
    second = Image.open(io.BytesIO(b)).convert("RGB")
    if first.size != second.size:
        return 1.0
    size = (GOLDEN_WIDTH, max(1, round(GOLDEN_WIDTH * first.height / first.width)))
    first = first.resize(size, Image.Resampling.LANCZOS)
    second = second.resize(size, Image.Resampling.LANCZOS)
    a_bytes, b_bytes = first.tobytes(), second.tobytes()
    differing = sum(
        1
        for i in range(0, len(a_bytes), 3)
        if max(abs(a_bytes[i + c] - b_bytes[i + c]) for c in range(3)) > CHANNEL_TOLERANCE
    )
    return differing / (size[0] * size[1])


def _write_meta() -> None:
    (GOLDENS / "meta.json").write_text(
        json.dumps(
            {
                "platform": _platform(),
                "note": "Regenerate with `npm run creative:goldens` after a template change.",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


_MISMATCH = (
    f"goldens were generated on {_meta().get('platform', 'nothing')} and this is "
    f"{_platform()}. Text layout depends on which fonts are installed, so comparing "
    "across platforms measures the font stack rather than the template. Regenerate "
    "here with `npm run creative:goldens`."
)


@pytest.mark.parametrize("key", compositor.keys())
@renders
async def test_a_template_still_looks_like_its_golden(
    key: str, picture: str, update_goldens: bool
) -> None:
    ratio = compositor.manifest(key).aspect_ratios[0]
    rendered = await compositor.render(key, filled(picture), ratios=[ratio])
    expected = GOLDENS / f"{key}.png"

    if update_goldens:
        GOLDENS.mkdir(parents=True, exist_ok=True)
        expected.write_bytes(rendered[0].png)
        _write_meta()
        return

    if _meta().get("platform") != _platform():
        pytest.skip(_MISMATCH)
    assert expected.is_file(), f"no golden for {key}; run `npm run creative:goldens`"
    drift = difference(expected.read_bytes(), rendered[0].png)
    assert drift <= GOLDEN_TOLERANCE, f"{key} drifted {drift:.1%} from its golden"


@renders
async def test_the_golden_comparison_can_fail(picture: str, update_goldens: bool) -> None:
    """The control. A comparison that cannot fail is a comparison that passes on
    a blank page, and this file would then be worth nothing."""
    if update_goldens or _meta().get("platform") != _platform():
        pytest.skip(_MISMATCH)
    key = compositor.keys()[0]
    ratio = compositor.manifest(key).aspect_ratios[0]
    altered = await compositor.render(
        key,
        {**filled(picture), "headline": "COMPLETELY DIFFERENT WORDS ENTIRELY HERE"},
        ratios=[ratio],
    )
    drift = difference((GOLDENS / f"{key}.png").read_bytes(), altered[0].png)
    assert drift > GOLDEN_TOLERANCE, "a changed headline did not register as drift"
