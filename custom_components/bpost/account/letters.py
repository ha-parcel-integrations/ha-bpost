"""Mail Ahead letter parsing for the account source.

Letters have no tracking status or canonical parcel shape, so they live apart
from ``parcels.py``. No I/O and no Home Assistant objects.
"""
from __future__ import annotations

import logging
from typing import Any

from ..status import NEW_ISSUE_URL

_LOGGER = logging.getLogger(__name__)

_first_sighting_warned = False
_unexpected_entry_warned = False


def _warn_first_sighting(day: str, raw: dict[str, Any]) -> None:
    """Log once, ever, the shape of the first letter seen.

    No populated letter has been observed yet, so the first one settles the
    field set and the date formats. Keys and dates only — the sender and the
    image link stay out of the log.
    """
    global _first_sighting_warned
    if _first_sighting_warned:
        return
    _first_sighting_warned = True
    _LOGGER.warning(
        "bpost reported a Mail Ahead letter for the first time (keys %s, "
        "group date %r, plannedDistributionDate %r, sender keys %s) — please "
        "open an issue (%s) and paste this line so the letter shape can be "
        "confirmed.",
        sorted(raw),
        day,
        raw.get("plannedDistributionDate"),
        sorted(raw["sender"]) if isinstance(raw.get("sender"), dict) else None,
        NEW_ISSUE_URL,
    )


def _warn_unexpected_entry(day: str, raw: Any) -> None:
    """Log once when a letter group or entry is not the expected shape."""
    global _unexpected_entry_warned
    if _unexpected_entry_warned:
        return
    _unexpected_entry_warned = True
    _LOGGER.warning(
        "bpost returned a Mail Ahead entry this integration cannot read "
        "(group date %r, type %s, keys %s) — please open an issue (%s) and "
        "paste this line.",
        day,
        type(raw).__name__,
        sorted(raw) if isinstance(raw, dict) else None,
        NEW_ISSUE_URL,
    )


def extract_letters(images: Any) -> list[dict[str, Any]]:
    """Flatten bpost's date-keyed letter map, newest first, deduplicated on id."""
    if not isinstance(images, dict):
        return []
    letters: dict[str, dict[str, Any]] = {}
    for day, entries in images.items():
        if not isinstance(entries, list):
            _warn_unexpected_entry(day, entries)
            continue
        for raw in entries:
            if not isinstance(raw, dict) or not raw.get("itemId"):
                _warn_unexpected_entry(day, raw)
                continue
            _warn_first_sighting(day, raw)
            sender = raw.get("sender")
            letters[str(raw["itemId"])] = {
                "id": str(raw["itemId"]),
                "date": day,
                "planned_delivery": raw.get("plannedDistributionDate"),
                "sender": sender.get("name") if isinstance(sender, dict) else None,
                "raw": raw,
            }
    return sorted(
        letters.values(),
        key=lambda letter: (str(letter["planned_delivery"] or letter["date"]), letter["id"]),
        reverse=True,
    )
