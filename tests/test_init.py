"""Tests for bpost setup and unload."""
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bpost.api import BpostApiError
from custom_components.bpost.const import (
    CONF_BARCODE,
    CONF_PARCELS,
    CONF_POSTAL_CODE,
    DOMAIN,
)

from .payloads import BARCODE, OTHER_BARCODE, POSTAL_CODE
from .payloads import active_item as _sample


def _parcels(*barcodes: str) -> list[dict]:
    return [{CONF_BARCODE: b} for b in barcodes]


def _entry(parcels: list[dict], postal_code: str = POSTAL_CODE) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=postal_code,
        options={CONF_PARCELS: parcels, CONF_POSTAL_CODE: postal_code},
    )


async def test_setup_and_unload(hass):
    entry = _entry(_parcels(BARCODE))
    entry.add_to_hass(hass)

    with patch(
        "custom_components.bpost.api.BpostApiClient.async_get_parcel",
        new=AsyncMock(return_value=_sample()),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED

    # The active parcel produced a per-parcel sensor and the summary sensor.
    incoming = hass.states.get("sensor.bpost_1000_incoming_parcels")
    assert incoming is not None
    assert incoming.state == "1"

    # Services registered on setup...
    assert hass.services.has_service(DOMAIN, "track_parcel")

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED

    # ...and removed on unload (last/only hub gone).
    assert not hass.services.has_service(DOMAIN, "track_parcel")


async def test_setup_retries_when_first_refresh_fails(hass):
    """When the first data fetch fails, setup retries from the entry itself.

    The first refresh runs in __init__.py before platforms are forwarded, so a
    failure raises ConfigEntryNotReady from the entry setup (SETUP_RETRY) rather
    than — too late — from a forwarded platform.
    """
    entry = _entry(_parcels(BARCODE))
    entry.add_to_hass(hass)

    with patch(
        "custom_components.bpost.api.BpostApiClient.async_get_parcel",
        new=AsyncMock(side_effect=BpostApiError("bpost unreachable")),
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_per_parcel_sensor_spawn_and_remove(hass):
    entry = _entry(_parcels(BARCODE))
    entry.add_to_hass(hass)

    mock = AsyncMock(return_value=_sample())
    with patch("custom_components.bpost.api.BpostApiClient.async_get_parcel", new=mock):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        registry = er.async_get(hass)
        assert registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_{BARCODE}"
        )

        # The next poll returns a different tracking code: the summary sensor
        # spawns a new per-parcel sensor and removes the stale one.
        mock.return_value = _sample(OTHER_BARCODE)
        hass.config_entries.async_update_entry(
            entry,
            options={
                **entry.options,
                CONF_PARCELS: _parcels(OTHER_BARCODE),
            },
        )
        await entry.runtime_data.coordinator.async_request_refresh()
        await hass.async_block_till_done()

        assert registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_{OTHER_BARCODE}"
        )
        assert (
            registry.async_get_entity_id(
                "sensor", DOMAIN, f"{entry.entry_id}_{BARCODE}"
            )
            is None
        )


async def test_options_update_applies_live_without_reload(hass):
    """Adding a parcel via options refreshes the coordinator immediately."""
    entry = _entry(_parcels(BARCODE))
    entry.add_to_hass(hass)

    mock = AsyncMock(return_value=_sample())
    with patch("custom_components.bpost.api.BpostApiClient.async_get_parcel", new=mock):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        mock.side_effect = lambda barcode, postal_code: _sample(barcode)
        hass.config_entries.async_update_entry(
            entry,
            options={
                **entry.options,
                CONF_PARCELS: _parcels(BARCODE, OTHER_BARCODE),
            },
        )
        await hass.async_block_till_done()

    incoming = hass.states.get("sensor.bpost_1000_incoming_parcels")
    assert incoming.state == "2"
