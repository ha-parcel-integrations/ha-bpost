"""The parcel contract's checks, run over every source's normalised samples."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from custom_components.bpost.account.parcels import normalize_account_parcel
from custom_components.bpost.const import ParcelStatus
from custom_components.bpost.tracking.parcels import (
    is_pickup,
    normalize_parcel,
    planned_for_status,
    planned_window,
)

from .tracking.payloads import (
    active_item,
    delivered_item,
    delivered_kariboo_item,
    delivered_unknown_method_item,
    in_transit_item,
)

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

_BRUSSELS = ZoneInfo("Europe/Brussels")
_POINT = {"name": "Example Point", "type": "POSTAL_POINT"}


def _tracked(raw):
    return lambda: normalize_parcel(raw(), barcode="EXAMPLE1", postal_code="1000")


def _account(**raw):
    base = {
        "itemCode": "EXAMPLE1",
        "currentStatus": "OUT_FOR_DELIVERY",
        "eta": {"day": "2099-05-22", "time1": "13:00", "time2": "15:00"},
    }
    return lambda: normalize_account_parcel({**base, **raw})


SAMPLES = {
    "tracked_active": _tracked(active_item),
    "tracked_in_transit": _tracked(in_transit_item),
    "tracked_delivered": _tracked(delivered_item),
    "tracked_kariboo": _tracked(delivered_kariboo_item),
    "tracked_unseen_method": _tracked(delivered_unknown_method_item),
    "account_active": _account(),
    "account_date_only": _account(eta={"day": "2099-05-22"}),
    "account_moment": _account(eta={"day": "2099-05-22", "time1": "13:00"}),
    "account_at_pickup": _account(
        currentStatus="AVAILABLE_KARIBOO_POINT", deliveryPoint=_POINT
    ),
    "account_collected": _account(
        currentStatus="PICKED_UP_IN_KARIBOO_POINT",
        deliveryPoint=_POINT,
        actualDeliveryTime={"day": "2099-05-22", "time": "10:00"},
    ),
    "account_delivered_unseen_code": _account(
        currentStatus="SOMETHING_NEW",
        actualDeliveryTime={"day": "2099-05-22", "time": "10:00"},
    ),
    "account_returning": _account(currentStatus="BTS_OUT_FOR_DELIVERY_KARIBOO_POINT"),
    "account_bare": lambda: normalize_account_parcel({}),
}


@pytest.fixture(params=SAMPLES)
def parcel(request) -> dict:
    return SAMPLES[request.param]()


def test_keys_and_order(parcel):
    assert list(parcel) == CANONICAL_KEYS


def test_delivered_follows_status(parcel):
    assert parcel["delivered"] is (parcel["status"] is ParcelStatus.DELIVERED)


def test_delivered_at_only_when_delivered(parcel):
    if not parcel["delivered"]:
        assert parcel["delivered_at"] is None


def test_planned_window_is_ordered_and_anchored(parcel):
    if parcel["planned_to"] is not None:
        assert parcel["planned_from"] is not None
        assert datetime.fromisoformat(parcel["planned_to"]) > datetime.fromisoformat(
            parcel["planned_from"]
        )


def test_planned_is_empty_when_the_parcel_is_done_or_waiting(parcel):
    if parcel["status"] in (
        ParcelStatus.DELIVERED,
        ParcelStatus.AT_PICKUP_POINT,
        ParcelStatus.RETURNING,
    ):
        assert parcel["planned_from"] is None
        assert parcel["planned_to"] is None


def test_pickup_is_a_bool_and_the_point_needs_it(parcel):
    assert isinstance(parcel["pickup"], bool)
    if not parcel["pickup"]:
        assert parcel["pickup_point"] is None


def test_the_delivery_time_decides_the_status_even_for_an_unseen_code():
    for name in ("tracked_unseen_method", "account_delivered_unseen_code"):
        parcel = SAMPLES[name]()
        assert parcel["status"] is ParcelStatus.DELIVERED
        assert parcel["delivered"] is True
        assert parcel["delivered_at"] is not None


def test_a_collected_pickup_parcel_stays_pickup():
    parcel = SAMPLES["account_collected"]()
    assert parcel["delivered"] is True
    assert parcel["pickup"] is True
    assert parcel["pickup_point"] == "Example Point"


def test_an_account_window_keeps_both_ends():
    parcel = SAMPLES["account_active"]()
    assert parcel["planned_from"] == "2099-05-22T13:00:00+02:00"
    assert parcel["planned_to"] == "2099-05-22T15:00:00+02:00"


def test_an_account_date_covers_the_whole_local_day():
    parcel = SAMPLES["account_date_only"]()
    assert parcel["planned_from"] == "2099-05-22T00:00:00+02:00"
    assert parcel["planned_to"] == "2099-05-22T23:59:59+02:00"


def test_an_account_moment_ends_at_the_end_of_its_day():
    parcel = SAMPLES["account_moment"]()
    assert parcel["planned_to"] == "2099-05-22T23:59:59+02:00"


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (
            "2026-04-29T13:00:00+02:00",
            "2026-04-29T15:00:00+02:00",
            ("2026-04-29T13:00:00+02:00", "2026-04-29T15:00:00+02:00"),
        ),
        (
            "2026-04-29T13:00:00+02:00",
            None,
            ("2026-04-29T13:00:00+02:00", "2026-04-29T23:59:59+02:00"),
        ),
        (
            "2026-04-29T13:00:00+02:00",
            "2026-04-29T13:00:00+02:00",
            ("2026-04-29T13:00:00+02:00", "2026-04-29T23:59:59+02:00"),
        ),
        (
            "2026-04-29T13:00:00",
            None,
            ("2026-04-29T13:00:00+02:00", "2026-04-29T23:59:59+02:00"),
        ),
        (
            "2026-04-29",
            None,
            ("2026-04-29T00:00:00+02:00", "2026-04-29T23:59:59+02:00"),
        ),
        (
            date(2026, 4, 29),
            date(2026, 4, 29),
            ("2026-04-29T00:00:00+02:00", "2026-04-29T23:59:59+02:00"),
        ),
        (
            "2026-04-29",
            "2026-05-01",
            ("2026-04-29T00:00:00+02:00", "2026-05-01T23:59:59+02:00"),
        ),
        (
            "2026-04-29T15:00:00+02:00",
            "2026-04-29T13:00:00+02:00",
            ("2026-04-29T13:00:00+02:00", "2026-04-29T15:00:00+02:00"),
        ),
        (
            None,
            "2026-04-29T13:00:00+02:00",
            ("2026-04-29T13:00:00+02:00", "2026-04-29T23:59:59+02:00"),
        ),
        (
            datetime(2026, 4, 29, 13, 0),
            datetime(2026, 4, 29, 15, 0),
            ("2026-04-29T13:00:00+02:00", "2026-04-29T15:00:00+02:00"),
        ),
        (None, None, (None, None)),
        ("garbage", None, (None, None)),
        (12, 13, (None, None)),
    ],
)
def test_planned_window_shapes(start, end, expected):
    assert planned_window(start, end, zone=_BRUSSELS) == expected


@pytest.mark.parametrize(
    "status",
    [ParcelStatus.AT_PICKUP_POINT, ParcelStatus.RETURNING, ParcelStatus.DELIVERED],
)
def test_planned_for_status_empties_the_window(status):
    assert planned_for_status(status, "a", "b") == (None, None)


def test_planned_for_status_keeps_the_window_otherwise():
    for status in (
        ParcelStatus.REGISTERED,
        ParcelStatus.IN_TRANSIT,
        ParcelStatus.OUT_FOR_DELIVERY,
        ParcelStatus.PROBLEM,
        ParcelStatus.UNKNOWN,
    ):
        assert planned_for_status(status, "a", "b") == ("a", "b")


def test_is_pickup_sources():
    assert is_pickup(True, ParcelStatus.IN_TRANSIT) is True
    assert is_pickup(None, ParcelStatus.AT_PICKUP_POINT) is True
    assert is_pickup(None, ParcelStatus.DELIVERED, [None, ParcelStatus.AT_PICKUP_POINT])
    assert is_pickup(False, ParcelStatus.IN_TRANSIT, [ParcelStatus.IN_TRANSIT]) is False
    assert is_pickup(None, ParcelStatus.DELIVERED) is False


def test_a_delivery_time_does_not_turn_a_return_into_a_delivery():
    parcel = SAMPLES["account_returning"]()
    assert parcel["status"] is ParcelStatus.RETURNING
    assert parcel["delivered"] is False
    back = normalize_account_parcel(
        {
            "itemCode": "EXAMPLE1",
            "currentStatus": "BTS_OUT_FOR_DELIVERY_KARIBOO_POINT",
            "actualDeliveryTime": {"day": "2099-05-22", "time": "10:00"},
        }
    )
    assert back["status"] is ParcelStatus.RETURNING
    assert back["delivered"] is True
    assert back["delivered_at"] is not None
    assert back["planned_from"] is None
