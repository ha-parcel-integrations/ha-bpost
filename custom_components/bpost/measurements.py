"""Weight and dimension parsing shared by both sources.

bpost states its units in the field names themselves (``weightInGrams``,
``dimensionsInCm``), so these are pure unit conversions with no carrier
semantics — the one kind of parsing both routes can safely share.
"""
from __future__ import annotations

import re
from typing import Any


def to_number(value: Any) -> float | None:
    """Parse a numeric API value without accepting arbitrary text."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return None


def weight_kg(grams: Any) -> float | None:
    """Convert a ``weightInGrams`` value to the canonical kilograms."""
    value = to_number(grams)
    if value is None or value <= 0:
        return None
    return value / 1000


def dimensions_cm(value: Any) -> dict[str, float | str] | None:
    """Convert a ``dimensionsInCm`` value to the canonical dimensions shape.

    Both a structured object and a display string are accepted: the tracker
    returns ``"41.5cm x 21.5cm x 51cm"``, where the unit suffixes are noise
    because the field name already fixes the unit.
    """
    if isinstance(value, dict):
        numbers = [
            to_number(value.get(key) or value.get(f"{key}InCm"))
            for key in ("length", "width", "height")
        ]
    elif isinstance(value, str):
        numbers = [to_number(number) for number in re.findall(r"\d+(?:[.,]\d+)?", value)[:3]]
    else:
        return None
    if len(numbers) != 3 or any(number is None or number <= 0 for number in numbers):
        return None
    length, width, height = numbers
    assert length is not None and width is not None and height is not None
    return {
        "length": length,
        "width": width,
        "height": height,
        "text": f"{length:g} x {width:g} x {height:g} cm",
    }
