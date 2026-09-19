"""Tests for bpost sensor property logic."""
from datetime import datetime, timezone
from unittest.mock import MagicMock

from custom_components.bpost.const import ParcelStatus
from custom_components.bpost.sensor import (
    BpostAwaitingPickupSensor,
    BpostDeliveredParcelsSensor,
    BpostIncomingParcelsSensor,
    BpostLastUpdateSensor,
    BpostNextDeliverySensor,
    BpostOutgoingDeliveredParcelsSensor,
    BpostOutgoingParcelsSensor,
    BpostParcelSensor,
)


def _entry(entry_id: str = "e1") -> MagicMock:
    entry = MagicMock()
    entry.entry_id = entry_id
    return entry


def _coordinator(data: list[dict], delivered: list[dict] | None = None) -> MagicMock:
    coordinator = MagicMock()
    coordinator.data = data
    coordinator.delivered = delivered if delivered is not None else []
    return coordinator


def _parcel(
    barcode: str,
    status: ParcelStatus = ParcelStatus.IN_TRANSIT,
    pickup: bool = False,
    planned_from: str | None = None,
) -> dict:
    return {
        "carrier": "bpost",
        "barcode": barcode,
        "sender": "Sender",
        "receiver": None,
        "status": status,
        "pickup": pickup,
        "planned_from": planned_from,
    }


def test_incoming_counts_and_lists():
    coordinator = _coordinator([_parcel("A"), _parcel("B")])
    sensor = BpostIncomingParcelsSensor(coordinator, _entry(), lambda _: None, set())
    assert sensor.native_value == 2
    assert len(sensor.extra_state_attributes["parcels"]) == 2


def test_parcel_sensor_status_and_attributes():
    parcel = _parcel("A", status=ParcelStatus.OUT_FOR_DELIVERY)
    sensor = BpostParcelSensor(_coordinator([parcel]), _entry(), "A")
    assert sensor.native_value == ParcelStatus.OUT_FOR_DELIVERY
    assert sensor.extra_state_attributes["barcode"] == "A"


def test_parcel_sensor_missing_barcode():
    sensor = BpostParcelSensor(_coordinator([_parcel("A")]), _entry(), "OTHER")
    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {}


def test_next_delivery_picks_earliest():
    coordinator = _coordinator([
        _parcel("A", planned_from="2026-05-02T10:00:00Z"),
        _parcel("B", planned_from="2026-05-01T10:00:00Z"),
    ])
    sensor = BpostNextDeliverySensor(coordinator, _entry())
    assert sensor.native_value == datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc)
    assert sensor.extra_state_attributes["barcode"] == "B"


def test_next_delivery_none_without_moments():
    sensor = BpostNextDeliverySensor(_coordinator([_parcel("A")]), _entry())
    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {}


def test_next_delivery_skips_unparseable_moment():
    coordinator = _coordinator([
        _parcel("A", planned_from="not-a-date"),
        _parcel("B", planned_from="2026-05-01T10:00:00Z"),
    ])
    sensor = BpostNextDeliverySensor(coordinator, _entry())
    assert sensor.extra_state_attributes["barcode"] == "B"


def test_delivered_sensor():
    coordinator = _coordinator([], delivered=[_parcel("D", status=ParcelStatus.DELIVERED)])
    sensor = BpostDeliveredParcelsSensor(coordinator, _entry())
    assert sensor.native_value == 1
    assert sensor.extra_state_attributes["parcels"][0]["barcode"] == "D"


def test_awaiting_pickup_counts_only_parcels_ready_for_collection():
    ready = _parcel("READY", status=ParcelStatus.AT_PICKUP_POINT, pickup=True)
    en_route = _parcel("ROUTE", status=ParcelStatus.IN_TRANSIT, pickup=True)
    home_delivery = _parcel("HOME", status=ParcelStatus.AT_PICKUP_POINT)
    sensor = BpostAwaitingPickupSensor(
        _coordinator([ready, en_route, home_delivery]), _entry()
    )

    assert sensor.native_value == 1
    assert sensor.extra_state_attributes["parcels"] == [ready]


def test_account_bucket_sensors_use_the_standard_coordinator_data():
    active = _parcel("OUT")
    delivered = _parcel("DONE", status=ParcelStatus.DELIVERED)
    coordinator = _coordinator(
        {
            "incoming_active": [],
            "incoming_delivered": [],
            "outgoing_active": [active],
            "outgoing_delivered": [delivered],
        }
    )
    outgoing = BpostOutgoingParcelsSensor(coordinator, _entry())
    outgoing_delivered = BpostOutgoingDeliveredParcelsSensor(coordinator, _entry())

    assert outgoing.native_value == 1
    assert outgoing.extra_state_attributes["parcels"] == [active]
    assert outgoing_delivered.native_value == 1
    assert outgoing_delivered.extra_state_attributes["parcels"] == [delivered]


def test_last_update_sensor():
    coordinator = _coordinator([])
    moment = datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc)
    coordinator.last_success_time = moment
    sensor = BpostLastUpdateSensor(coordinator, _entry())
    assert sensor.native_value == moment
