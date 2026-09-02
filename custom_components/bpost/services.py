"""Services for the bpost parcel tracker integration.

`bpost.track_parcel` / `bpost.untrack_parcel` let you add or remove a tracked
parcel without opening the integration options — so a Lovelace button can
start tracking a parcel straight from a dashboard. Format-only validation
(non-empty barcode), deliberately not a live lookup — a service call must not
block on a network round-trip.

A hub is scoped to one postal code (config_flow.py's hub-per-postcode model,
mirroring GLS), so tracking normally needs only a barcode — the postal code
is implicit from the hub. ``track_parcel`` keeps an optional ``postal_code``
field to pick *which* hub when more than one is configured (e.g. a household
that also receives parcels addressed to a second postcode), the same escape
hatch GLS keeps for its own multi-hub households.
"""
from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .config_flow import normalize_barcode, normalize_postal_code, valid_barcode
from .const import CONF_BARCODE, CONF_PARCELS, CONF_POSTAL_CODE, DOMAIN
from .parcels import parcel_key

SERVICE_TRACK_PARCEL = "track_parcel"
SERVICE_UNTRACK_PARCEL = "untrack_parcel"

_TRACK_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_BARCODE): cv.string,
        vol.Optional(CONF_POSTAL_CODE): cv.string,
    }
)
_UNTRACK_SCHEMA = vol.Schema({vol.Required(CONF_BARCODE): cv.string})


def _resolve_entry(hass: HomeAssistant, postal_code: str | None) -> ConfigEntry:
    """Pick the bpost hub to act on.

    With one hub, that hub. With several, the ``postal_code`` argument
    selects it; if omitted and ambiguous, raise so the caller knows to
    specify one.
    """
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        raise ServiceValidationError("bpost is not set up")
    if postal_code:
        target = normalize_postal_code(postal_code)
        for entry in entries:
            if entry.options.get(CONF_POSTAL_CODE) == target:
                return entry
        raise ServiceValidationError(f"No bpost hub for postal code {target}")
    if len(entries) == 1:
        return entries[0]
    raise ServiceValidationError(
        "Multiple bpost hubs are set up — pass postal_code to choose one"
    )


def async_setup_services(hass: HomeAssistant) -> None:
    """Register the bpost services (idempotent)."""
    if hass.services.has_service(DOMAIN, SERVICE_TRACK_PARCEL):
        return

    async def _track(call: ServiceCall) -> None:
        barcode = normalize_barcode(call.data[CONF_BARCODE])
        if not valid_barcode(barcode):
            raise ServiceValidationError("A bpost barcode is required")
        entry = _resolve_entry(hass, call.data.get(CONF_POSTAL_CODE))

        parcels = [dict(p) for p in entry.options.get(CONF_PARCELS, [])]
        new_key = parcel_key(barcode)
        if any(parcel_key(p[CONF_BARCODE]) == new_key for p in parcels):
            return  # already tracked — no-op
        parcels.append({CONF_BARCODE: barcode})
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, CONF_PARCELS: parcels}
        )

    async def _untrack(call: ServiceCall) -> None:
        barcode = normalize_barcode(call.data[CONF_BARCODE])
        target_key = parcel_key(barcode)
        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            raise ServiceValidationError("bpost is not set up")
        # Remove the parcel from whichever hub(s) track it.
        for entry in entries:
            current = entry.options.get(CONF_PARCELS, [])
            kept = [
                p for p in current if parcel_key(p[CONF_BARCODE]) != target_key
            ]
            if len(kept) != len(current):
                hass.config_entries.async_update_entry(
                    entry, options={**entry.options, CONF_PARCELS: kept}
                )

    hass.services.async_register(
        DOMAIN, SERVICE_TRACK_PARCEL, _track, schema=_TRACK_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_UNTRACK_PARCEL, _untrack, schema=_UNTRACK_SCHEMA
    )


def async_unload_services(hass: HomeAssistant) -> None:
    """Remove the bpost services."""
    for service in (SERVICE_TRACK_PARCEL, SERVICE_UNTRACK_PARCEL):
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)
