"""Tests for the bpost coordinator: fetching, caching and events.

The parcel mapping itself is covered by ``test_parcels.py``.
"""
from unittest.mock import AsyncMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bpost.api import BpostApiError
from custom_components.bpost.const import (
    CONF_BARCODE,
    CONF_DELIVERED_FILTER_AMOUNT,
    CONF_DELIVERED_FILTER_TYPE,
    CONF_PARCELS,
    CONF_POSTAL_CODE,
    DOMAIN,
    ParcelStatus,
)
from custom_components.bpost.coordinator import BpostCoordinator

from .payloads import BARCODE, POSTAL_CODE, active_item, delivered_item, in_transit_item

OTHER_BARCODE = "888888888888"


def _parcels(*barcodes: str) -> list[dict]:
    return [{CONF_BARCODE: b} for b in barcodes]


def _entry_with(parcels: list[dict], postal_code: str = POSTAL_CODE) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        # Keep-most-recent-100 so the delivered-retention filter never trims
        # the (old, fixed-date) sample parcels these tests assert on.
        options={
            CONF_PARCELS: parcels,
            CONF_POSTAL_CODE: postal_code,
            CONF_DELIVERED_FILTER_TYPE: "parcels",
            CONF_DELIVERED_FILTER_AMOUNT: 100,
        },
        unique_id=postal_code,
    )


# ---------------------------------------------------------------------------
# fetching
# ---------------------------------------------------------------------------


async def test_update_merges_multiple_parcels(hass):
    entry = _entry_with(_parcels(BARCODE, OTHER_BARCODE))
    entry.add_to_hass(hass)
    client = AsyncMock()
    client.async_get_parcel.side_effect = lambda barcode, postal_code: (
        active_item(barcode) if barcode == BARCODE else delivered_item(barcode)
    )
    coordinator = BpostCoordinator(hass, client, entry)

    data = await coordinator._async_update_data()

    assert len(data) == 1  # one active
    assert data[0]["barcode"] == BARCODE
    assert len(coordinator.delivered) == 1
    assert coordinator.last_success_time is not None


async def test_update_uses_the_hub_postal_code_for_every_fetch(hass):
    entry = _entry_with(_parcels(BARCODE, OTHER_BARCODE))
    entry.add_to_hass(hass)
    client = AsyncMock()
    client.async_get_parcel.return_value = delivered_item()
    coordinator = BpostCoordinator(hass, client, entry)

    await coordinator._async_update_data()

    for call in client.async_get_parcel.await_args_list:
        assert call.args[1] == POSTAL_CODE


async def test_update_not_found_shows_pending_placeholder(hass):
    entry = _entry_with(_parcels(BARCODE))
    entry.add_to_hass(hass)
    client = AsyncMock()
    client.async_get_parcel.return_value = None  # not found
    coordinator = BpostCoordinator(hass, client, entry)

    data = await coordinator._async_update_data()

    assert len(data) == 1
    assert data[0]["barcode"] == BARCODE
    assert data[0]["status"] == ParcelStatus.UNKNOWN


async def test_update_keeps_cached_payload_on_error(hass):
    entry = _entry_with(_parcels(BARCODE))
    entry.add_to_hass(hass)
    client = AsyncMock()
    client.async_get_parcel.return_value = delivered_item()
    coordinator = BpostCoordinator(hass, client, entry)
    await coordinator._async_update_data()  # populates the cache

    client.async_get_parcel.side_effect = BpostApiError("HTTP 500")
    await coordinator._async_update_data()  # error -> cached raw reused
    assert len(coordinator.delivered) == 1


async def test_update_raises_when_every_parcel_fails(hass):
    from homeassistant.helpers.update_coordinator import UpdateFailed

    entry = _entry_with(_parcels(BARCODE))
    entry.add_to_hass(hass)
    client = AsyncMock()
    client.async_get_parcel.side_effect = BpostApiError("HTTP 500")
    coordinator = BpostCoordinator(hass, client, entry)

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_update_reraises_unexpected_exceptions(hass):
    entry = _entry_with(_parcels(BARCODE))
    entry.add_to_hass(hass)
    client = AsyncMock()
    client.async_get_parcel.side_effect = ValueError("boom")
    coordinator = BpostCoordinator(hass, client, entry)

    with pytest.raises(ValueError):
        await coordinator._async_update_data()


