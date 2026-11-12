"""Colours, measured: a brand's palette read from its pixels, and how far apart
two colours look to a person.

A model asked for a logo's hex codes answers with plausible ones — #0A2540
for "dark blue" — which can sit ΔE 10 from the blue actually printed on the
showroom sign. So the palette is counted from the image, and the model is only
asked which of the counted colours plays which part.

ΔE is CIEDE2000 (Sharma, Wu & Dalal, 2005): the difference a person sees, not
the distance between numbers. Around 2 is the smallest a trained eye notices
side by side; 5 is "the same colour" for a brand on different screens.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from typing import cast

from PIL import Image

Lab = tuple[float, float, float]
RGB = tuple[int, int, int]


def hex_to_rgb(value: str) -> RGB:
    text = value.strip().lstrip("#")
    if len(text) == 3:
        text = "".join(c * 2 for c in text)
    if len(text) != 6:
        raise ValueError(f"{value!r} is not a colour")
    return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))


def rgb_to_hex(rgb: RGB) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def rgb_to_lab(rgb: RGB) -> Lab:
    """sRGB (D65) to CIELAB."""

    def linear(channel: int) -> float:
        c = channel / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (linear(c) for c in rgb)
    x = (r * 0.4124564 + g * 0.3575761 + b * 0.1804375) / 0.95047
    y = r * 0.2126729 + g * 0.7151522 + b * 0.0721750
    z = (r * 0.0193339 + g * 0.1191920 + b * 0.9503041) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 216 / 24389 else (24389 / 27 * t + 16) / 116

    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def delta_e(first: Lab, second: Lab) -> float:
    """CIEDE2000 colour difference."""
    l1, a1, b1 = first
    l2, a2, b2 = second
    c1, c2 = math.hypot(a1, b1), math.hypot(a2, b2)
    c_bar = (c1 + c2) / 2
    g = 0.5 * (1 - math.sqrt(c_bar**7 / (c_bar**7 + 25**7)))
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360 if c1p else 0.0
    h2p = math.degrees(math.atan2(b2, a2p)) % 360 if c2p else 0.0

    dl = l2 - l1
    dc = c2p - c1p
    if c1p * c2p == 0:
        dh = 0.0
    elif abs(h2p - h1p) <= 180:
        dh = h2p - h1p
    elif h2p - h1p > 180:
        dh = h2p - h1p - 360
    else:
        dh = h2p - h1p + 360
    dH = 2 * math.sqrt(c1p * c2p) * math.sin(math.radians(dh / 2))  # noqa: N806

    l_bar = (l1 + l2) / 2
    cp_bar = (c1p + c2p) / 2
    if c1p * c2p == 0:
        hp_bar = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hp_bar = (h1p + h2p) / 2
    elif h1p + h2p < 360:
        hp_bar = (h1p + h2p + 360) / 2
    else:
        hp_bar = (h1p + h2p - 360) / 2

    t = (
        1
        - 0.17 * math.cos(math.radians(hp_bar - 30))
        + 0.24 * math.cos(math.radians(2 * hp_bar))
        + 0.32 * math.cos(math.radians(3 * hp_bar + 6))
        - 0.20 * math.cos(math.radians(4 * hp_bar - 63))
    )
    d_theta = 30 * math.exp(-(((hp_bar - 275) / 25) ** 2))
    rc = 2 * math.sqrt(cp_bar**7 / (cp_bar**7 + 25**7))
    sl = 1 + (0.015 * (l_bar - 50) ** 2) / math.sqrt(20 + (l_bar - 50) ** 2)
    sc = 1 + 0.045 * cp_bar
    sh = 1 + 0.015 * cp_bar * t
    rt = -math.sin(math.radians(2 * d_theta)) * rc
    return math.sqrt((dl / sl) ** 2 + (dc / sc) ** 2 + (dH / sh) ** 2 + rt * (dc / sc) * (dH / sh))


def distance(first_hex: str, second_hex: str) -> float:
    return delta_e(rgb_to_lab(hex_to_rgb(first_hex)), rgb_to_lab(hex_to_rgb(second_hex)))


# --------------------------------------------------------------------------
# a palette, counted
# --------------------------------------------------------------------------

#: Colours closer than this are one colour: anti-aliased edges and JPEG noise
#: around a flat fill, not a second brand colour.
SAME = 5.0
#: A colour on less of the image than this is an edge, not a colour.
MIN_SHARE = 0.01


@dataclass(frozen=True, slots=True)
class Swatch:
    hex: str
    #: Share of the counted (opaque) pixels.
    share: float


def palette(data: bytes, *, colours: int = 12, keep: int = 8) -> list[Swatch]:
    """The colours an image is made of, most used first.

    Transparent pixels are not counted — a logo on a transparent background
    is not a white logo. Quantising to a dozen and then merging what a person
    could not tell apart keeps flat brand fills exact and folds their edges
    back into them.
    """
    image = Image.open(io.BytesIO(data))
    image.thumbnail((256, 256))
    rgba = image.convert("RGBA")
    pixels: list[tuple[int, int, int, int]] = list(rgba.get_flattened_data())  # type: ignore[arg-type]
    opaque = [px[:3] for px in pixels if px[3] >= 128]
    if not opaque:
        return []
    flat = Image.new("RGB", (len(opaque), 1))
    flat.putdata(opaque)
    quantised = flat.quantize(colors=colours, method=Image.Quantize.MEDIANCUT)
    lookup = quantised.getpalette() or []
    counts = sorted(quantised.getcolors(maxcolors=colours) or [], reverse=True)

    merged: list[tuple[Lab, RGB, int]] = []
    for count, index in counts:
        at = cast(int, index) * 3  # a palette image's colours are indices
        rgb = (lookup[at], lookup[at + 1], lookup[at + 2])
        lab = rgb_to_lab(rgb)
        for i, (other_lab, other_rgb, other_count) in enumerate(merged):
            if delta_e(lab, other_lab) < SAME:
                # The bigger fill keeps its exact colour; the edge joins it.
                merged[i] = (other_lab, other_rgb, other_count + count)
                break
        else:
            merged.append((lab, rgb, count))

    total = len(opaque)
    swatches = [
        Swatch(rgb_to_hex(rgb), round(count / total, 4))
        for _lab, rgb, count in sorted(merged, key=lambda m: -m[2])
        if count / total >= MIN_SHARE
    ]
    return swatches[:keep]


def combined(images: list[bytes], *, keep: int = 10) -> list[Swatch]:
    """One palette across several images, each weighted equally — a logo is
    not outvoted by a photograph because the photograph has more pixels."""
    pooled: list[tuple[Lab, str, float]] = []
    for data in images:
        for swatch in palette(data):
            lab = rgb_to_lab(hex_to_rgb(swatch.hex))
            for i, (other_lab, other_hex, other_share) in enumerate(pooled):
                if delta_e(lab, other_lab) < SAME:
                    pooled[i] = (other_lab, other_hex, other_share + swatch.share)
                    break
            else:
                pooled.append((lab, swatch.hex, swatch.share))
    count = max(len(images), 1)
    ranked = sorted(pooled, key=lambda p: -p[2])
    return [Swatch(hex_, round(share / count, 4)) for _lab, hex_, share in ranked][:keep]
