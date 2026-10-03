"""Tests for account inbox polling."""
from datetime import date, timedelta
from unittest.mock import AsyncMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bpost.account.client import (
    BpostAccountApiError,
    BpostAccountReauthRequired,
)
from custom_components.bpost.account.coordinator import BpostAccountCoordinator
from custom_components.bpost.account.parcels import is_outgoing
from custom_components.bpost.const import DOMAIN, ParcelStatus

from .letters_payload import LETTERS_IMAGES

# Relative so the delivered-retention filter never ages the fixture out.
RECENT_DAY = (date.today() - timedelta(days=1)).isoformat()


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
            "actualDeliveryTime": {"day": RECENT_DAY, "time": "12:00"},
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
                "actualDeliveryTime": {"day": RECENT_DAY, "time": "12:00"},
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


def _letters_client(*letter_maps):
    client = AsyncMock()
    client.async_get_parcel_summaries.return_value = []
    client.async_get_letters.side_effect = list(letter_maps)
    return client


async def test_letters_are_public_and_the_image_link_stays_internal(hass):
    coordinator = BpostAccountCoordinator(hass, _letters_client(LETTERS_IMAGES), MockConfigEntry(domain=DOMAIN))
    await coordinator._async_update_data()
    assert [letter["id"] for letter in coordinator.letters] == ["ITEM-NEW", "ITEM-OLD"]
    assert all("image_url" not in letter for letter in coordinator.letters)
    assert coordinator.letter_image("ITEM-OLD") == ("REF-OLD", "https://images.example.test/old.jpg?sig=abc")
    assert coordinator.letter_image("GONE") is None
    window = coordinator._client.async_get_letters.await_args.args
    assert (date.fromisoformat(window[1]) - date.fromisoformat(window[0])).days == 29


async def test_letter_announced_fires_only_for_letters_new_since_last_poll(hass):
    first = {"2026-10-02": LETTERS_IMAGES["2026-10-02"]}
    coordinator = BpostAccountCoordinator(
        hass, _letters_client(first, LETTERS_IMAGES), MockConfigEntry(domain=DOMAIN)
    )
    events = []
    hass.bus.async_listen(f"{DOMAIN}_letter_announced", events.append)
    await coordinator._async_update_data()
    await hass.async_block_till_done()
    assert events == []
    await coordinator._async_update_data()
    await hass.async_block_till_done()
    assert [event.data["id"] for event in events] == ["ITEM-NEW"]
    assert events[0].data["carrier"] == "bpost"
    assert "image_url" not in events[0].data


async def test_letters_failure_keeps_parcels_and_the_previous_letters(hass, caplog):
    coordinator = BpostAccountCoordinator(
        hass,
        _letters_client(LETTERS_IMAGES, BpostAccountApiError("down")),
        MockConfigEntry(domain=DOMAIN),
    )
    await coordinator._async_update_data()
    assert await coordinator._async_update_data() is not None
    assert len(coordinator.letters) == 2
    assert "Mail Ahead" in caplog.text


async def test_a_rejected_token_starts_reauth_from_either_call(hass):
    import pytest
    from homeassistant.exceptions import ConfigEntryAuthFailed

    coordinator = BpostAccountCoordinator(
        hass, _letters_client(BpostAccountReauthRequired("expired")), MockConfigEntry(domain=DOMAIN)
    )
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()

    client = AsyncMock()
    client.async_get_parcel_summaries.side_effect = BpostAccountReauthRequired("expired")
    coordinator = BpostAccountCoordinator(hass, client, MockConfigEntry(domain=DOMAIN))
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_letter_image_fetch_goes_through_the_client(hass):
    client = _letters_client()
    client.async_get_letter_image.return_value = (b"img", "image/jpeg")
    coordinator = BpostAccountCoordinator(hass, client, MockConfigEntry(domain=DOMAIN))
    assert await coordinator.async_fetch_letter_image("https://x.test/a") == (b"img", "image/jpeg")
