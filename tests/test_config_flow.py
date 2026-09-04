"""Tests for the bpost config and options flow."""
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bpost.config_flow import (
    normalize_barcode,
    normalize_postal_code,
    valid_barcode,
    valid_postal_code,
)
from custom_components.bpost.const import (
    CONF_BARCODE,
    CONF_DELIVERED_FILTER_AMOUNT,
    CONF_DELIVERED_FILTER_TYPE,
    CONF_INCLUDE_HISTORY,
    CONF_PARCELS,
    CONF_POSTAL_CODE,
    DOMAIN,
)

from .payloads import BARCODE, POSTAL_CODE


def test_normalize_barcode_and_postal_code_only_strip():
    assert normalize_barcode("  323456789012  ") == "323456789012"
    assert normalize_barcode(None) == ""
    assert normalize_postal_code(" 1000 ") == "1000"


def test_valid_barcode_and_postal_code_require_non_empty():
    assert valid_barcode("323456789012")
    assert not valid_barcode("")
    assert valid_postal_code("1000")
    assert not valid_postal_code("")


async def test_user_flow_creates_hub_with_postcode_only(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_POSTAL_CODE: f" {POSTAL_CODE} "}
    )
    assert result["type"] == "create_entry"
    assert result["title"] == f"bpost ({POSTAL_CODE})"
    assert result["options"][CONF_PARCELS] == []
    assert result["options"][CONF_POSTAL_CODE] == POSTAL_CODE


async def test_user_flow_invalid_postcode(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_POSTAL_CODE: "  "}
    )
    assert result["errors"][CONF_POSTAL_CODE] == "invalid_postcode"


async def test_same_postcode_hub_rejected(hass):
    MockConfigEntry(domain=DOMAIN, unique_id=POSTAL_CODE).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_POSTAL_CODE: POSTAL_CODE}
    )
    assert result["type"] == "abort"
    assert result["reason"] == "already_configured"


async def test_second_hub_different_postcode_allowed(hass):
    """A hub for a different postcode is allowed (home + a second address)."""
    MockConfigEntry(domain=DOMAIN, unique_id=POSTAL_CODE).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_POSTAL_CODE: "9000"}
    )
    assert result["type"] == "create_entry"
    assert result["title"] == "bpost (9000)"


def _hub(parcels: list[dict]) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=POSTAL_CODE,
        options={CONF_PARCELS: parcels, CONF_POSTAL_CODE: POSTAL_CODE},
    )


def _parcel(barcode: str = BARCODE) -> dict:
    return {CONF_BARCODE: barcode}


async def _open_menu_step(hass, entry, step_id: str):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "menu"
    assert result["menu_options"] == ["parcels", "settings"]
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": step_id}
    )


async def test_options_parcels_add(hass):
    entry = _hub([])
    entry.add_to_hass(hass)
    result = await _open_menu_step(hass, entry, "parcels")

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"tracking_codes": [BARCODE]}
    )

    assert result["type"] == "create_entry"
    assert result["data"][CONF_PARCELS] == [_parcel()]
    # The hub's postal code is untouched by the parcels step.
    assert result["data"][CONF_POSTAL_CODE] == POSTAL_CODE


async def test_options_parcels_remove(hass):
    entry = _hub([_parcel(), _parcel("OTHERBARCODE")])
    entry.add_to_hass(hass)
    result = await _open_menu_step(hass, entry, "parcels")

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"tracking_codes": [BARCODE]}
    )

    assert result["type"] == "create_entry"
    assert result["data"][CONF_PARCELS] == [_parcel()]


async def test_options_parcels_deduplicates_and_normalizes(hass):
    entry = _hub([])
    entry.add_to_hass(hass)
    result = await _open_menu_step(hass, entry, "parcels")

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"tracking_codes": [f"  {BARCODE}  ", BARCODE, ""]}
    )

    assert result["data"][CONF_PARCELS] == [_parcel()]


async def test_options_changes_history_and_delivered(hass):
    entry = _hub([])
    entry.add_to_hass(hass)
    result = await _open_menu_step(hass, entry, "settings")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_DELIVERED_FILTER_TYPE: "parcels",
            CONF_DELIVERED_FILTER_AMOUNT: 5,
            CONF_INCLUDE_HISTORY: True,
        },
    )
    assert result["type"] == "create_entry"
    assert result["data"][CONF_INCLUDE_HISTORY] is True
    assert result["data"][CONF_DELIVERED_FILTER_TYPE] == "parcels"
    assert result["data"][CONF_DELIVERED_FILTER_AMOUNT] == 5
    # The hub's postal code and tracked parcels survive a settings save.
    assert result["data"][CONF_POSTAL_CODE] == POSTAL_CODE
