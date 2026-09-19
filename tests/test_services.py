"""Tests for the bpost services (track_parcel / untrack_parcel)."""
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bpost.const import (
    CONF_BARCODE,
    CONF_EMAIL,
    CONF_PARCELS,
    CONF_POSTAL_CODE,
    CONF_SOURCE,
    CONF_TRACKING_CODE,
    DOMAIN,
    SOURCE_ACCOUNT,
)

from .payloads import BARCODE, POSTAL_CODE, active_item

_SAMPLE = active_item()
_PATCH_TARGET = "custom_components.bpost.api.BpostApiClient.async_get_parcel"

OTHER_POSTAL_CODE = "9000"


async def _setup(
    hass, parcels: list[dict] | None = None, postal_code: str = POSTAL_CODE
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=postal_code,
        options={CONF_PARCELS: parcels or [], CONF_POSTAL_CODE: postal_code},
    )
    entry.add_to_hass(hass)
    with patch(_PATCH_TARGET, new=AsyncMock(return_value=_SAMPLE)):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_track_parcel_adds_to_options(hass):
    entry = await _setup(hass)
    with patch(_PATCH_TARGET, new=AsyncMock(return_value=_SAMPLE)):
        await hass.services.async_call(
            DOMAIN,
            "track_parcel",
            {CONF_TRACKING_CODE: BARCODE},
            blocking=True,
        )
        await hass.async_block_till_done()

    assert entry.options[CONF_PARCELS] == [{CONF_BARCODE: BARCODE}]


async def test_track_parcel_trims_whitespace(hass):
    entry = await _setup(hass)
    with patch(_PATCH_TARGET, new=AsyncMock(return_value=_SAMPLE)):
        await hass.services.async_call(
            DOMAIN,
            "track_parcel",
            {CONF_TRACKING_CODE: f"  {BARCODE}  "},
            blocking=True,
        )
        await hass.async_block_till_done()

    assert entry.options[CONF_PARCELS] == [{CONF_BARCODE: BARCODE}]


async def test_track_parcel_rejects_blank_barcode(hass):
    await _setup(hass)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "track_parcel",
            {CONF_TRACKING_CODE: "   "},
            blocking=True,
        )


async def test_track_parcel_duplicate_is_noop(hass):
    entry = await _setup(hass)
    with patch(_PATCH_TARGET, new=AsyncMock(return_value=_SAMPLE)):
        for _ in range(2):
            await hass.services.async_call(
                DOMAIN,
                "track_parcel",
                {CONF_TRACKING_CODE: BARCODE},
                blocking=True,
            )
            await hass.async_block_till_done()

    assert len(entry.options[CONF_PARCELS]) == 1


async def test_untrack_parcel_removes_from_options(hass):
    entry = await _setup(hass, parcels=[{CONF_BARCODE: BARCODE}])
    with patch(_PATCH_TARGET, new=AsyncMock(return_value=_SAMPLE)):
        await hass.services.async_call(
            DOMAIN,
            "untrack_parcel",
            {CONF_TRACKING_CODE: BARCODE},
            blocking=True,
        )
        await hass.async_block_till_done()

    assert entry.options[CONF_PARCELS] == []


async def test_untrack_unknown_barcode_is_noop(hass):
    entry = await _setup(hass, parcels=[{CONF_BARCODE: BARCODE}])
    with patch(_PATCH_TARGET, new=AsyncMock(return_value=_SAMPLE)):
        await hass.services.async_call(
            DOMAIN,
            "untrack_parcel",
            {CONF_TRACKING_CODE: "999999999999"},
            blocking=True,
        )
        await hass.async_block_till_done()

    assert len(entry.options[CONF_PARCELS]) == 1


async def test_track_parcel_not_set_up_raises(hass):
    with pytest.raises(ServiceValidationError):
        from custom_components.bpost.services import _resolve_entry

        _resolve_entry(hass, None)


async def test_track_parcel_multiple_hubs_requires_postal_code(hass):
    with patch(_PATCH_TARGET, new=AsyncMock(return_value=_SAMPLE)):
        await _setup(hass, postal_code=POSTAL_CODE)
        await _setup(hass, postal_code=OTHER_POSTAL_CODE)

        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(
                DOMAIN,
                "track_parcel",
                {CONF_TRACKING_CODE: BARCODE},
                blocking=True,
            )


