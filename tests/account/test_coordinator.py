"""Tests for account inbox polling."""
from unittest.mock import AsyncMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bpost.account.client import BpostAccountApiError
from custom_components.bpost.account.coordinator import BpostAccountCoordinator
from custom_components.bpost.account.parcels import is_outgoing
from custom_components.bpost.const import DOMAIN, ParcelStatus


async def test_empty_account_inbox_stays_available_and_keeps_polling(hass):
    client = AsyncMock()
    client.async_get_parcel_summaries.return_value = []
    entry = MockConfigEntry(domain=DOMAIN)
    coordinator = BpostAccountCoordinator(hass, client, entry)
    assert await coordinator._async_update_data() == {
        "incoming_active": [],
        "incoming_delivered": [],
        "outgoing_active": [],
        "outgoing_delivered": [],
    }
    assert coordinator.update_interval is not None


async def test_account_api_error_becomes_update_failed(hass):
    client = AsyncMock()
    client.async_get_parcel_summaries.side_effect = BpostAccountApiError("nope")
    coordinator = BpostAccountCoordinator(hass, client, MockConfigEntry(domain=DOMAIN))
    import pytest
    from homeassistant.helpers.update_coordinator import UpdateFailed
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


def test_sender_user_type_is_classified_as_outgoing():
    assert is_outgoing({"userType": "SENDER"})
    assert not is_outgoing({"userType": "RECEIVER"})


async def test_account_coordinator_returns_the_standard_four_buckets(hass):
    client = AsyncMock()
    client.async_get_parcel_summaries.return_value = [
        {"itemCode": "IN", "userType": "RECEIVER", "currentStatus": "PROCESSING"},
        {"itemCode": "OUT", "userType": "SENDER", "currentStatus": "PROCESSING"},
        {
            "itemCode": "DONE",
            "userType": "SENDER",
            "currentStatus": "DELIVERED_TO_SENDER",
            "actualDeliveryTime": {"day": "2026-09-19", "time": "12:00"},
        },
    ]
    coordinator = BpostAccountCoordinator(hass, client, MockConfigEntry(domain=DOMAIN))

    data = await coordinator._async_update_data()

    assert [parcel["barcode"] for parcel in data["incoming_active"]] == ["IN"]
    assert data["incoming_delivered"] == []
    assert [parcel["barcode"] for parcel in data["outgoing_active"]] == ["OUT"]
    assert [parcel["barcode"] for parcel in data["outgoing_delivered"]] == ["DONE"]


async def test_account_outgoing_status_change_fires_suite_event(hass):
    client = AsyncMock()
    client.async_get_parcel_summaries.side_effect = [
        [{"itemCode": "OUT", "userType": "SENDER", "currentStatus": "PROCESSING"}],
        [{"itemCode": "OUT", "userType": "SENDER", "currentStatus": "OUT_FOR_DELIVERY_HOME"}],
    ]
    coordinator = BpostAccountCoordinator(hass, client, MockConfigEntry(domain=DOMAIN))
    events = []
    hass.bus.async_listen(f"{DOMAIN}_outgoing_parcel_status_changed", events.append)

    await coordinator._async_update_data()
    await coordinator._async_update_data()
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data["old_status"] is ParcelStatus.IN_TRANSIT
    assert events[0].data["new_status"] is ParcelStatus.OUT_FOR_DELIVERY


async def test_account_outgoing_delivery_fires_dedicated_event_only(hass):
    client = AsyncMock()
    client.async_get_parcel_summaries.side_effect = [
        [{"itemCode": "OUT", "userType": "SENDER", "currentStatus": "OUT_FOR_DELIVERY_HOME"}],
        [{"itemCode": "OUT", "userType": "SENDER", "currentStatus": "DELIVERED_TO_SENDER"}],
    ]
    coordinator = BpostAccountCoordinator(hass, client, MockConfigEntry(domain=DOMAIN))
    delivered, changed = [], []
    hass.bus.async_listen(f"{DOMAIN}_outgoing_parcel_delivered", delivered.append)
    hass.bus.async_listen(f"{DOMAIN}_outgoing_parcel_status_changed", changed.append)

    await coordinator._async_update_data()
    await coordinator._async_update_data()
    await hass.async_block_till_done()

    assert len(delivered) == 1
    assert changed == []


async def test_account_first_refresh_fires_no_incoming_events(hass):
    client = AsyncMock()
    client.async_get_parcel_summaries.return_value = [
        {"itemCode": "IN", "userType": "RECEIVER", "currentStatus": "PROCESSING"},
    ]
    coordinator = BpostAccountCoordinator(hass, client, MockConfigEntry(domain=DOMAIN))
    events = []
    hass.bus.async_listen(f"{DOMAIN}_parcel_registered", events.append)
    hass.bus.async_listen(f"{DOMAIN}_parcel_status_changed", events.append)

    await coordinator._async_update_data()
    await hass.async_block_till_done()

    assert events == []


