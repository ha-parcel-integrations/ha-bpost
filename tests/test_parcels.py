"""Tests for the pure parcel-mapping helpers.

These need no Home Assistant instance — the whole point of keeping
``parcels.py`` free of I/O is that the carrier-specific mapping can be tested
as plain functions.
"""
from datetime import datetime, timedelta, timezone

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bpost.const import (
    CAPABILITIES,
    CONF_DELIVERED_FILTER_AMOUNT,
    CONF_DELIVERED_FILTER_TYPE,
    DOMAIN,
    KNOWN_CAPABILITIES,
    ParcelStatus,
)
from custom_components.bpost.parcels import (
    apply_delivered_filter,
    build_history,
    map_parcel_status,
    normalize_parcel,
    parcel_key,
    parse_iso,
    resolve_lang,
    sort_parcels_by_ts,
    to_iso_timestamp,
)

from .payloads import (
    BARCODE,
    POSTAL_CODE,
    active_item,
    delivered_item,
    delivered_kariboo_item,
    delivered_unknown_method_item,
    event,
    in_transit_item,
    item,
)

# ---------------------------------------------------------------------------
# map_parcel_status — exact / prefix / unknown
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code,expected",
    [
        ("delivered", ParcelStatus.DELIVERED),
        ("delivered_kariboo_point", ParcelStatus.DELIVERED),
        ("out_for_delivery_byCar", ParcelStatus.OUT_FOR_DELIVERY),
    ],
)
def test_map_parcel_status_known_exact(code, expected):
    assert map_parcel_status(code) == expected


def test_map_parcel_status_missing_is_unknown():
    assert map_parcel_status(None) == ParcelStatus.UNKNOWN
    assert map_parcel_status("") == ParcelStatus.UNKNOWN


def test_map_parcel_status_prefix_match_example_from_plan(caplog):
    """An unseen method suffix prefix-matches: out_for_delivery_byBike -> out_for_delivery."""
    assert map_parcel_status("out_for_delivery_byBike") == ParcelStatus.OUT_FOR_DELIVERY
    assert "prefix match" in caplog.text


def test_map_parcel_status_prefix_match_on_delivered_family(caplog):
    assert map_parcel_status("delivered_parcel_locker") == ParcelStatus.DELIVERED
    assert "prefix match" in caplog.text


def test_map_parcel_status_exact_hit_does_not_warn(caplog):
    """A band-ordering trap: an exact key must never fall through to the
    prefix path or its distinct log line, even though a shorter prefix of it
    (``delivered``) is also a valid key."""
    assert map_parcel_status("delivered_kariboo_point") == ParcelStatus.DELIVERED
    assert caplog.text == ""


def test_map_parcel_status_completely_unmapped_is_unknown_and_warns(caplog):
    assert map_parcel_status("on_the_way_to_a_bpost_facility") == ParcelStatus.UNKNOWN
    assert "issues/new" in caplog.text
    assert "prefix match" not in caplog.text


def test_unmapped_status_warns_only_once(caplog):
    assert map_parcel_status("teleported") == ParcelStatus.UNKNOWN
    assert map_parcel_status("teleported") == ParcelStatus.UNKNOWN
    assert caplog.text.count("teleported") == 1


# ---------------------------------------------------------------------------
# resolve_lang
# ---------------------------------------------------------------------------


def test_resolve_lang_limits_to_nl_fr_en():
    assert resolve_lang("nl") == "nl"
    assert resolve_lang("fr-BE") == "fr"
    assert resolve_lang("de") == "en"
    assert resolve_lang(None) == "en"


# ---------------------------------------------------------------------------
# timestamp helpers
# ---------------------------------------------------------------------------


def test_parse_iso_handles_z_naive_and_garbage():
    assert parse_iso("2026-04-29T13:12:42Z").tzinfo is not None
    assert parse_iso("2026-04-29T13:12:42").tzinfo == timezone.utc
    assert parse_iso("not-a-date") is None
    assert parse_iso(None) is None


def test_to_iso_timestamp_converts_epoch_milliseconds():
    assert to_iso_timestamp(1784203767167) == "2026-07-16T12:09:27.167000+00:00"
    assert to_iso_timestamp("2026-04-29T13:12:42Z") == "2026-04-29T13:12:42Z"
    assert to_iso_timestamp(None) is None
    assert to_iso_timestamp(10**20) is None


# ---------------------------------------------------------------------------
# build_history — newest-first input, oldest->newest output
# ---------------------------------------------------------------------------


