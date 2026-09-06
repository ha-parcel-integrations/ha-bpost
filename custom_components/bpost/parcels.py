"""Canonical parcel shape, status mapping and list helpers.

Everything in this module is a **pure function** — no I/O, no Home Assistant
objects beyond the config entry's options (logging aside, which is the
established one-shot-warning pattern used throughout the suite).

Every field lookup below was read off a third-party client's source, not off
this repo's own wire. The
one-shot WARNINGs in this module are the safety net a pre-1.0 release ships
with: an unrecognised status, a first-seen ETA window or ``deliveryPoint``
object all log once instead of silently mis-mapping.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry

from .const import (
    CONF_DELIVERED_FILTER_AMOUNT,
    CONF_DELIVERED_FILTER_TYPE,
    DEFAULT_DELIVERED_FILTER_AMOUNT,
    DEFAULT_DELIVERED_FILTER_TYPE,
    HISTORY_MAX_EVENTS,
    TRACKING_URL,
    ParcelStatus,
)

_LOGGER = logging.getLogger(__name__)

# Where users report a status/shape we do not handle yet. The ``?template=``
# parameter matters: without it the link opens a blank form, missing the
# version and the log line we need.
NEW_ISSUE_URL = (
    "https://github.com/ha-parcel-integrations/ha-bpost/issues/new"
    "?template=unrecognised_status.yml"
)

# Three known ``activeStep.name`` codes out of an unknown set — neither
# source client claims a complete vocabulary, and the codes are
# not documented anywhere. Written against the open ``ParcelStatus`` enum:
# nothing maps to registered/in_transit/at_pickup_point/returning/problem
# because no evidence exists for a bpost code reaching them — leave those
# unmapped rather than guessing a code name.
STATUS_MAP: dict[str, ParcelStatus] = {
    "delivered": ParcelStatus.DELIVERED,
    "delivered_kariboo_point": ParcelStatus.DELIVERED,
    "out_for_delivery_byCar": ParcelStatus.OUT_FOR_DELIVERY,
}


def _build_prefix_table() -> dict[str, ParcelStatus]:
    """Expand every known code into all of its leading ``_``-segment prefixes.

    ``out_for_delivery_byCar`` contributes ``out_for_delivery`` (and
    ``out_for_delivery_byCar`` itself, already an exact key); ``delivered``
    and ``delivered_kariboo_point`` both contribute ``delivered``. An unseen
    code is then matched by trying its own decreasing-length prefixes against
    this table (see :func:`_prefix_match`) — which is exactly how
    ``out_for_delivery_byBike`` resolves to ``out_for_delivery``.
    """
    table: dict[str, ParcelStatus] = {}
    for key, status in STATUS_MAP.items():
        segments = key.split("_")
        for length in range(1, len(segments) + 1):
            prefix = "_".join(segments[:length])
            table.setdefault(prefix, status)
    return table


_PREFIX_TABLE = _build_prefix_table()


def _prefix_match(code: str) -> ParcelStatus | None:
    """Longest-prefix match of ``code``'s own segments against known codes."""
    segments = code.split("_")
    for length in range(len(segments), 0, -1):
        candidate = "_".join(segments[:length])
        status = _PREFIX_TABLE.get(candidate)
        if status is not None:
            return status
    return None


# One-shot warning bookkeeping, mirrored across the suite: log once per HA
# session, not on every poll.
_unmapped_statuses_logged: set[str] = set()
_echoed_barcode_mismatches_logged: set[tuple[str, str]] = set()
_eta_first_sighting_warned = False
_delivery_point_first_sighting_warned = False


def _warn_unmapped_status(code: str, *, prefix_status: ParcelStatus | None) -> None:
    """Log an unrecognised ``activeStep.name`` once, distinguishing the path taken.

    A prefix hit is a mitigation, not evidence — it still warns, with its own wording, so a field report says which path resolved
    it.
    """
    if code in _unmapped_statuses_logged:
        return
    _unmapped_statuses_logged.add(code)
    if prefix_status is not None:
        _LOGGER.warning(
            "Unrecognised bpost activeStep code — matched by prefix only. "
            "Help us confirm it: open an issue and paste this line: %s\n"
            "  activeStep.name=%s → reported as %r (prefix match)",
            NEW_ISSUE_URL,
            code,
            prefix_status.value,
        )
    else:
        _LOGGER.warning(
            "Unrecognised bpost activeStep code — help us map it. Open an "
            "issue and paste this line: %s\n"
            "  activeStep.name=%s → reported as 'unknown'",
            NEW_ISSUE_URL,
            code,
        )


