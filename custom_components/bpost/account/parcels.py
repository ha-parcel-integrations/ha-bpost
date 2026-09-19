"""Conservative normalisation for My bpost account summaries."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

from ..const import ACCOUNT_TRACKING_URL, HISTORY_MAX_EVENTS, ParcelStatus
from ..measurements import dimensions_cm, weight_kg
from ..status import KNOWN_PROCESS_STEP_MAP, NEW_ISSUE_URL

_LOGGER = logging.getLogger(__name__)
_warned_statuses: set[str] = set()
# bpost reports the same vocabulary here as ``currentStatus``; the map itself
# is shared with the tracking route so the two sources cannot diverge.
STATUS_MAP = KNOWN_PROCESS_STEP_MAP


def _code(raw: dict[str, Any]) -> str | None:
    """Choose a usable code without claiming the currently unverified priority."""
    for key in ("itemCode", "senderBarcode", "itemId"):
        value = raw.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def is_outgoing(raw: dict[str, Any]) -> bool:
    """Return whether bpost identifies this account as the sender.

    ``userType`` is supplied by the current My bpost v3 model.  Keep unknown
    values incoming so a newly observed value never makes parcels disappear.
    """
    return str(raw.get("userType", "")).upper() in {"SENDER", "SHIPPER", "OUTGOING"}


def _timestamp(value: Any) -> str | None:
    """Convert My bpost's local ``{day, time}`` object to an ISO timestamp."""
    if not isinstance(value, dict) or not (value.get("day") or value.get("date")):
        return None
    try:
        return datetime.fromisoformat(f"{value.get('day') or value.get('date')}T{value.get('time') or '00:00'}").replace(tzinfo=ZoneInfo("Europe/Brussels")).isoformat()
    except ValueError:
        return None


def _history(raw: dict[str, Any]) -> list[dict]:
    """Return the newest-first API events in canonical oldest-first order."""
    events = []
    for event in raw.get("events", []):
        timestamp = _timestamp(event)
        if timestamp:
            events.append({"timestamp": timestamp, "status": None, "raw_status": event.get("key")})
    return sorted(events, key=lambda event: event["timestamp"])[-HISTORY_MAX_EVENTS:]


def _planned_window(raw: dict[str, Any]) -> tuple[str | None, str | None]:
    """Build the confirmed v3 ETA window from ``eta.day/time1/time2``."""
    eta = raw.get("eta")
    if not isinstance(eta, dict) or not eta.get("day"):
        return None, None
    return (
        _timestamp({"day": eta["day"], "time": eta.get("time1")}),
        _timestamp({"day": eta["day"], "time": eta.get("time2")}),
    )


def _account_details(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the observed account summary and optional detail object."""
    details = raw.get("viewParcelDetails")
    return [raw, details] if isinstance(details, dict) else [raw]


def _weight_kg(raw: dict[str, Any]) -> float | None:
    """Return the first weight any of the account objects reports."""
    for details in _account_details(raw):
        grams = weight_kg(details.get("weightInGrams"))
        if grams is not None:
            return grams
    return None


def _dimensions_cm(raw: dict[str, Any]) -> dict[str, float | str] | None:
    """Return the first dimensions any of the account objects reports."""
    for details in _account_details(raw):
        parsed = dimensions_cm(details.get("dimensionsInCm"))
        if parsed is not None:
            return parsed
    return None


def _current_status(raw: dict[str, Any]) -> str | None:
    """Pick bpost's explicit state, then its active step, then pending state."""
    for key in ("currentStatus", "parcelMainStatus", "status"):
        if raw.get(key):
            return str(raw[key])
    for step in raw.get("deliverySteps", []):
        if isinstance(step, dict) and step.get("status") == "active":
            return step.get("knownProcessStep") or step.get("name")
    return raw.get("parcelActiveStatus") or None


def normalize_account_parcel(raw: dict[str, Any], *, include_history: bool = False, lang: str = "en") -> dict[str, Any]:
    """Return the canonical shape, leaving unproven account semantics empty."""
    barcode = _code(raw)
    raw_status = _current_status(raw)
    status = STATUS_MAP.get(str(raw_status), ParcelStatus.UNKNOWN)
    planned_from, planned_to = _planned_window(raw)
    if status is ParcelStatus.UNKNOWN and raw_status is not None and str(raw_status) not in _warned_statuses:
        _warned_statuses.add(str(raw_status))
        _LOGGER.warning(
            "Unrecognised bpost account status — help us map it. Open an "
            "issue and paste this line: %s\n"
            "  currentStatus=%s → reported as 'unknown'",
            NEW_ISSUE_URL,
            raw_status,
        )
    return {
        "carrier": "bpost",
        "barcode": barcode,
        "sender": (raw.get("sender") or {}).get("name"),
        "receiver": (raw.get("receiver") or {}).get("name"),
        "status": status,
        "raw_status": str(raw_status) if raw_status is not None else None,
        "delivered": bool(_timestamp(raw.get("actualDeliveryTime"))) or status is ParcelStatus.DELIVERED,
        "delivered_at": _timestamp(raw.get("actualDeliveryTime")),
        "planned_from": planned_from,
        "planned_to": planned_to,
        # The canonical status itself proves that this parcel is waiting at a
        # collection point. A future fixture may add its human-readable name.
        "pickup": status is ParcelStatus.AT_PICKUP_POINT,
        "pickup_point": None,
        "weight": _weight_kg(raw),
        "dimensions": _dimensions_cm(raw),
        "url": (
            ACCOUNT_TRACKING_URL.format(lang=quote(lang, safe=""), barcode=quote(barcode, safe=""))
            if barcode
            else None
        ),
        "history": _history(raw) if include_history else None,
        "raw": raw,
    }