def test_build_history_orders_oldest_to_newest_from_newest_first_input():
    """bpost's own events array is newest-first."""
    events = [
        event("2026-04-29", "08:46", "Wordt geleverd", "Sera livré", "Being delivered"),
        event("2026-04-28", None, "Onderweg", "En route", "In transit"),
        event("2026-04-27", None, "Aangemeld", "Annoncé", "Registered"),
    ]
    history = build_history(events, lang="en")
    assert [entry["raw_status"] for entry in history] == [
        "Registered",
        "In transit",
        "Being delivered",
    ]
    # No event-level status code exists on this route (§4).
    assert all(entry["status"] is None for entry in history)


def test_build_history_localises_by_language():
    events = [event("2026-04-27", None, "Aangemeld", "Annoncé", "Registered")]
    assert build_history(events, lang="nl")[0]["raw_status"] == "Aangemeld"
    assert build_history(events, lang="fr")[0]["raw_status"] == "Annoncé"
    assert build_history(events, lang="en")[0]["raw_status"] == "Registered"


def test_build_history_falls_back_to_english_for_missing_language():
    events = [{"date": "2026-04-27", "time": None, "key": {"EN": {"description": "Registered"}}}]
    assert build_history(events, lang="nl")[0]["raw_status"] == "Registered"


def test_build_history_caps_to_max_events():
    events = [
        event(f"2026-04-{day:02d}", None, "x", "x", "x") for day in range(1, 26)
    ]
    assert len(build_history(events, max_events=20)) == 20


def test_build_history_handles_missing_and_malformed():
    assert build_history(None) == []
    assert build_history([{"date": None}]) == []
    assert build_history(["not-a-dict"]) == []


def test_build_history_keeps_relative_order_on_timestamp_tie():
    """When timestamps tie, the newest-first input order is the tiebreak (§4)."""
    events = [
        event("2026-04-27", "10:00", "second", "second", "second"),
        event("2026-04-27", "10:00", "first", "first", "first"),
    ]
    history = build_history(events, lang="en")
    assert [entry["raw_status"] for entry in history] == ["second", "first"]


# ---------------------------------------------------------------------------
# normalize_parcel — the canonical contract
# ---------------------------------------------------------------------------

CANONICAL_KEYS = [
    "carrier",
    "barcode",
    "sender",
    "receiver",
    "status",
    "raw_status",
    "delivered",
    "delivered_at",
    "planned_from",
    "planned_to",
    "pickup",
    "pickup_point",
    "url",
    "weight",
    "dimensions",
    "history",
    "raw",
]


def _normalize(raw, **kwargs):
    return normalize_parcel(raw, barcode=BARCODE, postal_code=POSTAL_CODE, **kwargs)


def test_normalize_publishes_exactly_the_canonical_keys():
    assert list(_normalize(delivered_item())) == CANONICAL_KEYS


def test_capabilities_are_known_values():
    assert CAPABILITIES <= KNOWN_CAPABILITIES


def test_capabilities_match_what_normalize_parcel_actually_returns():
    delivered = _normalize(delivered_item())
    active = _normalize(active_item())
    with_history = _normalize(delivered_item(), include_history=True)

    if "weight" in CAPABILITIES:
        assert delivered["weight"] is not None
    if "dimensions" in CAPABILITIES:
        assert delivered["dimensions"] is not None
    if "delivery_window" in CAPABILITIES:
        assert active["planned_from"] is not None or active["planned_to"] is not None
    if "pickup_point" in CAPABILITIES:
        assert delivered["pickup_point"] is not None
    if "url" in CAPABILITIES:
        assert delivered["url"] is not None
    if "history" in CAPABILITIES:
        assert with_history["history"] is not None


def test_normalize_delivered_mailbox_drop():
    parcel = _normalize(delivered_item())
    assert parcel["carrier"] == "bpost"
    assert parcel["barcode"] == BARCODE
    assert parcel["status"] == ParcelStatus.DELIVERED
    assert parcel["raw_status"] == "delivered"
    assert parcel["delivered"] is True
    assert parcel["delivered_at"] == "2026-04-29T00:00:00+00:00"
    assert parcel["planned_from"] is None
    assert parcel["planned_to"] is None
    assert parcel["url"] == (
        "https://track.bpost.cloud/btr/web/#/search"
        f"?lang=en&itemCode={BARCODE}&postalCode={POSTAL_CODE}"
    )
    assert parcel["weight"] is None
    assert parcel["dimensions"] is None
    assert parcel["pickup"] is False
    assert parcel["pickup_point"] is None