async def test_update_skips_parcels_missing_a_barcode(hass):
    entry = _entry_with(
        [
            {CONF_BARCODE: ""},
            {CONF_BARCODE: BARCODE},
        ]
    )
    entry.add_to_hass(hass)
    client = AsyncMock()
    client.async_get_parcel.return_value = delivered_item()
    coordinator = BpostCoordinator(hass, client, entry)

    await coordinator._async_update_data()
    assert client.async_get_parcel.await_count == 1  # the blank barcode skipped


async def test_update_no_postal_code_tracks_nothing(hass):
    """A hub with no postal code (shouldn't normally happen) tracks nothing
    rather than fetching with a blank postal code."""
    entry = _entry_with(_parcels(BARCODE), postal_code="")
    entry.add_to_hass(hass)
    client = AsyncMock()
    coordinator = BpostCoordinator(hass, client, entry)

    data = await coordinator._async_update_data()

    assert data == []
    client.async_get_parcel.assert_not_awaited()


async def test_update_prunes_cache_for_untracked_parcels(hass):
    entry = _entry_with(_parcels(BARCODE))
    entry.add_to_hass(hass)
    client = AsyncMock()
    client.async_get_parcel.return_value = delivered_item()
    coordinator = BpostCoordinator(hass, client, entry)
    coordinator._raw_cache["GONE"] = {}

    await coordinator._async_update_data()

    assert "GONE" not in coordinator._raw_cache
    assert BARCODE in coordinator._raw_cache


async def test_update_fetches_parcels_concurrently(hass):
    import asyncio

    entry = _entry_with(_parcels(BARCODE, OTHER_BARCODE))
    entry.add_to_hass(hass)
    in_flight = 0
    peak = 0

    async def _slow_fetch(barcode, postal_code):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0)
        in_flight -= 1
        return active_item(barcode)

    client = AsyncMock()
    client.async_get_parcel.side_effect = _slow_fetch
    coordinator = BpostCoordinator(hass, client, entry)

    await coordinator._async_update_data()
    assert peak == 2


async def test_cache_only_poll_does_not_stamp_last_success(hass):
    entry = _entry_with(_parcels(BARCODE))
    entry.add_to_hass(hass)
    client = AsyncMock()
    client.async_get_parcel.return_value = delivered_item()
    coordinator = BpostCoordinator(hass, client, entry)
    await coordinator._async_update_data()
    stamp = coordinator.last_success_time
    assert stamp is not None

    client.async_get_parcel.side_effect = BpostApiError("HTTP 500")
    await coordinator._async_update_data()  # served from cache
    assert coordinator.last_success_time == stamp


# ---------------------------------------------------------------------------
# events
# ---------------------------------------------------------------------------


async def test_first_refresh_fires_nothing(hass):
    entry = _entry_with(_parcels(BARCODE))
    entry.add_to_hass(hass)
    client = AsyncMock()
    client.async_get_parcel.return_value = active_item()
    coordinator = BpostCoordinator(hass, client, entry)

    fired = []
    for suffix in (
        "parcel_registered",
        "parcel_status_changed",
        "parcel_delivered",
        "parcel_delivery_time_changed",
    ):
        hass.bus.async_listen(f"{DOMAIN}_{suffix}", lambda e: fired.append(e))

    await coordinator._async_update_data()
    await hass.async_block_till_done()

    assert fired == []


async def test_event_carries_device_id(hass):
    from homeassistant.helpers import device_registry as dr

    entry = _entry_with(_parcels(BARCODE))
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
    )
    client = AsyncMock()
    coordinator = BpostCoordinator(hass, client, entry)

    events = []
    hass.bus.async_listen(
        f"{DOMAIN}_parcel_status_changed", lambda e: events.append(e)
    )

    client.async_get_parcel.return_value = in_transit_item()
    await coordinator._async_update_data()
    client.async_get_parcel.return_value = active_item()
    await coordinator._async_update_data()
    await hass.async_block_till_done()

    assert events[0].data["device_id"] == device.id


async def test_fires_status_changed_event(hass):
    entry = _entry_with(_parcels(BARCODE))
    entry.add_to_hass(hass)
    client = AsyncMock()
    coordinator = BpostCoordinator(hass, client, entry)

    events = []
    hass.bus.async_listen(
        f"{DOMAIN}_parcel_status_changed", lambda e: events.append(e)
    )

    client.async_get_parcel.return_value = in_transit_item()
    await coordinator._async_update_data()  # first refresh: suppressed (unknown)

    client.async_get_parcel.return_value = active_item()  # out for delivery
    await coordinator._async_update_data()
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data["old_status"] == ParcelStatus.UNKNOWN
    assert events[0].data["new_status"] == ParcelStatus.OUT_FOR_DELIVERY