async def test_account_new_incoming_parcel_fires_registered(hass):
    client = AsyncMock()
    client.async_get_parcel_summaries.side_effect = [
        [{"itemCode": "IN", "userType": "RECEIVER", "currentStatus": "PROCESSING"}],
        [
            {"itemCode": "IN", "userType": "RECEIVER", "currentStatus": "PROCESSING"},
            {"itemCode": "NEW", "userType": "RECEIVER", "currentStatus": "PROCESSING_HOME"},
        ],
    ]
    coordinator = BpostAccountCoordinator(hass, client, MockConfigEntry(domain=DOMAIN))
    events = []
    hass.bus.async_listen(f"{DOMAIN}_parcel_registered", events.append)

    await coordinator._async_update_data()
    await coordinator._async_update_data()
    await hass.async_block_till_done()

    assert [event.data["barcode"] for event in events] == ["NEW"]


async def test_account_incoming_status_change_fires_the_incoming_event(hass):
    client = AsyncMock()
    client.async_get_parcel_summaries.side_effect = [
        [{"itemCode": "IN", "userType": "RECEIVER", "currentStatus": "PROCESSING"}],
        [{"itemCode": "IN", "userType": "RECEIVER", "currentStatus": "OUT_FOR_DELIVERY_HOME"}],
    ]
    coordinator = BpostAccountCoordinator(hass, client, MockConfigEntry(domain=DOMAIN))
    incoming, outgoing = [], []
    hass.bus.async_listen(f"{DOMAIN}_parcel_status_changed", incoming.append)
    hass.bus.async_listen(f"{DOMAIN}_outgoing_parcel_status_changed", outgoing.append)

    await coordinator._async_update_data()
    await coordinator._async_update_data()
    await hass.async_block_till_done()

    assert len(incoming) == 1
    assert incoming[0].data["old_status"] is ParcelStatus.IN_TRANSIT
    assert incoming[0].data["new_status"] is ParcelStatus.OUT_FOR_DELIVERY
    assert outgoing == []


async def test_account_incoming_delivery_fires_dedicated_event_only(hass):
    client = AsyncMock()
    client.async_get_parcel_summaries.side_effect = [
        [{"itemCode": "IN", "userType": "RECEIVER", "currentStatus": "OUT_FOR_DELIVERY_HOME"}],
        [
            {
                "itemCode": "IN",
                "userType": "RECEIVER",
                "currentStatus": "DELIVERED_AT_HOME",
                "actualDeliveryTime": {"day": "2026-09-19", "time": "12:00"},
            }
        ],
    ]
    coordinator = BpostAccountCoordinator(hass, client, MockConfigEntry(domain=DOMAIN))
    delivered, changed = [], []
    hass.bus.async_listen(f"{DOMAIN}_parcel_delivered", delivered.append)
    hass.bus.async_listen(f"{DOMAIN}_parcel_status_changed", changed.append)

    await coordinator._async_update_data()
    await coordinator._async_update_data()
    await hass.async_block_till_done()

    assert len(delivered) == 1
    assert delivered[0].data["barcode"] == "IN"
    assert changed == []


async def test_account_incoming_eta_shift_fires_delivery_time_changed(hass):
    client = AsyncMock()
    client.async_get_parcel_summaries.side_effect = [
        [
            {
                "itemCode": "IN",
                "userType": "RECEIVER",
                "currentStatus": "PROCESSING",
                "eta": {"day": "2026-09-19", "time1": "10:00", "time2": "12:00"},
            }
        ],
        [
            {
                "itemCode": "IN",
                "userType": "RECEIVER",
                "currentStatus": "PROCESSING",
                "eta": {"day": "2026-09-20", "time1": "14:00", "time2": "16:00"},
            }
        ],
    ]
    coordinator = BpostAccountCoordinator(hass, client, MockConfigEntry(domain=DOMAIN))
    events = []
    hass.bus.async_listen(f"{DOMAIN}_parcel_delivery_time_changed", events.append)

    await coordinator._async_update_data()
    await coordinator._async_update_data()
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data["old_planned_from"] != events[0].data["new_planned_from"]


async def test_account_incoming_eta_dropping_to_null_stays_silent(hass):
    client = AsyncMock()
    client.async_get_parcel_summaries.side_effect = [
        [
            {
                "itemCode": "IN",
                "userType": "RECEIVER",
                "currentStatus": "PROCESSING",
                "eta": {"day": "2026-09-19", "time1": "10:00", "time2": "12:00"},
            }
        ],
        [{"itemCode": "IN", "userType": "RECEIVER", "currentStatus": "PROCESSING"}],
    ]
    coordinator = BpostAccountCoordinator(hass, client, MockConfigEntry(domain=DOMAIN))
    events = []
    hass.bus.async_listen(f"{DOMAIN}_parcel_delivery_time_changed", events.append)

    await coordinator._async_update_data()
    await coordinator._async_update_data()
    await hass.async_block_till_done()

    assert events == []