@pytest.mark.parametrize("factory", [delivered_kariboo_item, delivered_unknown_method_item])
def test_delivered_is_never_derived_from_the_status_name(factory):
    """The core rule: actualDeliveryInformation decides, not activeStep.name.

    Both a known pickup-point delivery code and a wholly unseen delivered
    method must report delivered.
    """
    parcel = _normalize(factory())
    assert parcel["delivered"] is True
    assert parcel["delivered_at"] == "2026-04-29T00:00:00+00:00"


def test_normalize_history_is_opt_in():
    parcel = _normalize(delivered_item(), include_history=True)
    assert len(parcel["history"]) == 3
    assert parcel["history"][-1]["raw_status"] == "Will be delivered today"


def test_normalize_history_off_by_default():
    assert _normalize(delivered_item())["history"] is None


def test_normalize_active_parcel_has_window():
    parcel = _normalize(active_item())
    assert parcel["status"] == ParcelStatus.OUT_FOR_DELIVERY
    assert parcel["delivered"] is False
    assert parcel["planned_from"] == "2026-04-29T13:00:00Z"
    assert parcel["planned_to"] == "2026-04-29T15:00:00Z"


def test_normalize_delivered_parcel_drops_eta_even_if_present():
    raw = delivered_item()
    raw["expectedDeliveryTimeRange"] = {
        "time1": "2026-04-29T13:00:00Z",
        "time2": "2026-04-29T15:00:00Z",
    }
    parcel = _normalize(raw)
    assert parcel["planned_from"] is None
    assert parcel["planned_to"] is None


def test_normalize_eta_missing_time1_time2_stays_none_and_warns(caplog):
    raw = item(eta={"date": "2026-04-29", "startTime": "13:00", "endTime": "15:00"})
    parcel = _normalize(raw)
    assert parcel["planned_from"] is None
    assert parcel["planned_to"] is None
    assert "issues/new" in caplog.text


def test_normalize_eta_as_plain_string_does_not_raise(caplog):
    raw = item(eta="13:00-15:00")
    parcel = _normalize(raw)
    assert parcel["planned_from"] is None
    assert parcel["planned_to"] is None
    assert "issues/new" in caplog.text


def test_normalize_eta_absent_never_warns(caplog):
    raw = item(eta=None)
    _normalize(raw)
    assert caplog.text == ""


def test_normalize_eta_first_sighting_warns_only_once(caplog):
    raw = item(eta={"time1": "2026-04-29T13:00:00Z", "time2": None})
    _normalize(raw)
    _normalize(raw)
    assert caplog.text.count("expectedDeliveryTimeRange") == 1


def test_normalize_delivery_point_first_sighting_warns_once(caplog):
    raw = item(delivery_point={"name": "Some Point", "address": "Somewhere 1"})
    _normalize(raw)
    _normalize(raw)
    assert caplog.text.count("deliveryPoint") == 1
    # never populate pickup_point from it — its contents are unconfirmed
    parcel = _normalize(raw)
    assert parcel["pickup_point"] is None
    assert parcel["pickup"] is False


def test_normalize_delivery_point_absent_never_warns(caplog):
    _normalize(item(delivery_point=None))
    assert caplog.text == ""


def test_normalize_sender_falls_back_to_sender_name():
    raw = item(sender=None)
    raw["sender"] = {"name": "Fallback Sender"}
    parcel = _normalize(raw)
    assert parcel["sender"] == "Fallback Sender"


def test_normalize_sender_none_when_neither_field_present():
    raw = item(sender=None)
    assert _normalize(raw)["sender"] is None


def test_normalize_echoed_barcode_mismatch_uses_tracked_value_and_warns(caplog):
    raw = item(echoed_item_code="SOMETHING_ELSE")
    parcel = _normalize(raw)
    assert parcel["barcode"] == BARCODE
    assert "SOMETHING_ELSE" in caplog.text
    assert "issues/new" in caplog.text


def test_normalize_echoed_barcode_match_never_warns(caplog):
    raw = item(echoed_item_code=BARCODE)
    _normalize(raw)
    assert caplog.text == ""


def test_normalize_pending_placeholder_for_not_found():
    """A tracked-but-not-found pair still yields a full parcel dict (§2)."""
    parcel = _normalize({})
    assert parcel["barcode"] == BARCODE
    assert parcel["status"] == ParcelStatus.UNKNOWN
    assert parcel["delivered"] is False
    assert parcel["raw_status"] is None
    assert parcel["history"] is None