async def test_track_parcel_multiple_hubs_postal_code_selects_target(hass):
    with patch(_PATCH_TARGET, new=AsyncMock(return_value=_SAMPLE)):
        entry_a = await _setup(hass, postal_code=POSTAL_CODE)
        entry_b = await _setup(hass, postal_code=OTHER_POSTAL_CODE)

        await hass.services.async_call(
            DOMAIN,
            "track_parcel",
            {CONF_TRACKING_CODE: BARCODE, CONF_POSTAL_CODE: OTHER_POSTAL_CODE},
            blocking=True,
        )
        await hass.async_block_till_done()

    assert entry_b.options[CONF_PARCELS] == [{CONF_BARCODE: BARCODE}]
    assert entry_a.options[CONF_PARCELS] == []


async def test_track_parcel_unknown_postal_code_raises(hass):
    with patch(_PATCH_TARGET, new=AsyncMock(return_value=_SAMPLE)):
        await _setup(hass, postal_code=POSTAL_CODE)

        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(
                DOMAIN,
                "track_parcel",
                {CONF_TRACKING_CODE: BARCODE, CONF_POSTAL_CODE: "0000"},
                blocking=True,
            )


async def test_untrack_parcel_removes_from_whichever_hub_tracks_it(hass):
    with patch(_PATCH_TARGET, new=AsyncMock(return_value=_SAMPLE)):
        entry_a = await _setup(
            hass, parcels=[{CONF_BARCODE: BARCODE}], postal_code=POSTAL_CODE
        )
        entry_b = await _setup(hass, postal_code=OTHER_POSTAL_CODE)

        await hass.services.async_call(
            DOMAIN,
            "untrack_parcel",
            {CONF_TRACKING_CODE: BARCODE},
            blocking=True,
        )
        await hass.async_block_till_done()

    assert entry_a.options[CONF_PARCELS] == []
    assert entry_b.options[CONF_PARCELS] == []


async def _setup_account(hass, email: str = "me@example.test") -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"account:{email}",
        data={
            CONF_SOURCE: SOURCE_ACCOUNT,
            CONF_EMAIL: email,
            "access_token": "access",
            "refresh_token": "refresh",
        },
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.bpost.account.client.BpostAccountClient.async_get_parcel_summaries",
        new=AsyncMock(return_value=[]),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_account_only_setup_registers_no_services(hass):
    await _setup_account(hass)

    assert not hass.services.has_service(DOMAIN, "track_parcel")
    assert not hass.services.has_service(DOMAIN, "untrack_parcel")


async def test_track_parcel_never_writes_into_an_account_entry(hass):
    account = await _setup_account(hass)
    hub = await _setup(hass)

    with patch(_PATCH_TARGET, new=AsyncMock(return_value=_SAMPLE)):
        await hass.services.async_call(
            DOMAIN,
            "track_parcel",
            {CONF_TRACKING_CODE: BARCODE},
            blocking=True,
        )
        await hass.async_block_till_done()

    # The single-hub shortcut must count tracking hubs only, or an account
    # entry would silently absorb the parcel.
    assert hub.options[CONF_PARCELS] == [{CONF_BARCODE: BARCODE}]
    assert CONF_PARCELS not in account.options


async def test_unloading_the_last_tracking_hub_removes_services_despite_an_account(hass):
    await _setup_account(hass)
    hub = await _setup(hass)
    assert hass.services.has_service(DOMAIN, "track_parcel")

    assert await hass.config_entries.async_unload(hub.entry_id)
    await hass.async_block_till_done()

    assert not hass.services.has_service(DOMAIN, "track_parcel")


async def test_unloading_an_account_entry_keeps_the_hub_services(hass):
    account = await _setup_account(hass)
    await _setup(hass)

    assert await hass.config_entries.async_unload(account.entry_id)
    await hass.async_block_till_done()

    assert hass.services.has_service(DOMAIN, "track_parcel")