def map_parcel_status(code: str | None) -> ParcelStatus:
    """Map an ``activeStep.name`` code to a canonical :class:`ParcelStatus`.

    Exact lookup first, then a defensive longest-prefix match, then ``unknown`` — every path but the exact hit logs a one-shot
    warning so the map can grow from field reports.
    """
    if not code:
        return ParcelStatus.UNKNOWN
    mapped = STATUS_MAP.get(code)
    if mapped is not None:
        return mapped
    prefix_status = _prefix_match(code)
    _warn_unmapped_status(code, prefix_status=prefix_status)
    return prefix_status if prefix_status is not None else ParcelStatus.UNKNOWN


def _warn_echoed_barcode_mismatch(supplied: str, echoed: str) -> None:
    """Log once per (supplied, echoed) pair that bpost echoed a different itemCode."""
    key = (supplied, echoed)
    if key in _echoed_barcode_mismatches_logged:
        return
    _echoed_barcode_mismatches_logged.add(key)
    _LOGGER.warning(
        "bpost echoed a different itemCode (%r) than the barcode being "
        "tracked (%r) — using the tracked value. Please open an issue (%s) "
        "and paste this line if this persists.",
        echoed,
        supplied,
        NEW_ISSUE_URL,
    )


def _warn_eta_first_sighting(raw_eta: Any) -> None:
    """Log once, ever, the first time ``expectedDeliveryTimeRange`` is populated.

    Inverse of the usual warning (mirrors Ceska Posta's ``_warn_eta_populated``):
    this field has never been observed non-null, so the first real sighting is
    the datum that settles which ETA shape bpost actually sends, whatever
    shape it turns out to be.
    """
    global _eta_first_sighting_warned
    if _eta_first_sighting_warned:
        return
    _eta_first_sighting_warned = True
    _LOGGER.warning(
        "bpost's expectedDeliveryTimeRange was populated for the first time "
        "(%r) — please open an issue (%s) and paste this line so the ETA "
        "window shape can be confirmed.",
        raw_eta,
        NEW_ISSUE_URL,
    )


def _warn_delivery_point_first_sighting(delivery_point: Any) -> None:
    """Log once, ever, the first time ``deliveryPoint`` is populated.

    Neither source client this route was reconstructed from ever reads
    ``deliveryPoint``, so its contents are unknown — only the key set is
    logged, never the values, until a fixture proves what is safe to show.
    """
    global _delivery_point_first_sighting_warned
    if _delivery_point_first_sighting_warned:
        return
    _delivery_point_first_sighting_warned = True
    keys = sorted(delivery_point.keys()) if isinstance(delivery_point, dict) else None
    _LOGGER.warning(
        "bpost's deliveryPoint was populated for the first time (keys=%r) — "
        "please open an issue (%s) and paste this line so its contents can "
        "be mapped.",
        keys,
        NEW_ISSUE_URL,
    )


def resolve_lang(language: str | None) -> str:
    """Return the bpost label language for ``language`` (``hass.config.language``).

    Limited to ``nl``/``fr``/``en``, defaulting to ``en`` — the source
    integration's behaviour, and the only three languages
    ``activeStep.label.main`` (and each history event's ``key``) is known to
    carry.
    """
    lang = (language or "en").split("-")[0].lower()
    return lang if lang in ("nl", "fr", "en") else "en"


def parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO 8601 string to an aware datetime, or ``None`` on failure.

    Naive values are treated as UTC so a list always sorts without crashing on
    a mixed set.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def to_iso_timestamp(value: Any) -> str | None:
    """Return an ISO 8601 string for a bpost timestamp field.

    Numbers are treated as **epoch milliseconds**; strings pass through
    untouched (their consumers are guarded by :func:`parse_iso`). Neither
    source client stamps a number for ``expectedDeliveryTimeRange.time1``/
    ``.time2``, but the shape is unconfirmed, so this stays permissive rather than assuming a string.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    return str(value)


def _event_timestamp(date: str | None, time: str | None) -> str | None:
    """Combine a bpost history event's separate ``date`` + ``time`` into one ISO string.

    Neither source client documents whether every event carries a ``time``; a
    bare date is treated as midnight rather than dropped.
    """
    if not date:
        return None
    return f"{date}T{time}:00" if time else f"{date}T00:00:00"


def _localized_text(node: Any, lang: str) -> str | None:
    """Return ``node[lang.upper()]["description"]``, falling back to English."""
    if not isinstance(node, dict):
        return None
    lang_node = node.get(lang.upper()) or node.get("EN")
    if isinstance(lang_node, dict):
        return lang_node.get("description")
    return None


def build_history(
    events: list | None, *, max_events: int = HISTORY_MAX_EVENTS, lang: str = "en"
) -> list[dict]:
    """Build the canonical ``history`` list from bpost's ``events`` array.

    bpost returns these **newest first** (the source client reads
    ``events[0]`` as "latest"); the canonical contract is oldest → newest,
    capped at ``max_events``. Sorting explicitly on the parsed timestamp
    (rather than just reversing) means a tie keeps the newest-first input
    order as its tiebreak — Python's sort is stable, so
    that falls out of sorting ascending without extra code. Each event has no
    status code of its own on this route, so ``status`` is always ``None``
    (never ``unknown``) and ``raw_status`` is the localised description text.
    """
    parseable: list[tuple[datetime, dict]] = []
    for event in events or []:
        if not isinstance(event, dict):
            continue
        timestamp = _event_timestamp(event.get("date"), event.get("time"))
        if not timestamp:
            continue
        entry = {
            "timestamp": timestamp,
            "status": None,
            "raw_status": _localized_text(event.get("key"), lang),
        }
        parsed = parse_iso(timestamp)
        if parsed is not None:
            parseable.append((parsed, entry))
    parseable.sort(key=lambda item: item[0])
    return [entry for _, entry in parseable][-max_events:]


def tracking_url(barcode: str | None, postal_code: str | None, lang: str) -> str | None:
    """Construct the bpost track-and-trace deep link for a parcel."""
    if not barcode or not postal_code:
        return None
    return TRACKING_URL.format(lang=lang, barcode=barcode, postal_code=postal_code)


def _delivered_at(raw: dict) -> str | None:
    """Return the delivery date, date-only, from ``actualDeliveryInformation``.

    ``actualDeliveryTime.day`` (``%Y-%m-%d``) is the only component either
    source client uses — no time-of-day has been observed, so none is
    synthesised.
    """
    actual_time = (raw.get("actualDeliveryInformation") or {}).get("actualDeliveryTime")
    if not isinstance(actual_time, dict):
        return None
    day = actual_time.get("day")
    if not day:
        return None
    try:
        parsed = datetime.strptime(str(day), "%Y-%m-%d")
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc).isoformat()


def _planned_window(raw: dict) -> tuple[str | None, str | None]:
    """Return ``(planned_from, planned_to)`` from ``expectedDeliveryTimeRange``.

    Only the ``time1``/``time2`` shape is implemented —
    the alternative ``{date, startTime, endTime}`` shape, or a plain string,
    both leave the window ``None`` without raising. Any non-null value fires
    the one-shot first-sighting warning regardless of shape, since even a
    recognised ``time1``/``time2`` object has never been seen on this repo's
    own wire.
    """
    eta = raw.get("expectedDeliveryTimeRange")
    if eta:
        _warn_eta_first_sighting(eta)
    if not isinstance(eta, dict):
        return None, None
    time1, time2 = eta.get("time1"), eta.get("time2")
    return (
        to_iso_timestamp(time1) if time1 else None,
        to_iso_timestamp(time2) if time2 else None,
    )


def normalize_parcel(
    raw: dict,
    *,
    barcode: str,
    postal_code: str,
    include_history: bool = False,
    lang: str = "en",
) -> dict:
    """Return a carrier-agnostic parcel dict for one bpost ``track/items`` result.

    ``barcode`` is the tracked parcel's own value; ``postal_code`` is the
    hub's default (``entry.options[CONF_POSTAL_CODE]``). Neither is read from
    ``raw`` — the deep link needs both regardless of whether the parcel was
    found, and the tracked barcode is treated as the source of truth over any
    echoed ``itemCode``. ``raw`` may be an empty dict for a
    tracked-but-not-yet-found pair — every lookup below already tolerates that.
    The canonical ``raw`` key is this same dict passed through verbatim, like
    every other suite carrier — see ``diagnostics.TO_REDACT`` for what gets
    blanked before it can reach a public issue.
    """
    active_step = raw.get("activeStep") or {}
    status_code = active_step.get("name")
    status = map_parcel_status(status_code)

    # Never derive `delivered` from the status name: the same delivery can
    # report `delivered` (mailbox drop) or `delivered_kariboo_point` (pickup
    # point) depending on method, and an unmapped method-suffixed code must
    # still report delivered. actualDeliveryInformation is the only reliable
    # signal — this rule must survive any refactor.
    delivered = bool(
        (raw.get("actualDeliveryInformation") or {}).get("actualDeliveryTime")
    )
    delivered_at = _delivered_at(raw) if delivered else None

    echoed = raw.get("itemCode")
    if echoed and echoed != barcode:
        _warn_echoed_barcode_mismatch(barcode, echoed)

    delivery_point = raw.get("deliveryPoint")
    if delivery_point:
        _warn_delivery_point_first_sighting(delivery_point)

    planned_from, planned_to = (None, None) if delivered else _planned_window(raw)

    sender = raw.get("senderCommercialName") or (raw.get("sender") or {}).get("name")

    return {
        "carrier": "bpost",
        "barcode": barcode,
        "sender": sender or None,
        "receiver": None,
        "status": status,
        "raw_status": status_code,
        "delivered": delivered,
        "delivered_at": delivered_at,
        "planned_from": planned_from,
        "planned_to": planned_to,
        "pickup": status is ParcelStatus.AT_PICKUP_POINT,
        "pickup_point": None,
        "url": tracking_url(barcode, postal_code, lang),
        "weight": None,
        "dimensions": None,
        "history": (
            build_history(raw.get("events"), lang=lang) if include_history else None
        ),
        "raw": raw,
    }


def parcel_key(barcode: str) -> str:
    """Return the tracked-parcel key — the barcode alone.

    Scoped within one hub/postcode (config_flow.py's hub-per-postcode model,
    mirroring GLS): the same barcode tracked in two different hubs is not a
    duplicate, since each hub is a separate device with its own postal code.
    """
    return barcode


def sort_parcels_by_ts(
    parcels: list[dict], key_field: str, *, descending: bool = False
) -> list[dict]:
    """Return normalised parcels sorted by the ISO timestamp at ``key_field``.

    The suite's sort contract: incoming/outgoing ascending on ``planned_from``,
    delivered descending on ``delivered_at``. Parcels whose value is missing or
    unparseable always sort to the end, regardless of ``descending``.
    """
    with_ts: list[tuple[datetime, dict]] = []
    without_ts: list[dict] = []
    for parcel in parcels:
        parsed = parse_iso(parcel.get(key_field))
        if parsed is None:
            without_ts.append(parcel)
        else:
            with_ts.append((parsed, parcel))
    with_ts.sort(key=lambda item: item[0], reverse=descending)
    return [parcel for _, parcel in with_ts] + without_ts


def apply_delivered_filter(parcels: list[dict], entry: ConfigEntry) -> list[dict]:
    """Trim the delivered list per the entry's retention option.

    ``parcels`` must already be sorted newest-first. ``days`` keeps deliveries
    from the last N days (an unparseable ``delivered_at`` is kept rather than
    silently dropped); the ``parcels`` type keeps the N most recent. Parcels
    stay *tracked* either way — this only controls what the delivered sensor
    shows.
    """
    options = entry.options
    filter_type = options.get(
        CONF_DELIVERED_FILTER_TYPE, DEFAULT_DELIVERED_FILTER_TYPE
    )
    amount = int(
        options.get(CONF_DELIVERED_FILTER_AMOUNT, DEFAULT_DELIVERED_FILTER_AMOUNT)
    )
    if filter_type == "days":
        cutoff = datetime.now(timezone.utc) - timedelta(days=amount)
        return [
            parcel
            for parcel in parcels
            if (parsed := parse_iso(parcel.get("delivered_at"))) is None
            or parsed >= cutoff
        ]
    return parcels[:amount]