def test_normalize_keeps_raw_verbatim():
    """raw is the untouched payload, like every other suite carrier — not an
    allowlist. A field this repo doesn't know about yet must still survive,
    so a future bpost change (or the still-open ETA/deliveryPoint shape) is
    visible in diagnostics rather than silently dropped."""
    raw = active_item()
    raw["someUnexpectedInternalField"] = "must survive"
    result = _normalize(raw)["raw"]
    assert result is raw
    assert result["someUnexpectedInternalField"] == "must survive"
    assert result["shipmentType"] == "PARCEL"
    assert result["productCategory"] == "NATIONAL"
    assert result["deliveryPreferenceType"] == "STANDARD"
    assert result["activeStep"]["label"]["main"]["EN"] == "Will be delivered today"
    assert result["senderCommercialName"] == "Example Shop"
    assert result["events"] == raw["events"]


def test_normalize_raw_includes_dearrayed_round_status_when_present():
    raw = active_item()
    raw["itemOnRoundStatus"] = {"nrOfStopsUntilTarget": 3}
    result = _normalize(raw)["raw"]
    assert result["itemOnRoundStatus"] == {"nrOfStopsUntilTarget": 3}


def test_normalize_raw_omits_round_status_key_when_absent():
    result = _normalize(active_item())["raw"]
    assert "itemOnRoundStatus" not in result


def test_normalize_url_requires_both_barcode_and_postal_code():
    from custom_components.bpost.parcels import tracking_url

    assert tracking_url(None, "1000", "en") is None
    assert tracking_url("ABC", None, "en") is None
    assert tracking_url("ABC", "1000", "nl").startswith(
        "https://track.bpost.cloud/btr/web/#/search?lang=nl"
    )


def test_in_transit_is_completely_unmapped():
    parcel = _normalize(in_transit_item())
    assert parcel["status"] == ParcelStatus.UNKNOWN


def test_parcel_key_is_the_barcode_alone():
    assert parcel_key("ABC123") == "ABC123"


# ---------------------------------------------------------------------------
# sort_parcels_by_ts
# ---------------------------------------------------------------------------


def test_sort_parcels_ascending_puts_unparseable_last():
    parcels = [
        {"barcode": "a", "planned_from": "2026-05-02T10:00:00Z"},
        {"barcode": "b", "planned_from": None},
        {"barcode": "c", "planned_from": "2026-05-01T10:00:00Z"},
    ]
    ordered = [p["barcode"] for p in sort_parcels_by_ts(parcels, "planned_from")]
    assert ordered == ["c", "a", "b"]


def test_sort_parcels_descending_still_puts_unparseable_last():
    parcels = [
        {"barcode": "a", "delivered_at": "2026-05-02T10:00:00Z"},
        {"barcode": "b", "delivered_at": "nonsense"},
        {"barcode": "c", "delivered_at": "2026-05-01T10:00:00Z"},
    ]
    ordered = [
        p["barcode"]
        for p in sort_parcels_by_ts(parcels, "delivered_at", descending=True)
    ]
    assert ordered == ["a", "c", "b"]


# ---------------------------------------------------------------------------
# apply_delivered_filter
# ---------------------------------------------------------------------------


def _entry(filter_type: str, amount: int) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        options={
            CONF_DELIVERED_FILTER_TYPE: filter_type,
            CONF_DELIVERED_FILTER_AMOUNT: amount,
        },
        unique_id=DOMAIN,
    )


def _delivered_pair() -> list[dict]:
    now = datetime.now(timezone.utc)
    return [
        {"barcode": "RECENT", "delivered_at": (now - timedelta(days=1)).isoformat()},
        {"barcode": "OLD", "delivered_at": (now - timedelta(days=30)).isoformat()},
    ]


def test_delivered_filter_by_days():
    kept = apply_delivered_filter(_delivered_pair(), _entry("days", 7))
    assert [p["barcode"] for p in kept] == ["RECENT"]


def test_delivered_filter_by_count():
    parcels = _delivered_pair()
    assert apply_delivered_filter(parcels, _entry("parcels", 1)) == parcels[:1]


def test_delivered_filter_keeps_unparseable_timestamp():
    parcels = [{"barcode": "WEIRD", "delivered_at": "nonsense"}]
    assert apply_delivered_filter(parcels, _entry("days", 7)) == parcels
