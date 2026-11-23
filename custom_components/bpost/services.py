"""Services for the bpost parcel tracker integration.

`bpost.track_parcel` / `bpost.untrack_parcel` let you add or remove a tracked
parcel without opening the integration options — so a Lovelace button can
start tracking a parcel straight from a dashboard. Format-only validation
(non-empty tracking code), deliberately not a live lookup — a service call must not
block on a network round-trip.

A hub is scoped to one postal code (config_flow.py's hub-per-postcode model,
mirroring GLS), so tracking normally needs only a ``tracking_code`` — the postal code
is implicit from the hub. ``track_parcel`` keeps an optional ``postal_code``
field to pick *which* hub when more than one is configured (e.g. a household
that also receives parcels addressed to a second postcode), the same escape
hatch GLS keeps for its own multi-hub households.

``bpost.update_contents`` sets or clears the text describing what is in a
parcel, tracked or not, on the hub(s) or account(s) that list the code.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
import voluptuous as vol

from .config_flow import normalize_barcode, normalize_postal_code, valid_barcode
from .const import (
    CONF_BARCODE,
    CONF_CONFIG_ENTRY_ID,
    CONF_CONTENTS,
    CONF_PARCELS,
    CONF_POSTAL_CODE,
    CONF_SOURCE,
    CONF_TRACKING_CODE,
    DOMAIN,
    SOURCE_TRACKING,
)
from .contents import ContentsStore, normalize_code
from .tracking.parcels import parcel_key

SERVICE_TRACK_PARCEL = "track_parcel"
SERVICE_UNTRACK_PARCEL = "untrack_parcel"
SERVICE_UPDATE_CONTENTS = "update_contents"

_TRACK_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_TRACKING_CODE): cv.string,
        vol.Optional(CONF_POSTAL_CODE): cv.string,
        vol.Optional(CONF_CONTENTS): cv.string,
    }
)
_UNTRACK_SCHEMA = vol.Schema({vol.Required(CONF_TRACKING_CODE): cv.string})
_UPDATE_CONTENTS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_TRACKING_CODE): cv.string,
        vol.Optional(CONF_CONTENTS): cv.string,
        vol.Optional(CONF_CONFIG_ENTRY_ID): cv.string,
    }
)


def _resolve_entry(hass: HomeAssistant, postal_code: str | None) -> ConfigEntry:
    """Pick the bpost hub to act on.

    With one hub, that hub. With several, the ``postal_code`` argument
    selects it; if omitted and ambiguous, raise so the caller knows to
    specify one.
    """
    entries = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.data.get(CONF_SOURCE, SOURCE_TRACKING) == SOURCE_TRACKING
    ]
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


def _loaded_coordinator(entry: ConfigEntry):
    """Return the coordinator of a set-up entry, or raise when it is not loaded."""
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError("bpost is not loaded")
    return entry.runtime_data.coordinator


def _contents_store(entry: ConfigEntry) -> ContentsStore | None:
    """Return the entry's contents store, or ``None`` when it is not loaded."""
    if entry.state is not ConfigEntryState.LOADED:
        return None
    return entry.runtime_data.coordinator.contents_store


