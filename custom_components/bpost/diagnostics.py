"""Diagnostics support for the bpost parcel tracker integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import BpostConfigEntry

# Diagnostics are pasted into public issues, so redact anything that
# identifies a person, an address or a specific parcel. Over-redacting is
# cheap; under-redacting leaks a user's home address into a
# GitHub thread.
#
# "raw_status" is a deliberate over-redaction, mirroring the Ceska Posta "id"
# precedent: the canonical top-level parcel field (bpost's activeStep.name, no
# PII — §6 says explicitly not to redact it) and each history entry's own
# "raw_status" (a localised event *description*, which §6 says to redact
# until proven generic) share the same key name, and key-based redaction
# cannot tell them apart. The one-shot WARNING log lines (not diagnostics)
# remain the channel that carries activeStep.name in the clear for mapping
# unrecognised codes.
TO_REDACT = {
    # canonical fields we publish ourselves
    "barcode",
    "postal_code",
    "sender",
    "receiver",
    "url",
    "raw_status",
    # bpost payload fields
    "itemIdentifier",
    "itemCode",
    "postalCode",
    "senderCommercialName",
    # the delivery photo is a fetch token for the user's own doorstep
    "safeplacePicture",
    "refId",
    # deliveryPoint's contents are unconfirmed (§3/§4) — redact wholesale
    "deliveryPoint",
    # driver position near the delivery address
    "lastKnownLocation",
    "targetLocation",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: BpostConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for the bpost config entry."""
    coordinator = entry.runtime_data.coordinator

    return {
        "entry_options": async_redact_data(dict(entry.options), TO_REDACT),
        "counts": {
            "incoming_active": len(coordinator.data or []),
            "delivered": len(coordinator.delivered or []),
        },
        "polling": {
            "tier_minutes": coordinator.current_tier_minutes,
            "update_interval_seconds": (
                coordinator.update_interval.total_seconds()
                if coordinator.update_interval
                else None
            ),
            "suspended": coordinator.update_interval is None,
        },
        "incoming": async_redact_data(coordinator.data or [], TO_REDACT),
        "delivered": async_redact_data(coordinator.delivered or [], TO_REDACT),
    }
