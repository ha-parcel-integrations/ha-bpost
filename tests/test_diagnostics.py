"""Tests for bpost diagnostics."""
from datetime import timedelta
from unittest.mock import MagicMock

from homeassistant.components.diagnostics import async_redact_data

from custom_components.bpost.diagnostics import (
    TO_REDACT,
    async_get_config_entry_diagnostics,
)


async def test_diagnostics_redacts_and_counts(hass):
    """Diagnostics get pasted into public issues — nothing identifying may survive."""
    entry = MagicMock()
    entry.options = {"parcels": [{"barcode": "323456789012", "postal_code": "1000"}]}
    entry.runtime_data.coordinator.current_tier_minutes = 15
    entry.runtime_data.coordinator.update_interval = timedelta(minutes=15)
    entry.runtime_data.coordinator.data = [
        {
            "barcode": "323456789012",
            "sender": "Example Shop",
            "receiver": None,
            "status": "out_for_delivery",
            "raw_status": "out_for_delivery_byCar",
            "url": "https://track.bpost.cloud/btr/web/#/search?lang=en&itemCode=323456789012&postalCode=1000",
            "raw": {
                "shipmentType": "PARCEL",
                "deliveryPoint": {"name": "Some Point"},
            },
            "history": [
                {"timestamp": "2026-04-29T08:00:00Z", "status": None, "raw_status": "Onderweg naar Jan Janssens"},
            ],
        }
    ]
    entry.runtime_data.coordinator.delivered = []

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["counts"] == {"incoming_active": 1, "delivered": 0}
    assert result["polling"] == {
        "tier_minutes": 15,
        "update_interval_seconds": 900.0,
        "suspended": False,
    }
    assert result["entry_options"]["parcels"][0]["barcode"] == "**REDACTED**"
    assert result["entry_options"]["parcels"][0]["postal_code"] == "**REDACTED**"
    assert result["incoming"][0]["barcode"] == "**REDACTED**"
    assert result["incoming"][0]["sender"] == "**REDACTED**"
    assert result["incoming"][0]["url"] == "**REDACTED**"
    assert result["incoming"][0]["raw"]["deliveryPoint"] == "**REDACTED**"
    # the over-redaction trade-off (see diagnostics.py): both the top-level
    # activeStep.name-derived field and the per-event description share the
    # "raw_status" key, so both get blanked.
    assert result["incoming"][0]["raw_status"] == "**REDACTED**"
    assert result["incoming"][0]["history"][0]["raw_status"] == "**REDACTED**"
    # non-identifying fields survive, or the diagnostics would be useless
    assert result["incoming"][0]["status"] == "out_for_delivery"
    assert result["incoming"][0]["raw"]["shipmentType"] == "PARCEL"


async def test_diagnostics_redacts_raw_sender_and_event_descriptions(hass):
    """raw is the untouched payload now (not an allowlist) — the sender name
    and event-description text it carries must still never reach a public
    issue."""
    entry = MagicMock()
    entry.options = {"parcels": [{"barcode": "323456789012", "postal_code": "1000"}]}
    entry.runtime_data.coordinator.current_tier_minutes = None
    entry.runtime_data.coordinator.update_interval = None
    entry.runtime_data.coordinator.data = [
        {
            "barcode": "323456789012",
            "sender": "Example Shop",
            "receiver": None,
            "status": "out_for_delivery",
            "raw_status": "out_for_delivery_byCar",
            "url": "https://track.bpost.cloud/btr/web/#/search?lang=en&itemCode=323456789012&postalCode=1000",
            "raw": {
                "shipmentType": "PARCEL",
                "sender": {"name": "Jan Janssens"},
                "events": [
                    {
                        "date": "2026-04-29",
                        "time": "08:46",
                        "key": {"EN": {"description": "Onderweg naar Jan Janssens"}},
                    }
                ],
            },
            "history": [],
        }
    ]
    entry.runtime_data.coordinator.delivered = []

    result = await async_get_config_entry_diagnostics(hass, entry)

    raw = result["incoming"][0]["raw"]
    assert raw["sender"] == "**REDACTED**"
    assert raw["events"][0]["key"]["EN"]["description"] == "**REDACTED**"
    # non-identifying fields survive
    assert raw["shipmentType"] == "PARCEL"
    assert raw["events"][0]["date"] == "2026-04-29"


async def test_diagnostics_reports_suspended_polling(hass):
    """update_interval None (Section 2.1's full stop) must be visible, not just absent."""
    entry = MagicMock()
    entry.options = {"parcels": []}
    entry.runtime_data.coordinator.current_tier_minutes = None
    entry.runtime_data.coordinator.update_interval = None
    entry.runtime_data.coordinator.data = []
    entry.runtime_data.coordinator.delivered = []

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["polling"] == {
        "tier_minutes": None,
        "update_interval_seconds": None,
        "suspended": True,
    }


def test_redaction_key_set_survives_untouched():
    """§6: redaction replaces values, never drops a key."""
    sample = {
        "barcode": "X",
        "postal_code": "Y",
        "sender": "Z",
        "receiver": None,
        "url": "u",
        "raw_status": "delivered",
        "status": "delivered",
        "raw": {"deliveryPoint": {"name": "n"}, "shipmentType": "PARCEL"},
    }
    redacted = async_redact_data(sample, TO_REDACT)
    assert set(redacted.keys()) == set(sample.keys())
    assert set(redacted["raw"].keys()) == set(sample["raw"].keys())