def async_setup_services(hass: HomeAssistant, *, hub: bool = True) -> None:
    """Register the bpost services (idempotent).

    ``update_contents`` serves every entry; ``track_parcel`` and
    ``untrack_parcel`` belong to the tracking hubs, so an account entry passes
    ``hub=False``.
    """

    async def _track(call: ServiceCall) -> None:
        barcode = normalize_barcode(call.data[CONF_TRACKING_CODE])
        if not valid_barcode(barcode):
            raise ServiceValidationError("A bpost barcode is required")
        entry = _resolve_entry(hass, call.data.get(CONF_POSTAL_CODE))

        has_contents = CONF_CONTENTS in call.data
        coordinator = _loaded_coordinator(entry) if has_contents else None

        parcels = [dict(p) for p in entry.options.get(CONF_PARCELS, [])]
        new_key = parcel_key(barcode)
        if any(parcel_key(p[CONF_BARCODE]) == new_key for p in parcels):
            # Already tracked: only a changed contents value does anything.
            if coordinator is not None and coordinator.contents_store.async_set(
                barcode, call.data[CONF_CONTENTS]
            ):
                await coordinator.async_request_refresh()
            return
        if coordinator is not None:
            # Stored before the options write, whose listener refreshes.
            coordinator.contents_store.async_set(barcode, call.data[CONF_CONTENTS])
        parcels.append({CONF_BARCODE: barcode})
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, CONF_PARCELS: parcels}
        )

    async def _untrack(call: ServiceCall) -> None:
        barcode = normalize_barcode(call.data[CONF_TRACKING_CODE])
        target_key = parcel_key(barcode)
        entries = [
            entry
            for entry in hass.config_entries.async_entries(DOMAIN)
            if entry.data.get(CONF_SOURCE, SOURCE_TRACKING) == SOURCE_TRACKING
        ]
        if not entries:
            raise ServiceValidationError("bpost is not set up")
        # Remove the parcel from whichever hub(s) track it.
        for entry in entries:
            current = entry.options.get(CONF_PARCELS, [])
            kept = [p for p in current if parcel_key(p[CONF_BARCODE]) != target_key]
            if len(kept) != len(current):
                if (store := _contents_store(entry)) is not None:
                    store.async_set(barcode, None)
                hass.config_entries.async_update_entry(
                    entry, options={**entry.options, CONF_PARCELS: kept}
                )

    async def _update_contents(call: ServiceCall) -> None:
        code = normalize_code(call.data[CONF_TRACKING_CODE])
        if not code:
            raise ServiceValidationError("A tracking code is required")
        loaded = [
            entry
            for entry in hass.config_entries.async_entries(DOMAIN)
            if entry.state is ConfigEntryState.LOADED
        ]
        if not loaded:
            raise ServiceValidationError("bpost is not set up")
        if entry_id := call.data.get(CONF_CONFIG_ENTRY_ID):
            targets = [entry for entry in loaded if entry.entry_id == entry_id]
            if not targets:
                raise ServiceValidationError(
                    f"'{entry_id}' is not a loaded bpost entry"
                )
        elif len(loaded) == 1:
            targets = loaded
        else:
            # A code can sit in two entries, so every entry that lists it gets
            # the value; guessing an entry would write to the wrong one.
            targets = [
                entry
                for entry in loaded
                if code in entry.runtime_data.coordinator.known_codes
            ]
            if not targets:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="update_contents_entry_required",
                )
        for entry in targets:
            coordinator = entry.runtime_data.coordinator
            if coordinator.contents_store.async_set(code, call.data.get(CONF_CONTENTS)):
                await coordinator.async_request_refresh()

    if hub and not hass.services.has_service(DOMAIN, SERVICE_TRACK_PARCEL):
        hass.services.async_register(
            DOMAIN, SERVICE_TRACK_PARCEL, _track, schema=_TRACK_SCHEMA
        )
        hass.services.async_register(
            DOMAIN, SERVICE_UNTRACK_PARCEL, _untrack, schema=_UNTRACK_SCHEMA
        )
    if not hass.services.has_service(DOMAIN, SERVICE_UPDATE_CONTENTS):
        hass.services.async_register(
            DOMAIN,
            SERVICE_UPDATE_CONTENTS,
            _update_contents,
            schema=_UPDATE_CONTENTS_SCHEMA,
        )


def async_unload_services(hass: HomeAssistant, *, keep_contents: bool = False) -> None:
    """Remove the bpost services their entries no longer need.

    Called once the last tracking hub is gone, which takes ``track_parcel`` and
    ``untrack_parcel`` with it; ``update_contents`` stays while any other entry
    is loaded (``keep_contents``).
    """
    services = [SERVICE_TRACK_PARCEL, SERVICE_UNTRACK_PARCEL]
    if not keep_contents:
        services.append(SERVICE_UPDATE_CONTENTS)
    for service in services:
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)