async def test_delivery_fires_delivered_event_and_not_status_changed(hass):
    entry = _entry_with(_parcels(BARCODE))
    entry.add_to_hass(hass)
    client = AsyncMock()
    coordinator = BpostCoordinator(hass, client, entry)

    delivered = []
    changed = []
    hass.bus.async_listen(f"{DOMAIN}_parcel_delivered", lambda e: delivered.append(e))
    hass.bus.async_listen(
        f"{DOMAIN}_parcel_status_changed", lambda e: changed.append(e)
    )

    client.async_get_parcel.return_value = active_item(BARCODE)
    await coordinator._async_update_data()
    client.async_get_parcel.return_value = delivered_item(BARCODE)
    await coordinator._async_update_data()
    await hass.async_block_till_done()

    assert changed == []
    assert len(delivered) == 1
    assert delivered[0].data["barcode"] == BARCODE
    assert delivered[0].data["status"] == ParcelStatus.DELIVERED


async def test_no_events_for_parcel_first_seen_delivered(hass):
    entry = _entry_with(_parcels(BARCODE))
    entry.add_to_hass(hass)
    client = AsyncMock()
    client.async_get_parcel.side_effect = lambda barcode, postal_code: (
        active_item(barcode) if barcode == BARCODE else delivered_item(barcode)
    )
    coordinator = BpostCoordinator(hass, client, entry)

    fired = []
    hass.bus.async_listen(f"{DOMAIN}_parcel_registered", lambda e: fired.append(e))
    hass.bus.async_listen(f"{DOMAIN}_parcel_delivered", lambda e: fired.append(e))

    await coordinator._async_update_data()  # first refresh seeds the state

    hass.config_entries.async_update_entry(
        entry,
        options={
            **entry.options,
            CONF_PARCELS: _parcels(BARCODE, OTHER_BARCODE),
        },
    )
    await coordinator._async_update_data()
    await hass.async_block_till_done()

    assert fired == []


async def test_fires_registered_event_for_new_parcel(hass):
    entry = _entry_with(_parcels(BARCODE))
    entry.add_to_hass(hass)
    client = AsyncMock()
    client.async_get_parcel.return_value = active_item(BARCODE)
    coordinator = BpostCoordinator(hass, client, entry)

    events = []
    hass.bus.async_listen(f"{DOMAIN}_parcel_registered", lambda e: events.append(e))

    await coordinator._async_update_data()  # first refresh: suppressed

    hass.config_entries.async_update_entry(
        entry,
        options={
            **entry.options,
            CONF_PARCELS: _parcels(BARCODE, OTHER_BARCODE),
        },
    )
    client.async_get_parcel.side_effect = lambda barcode, postal_code: active_item(barcode)
    await coordinator._async_update_data()
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data["barcode"] == OTHER_BARCODE


async def test_fires_delivery_time_changed_event(hass):
    entry = _entry_with(_parcels(BARCODE))
    entry.add_to_hass(hass)
    client = AsyncMock()
    coordinator = BpostCoordinator(hass, client, entry)

    events = []
    hass.bus.async_listen(
        f"{DOMAIN}_parcel_delivery_time_changed", lambda e: events.append(e)
    )

    client.async_get_parcel.return_value = active_item()
    await coordinator._async_update_data()  # first refresh: suppressed

    moved = active_item()
    moved["expectedDeliveryTimeRange"] = {
        "time1": "2026-04-29T16:00:00Z",
        "time2": "2026-04-29T18:00:00Z",
    }
    client.async_get_parcel.return_value = moved
    await coordinator._async_update_data()
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data["old_planned_from"] == "2026-04-29T13:00:00Z"
    assert events[0].data["new_planned_from"] == "2026-04-29T16:00:00Z"


async def test_losing_the_eta_is_silent(hass):
    entry = _entry_with(_parcels(BARCODE))
    entry.add_to_hass(hass)
    client = AsyncMock()
    coordinator = BpostCoordinator(hass, client, entry)

    events = []
    hass.bus.async_listen(
        f"{DOMAIN}_parcel_delivery_time_changed", lambda e: events.append(e)
    )

    client.async_get_parcel.return_value = active_item()
    await coordinator._async_update_data()

    dropped = active_item()
    del dropped["expectedDeliveryTimeRange"]
    client.async_get_parcel.return_value = dropped
    await coordinator._async_update_data()
    await hass.async_block_till_done()

    assert events == []
