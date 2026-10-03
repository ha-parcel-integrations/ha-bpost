"""Coordinator for the account inbox source."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from ..const import (
    CONF_INCLUDE_HISTORY,
    DEFAULT_INCLUDE_HISTORY,
    DOMAIN,
    MID_INTERVAL_MINUTES,
    ParcelStatus,
)
from ..events import (
    fire_incoming_change_events,
    fire_outgoing_change_events,
    snapshot_delivery_times,
    snapshot_states,
)
from ..tracking.parcels import apply_delivered_filter, resolve_lang, sort_parcels_by_ts
from .client import BpostAccountApiError, BpostAccountClient, BpostAccountReauthRequired
from .letters import extract_letters, public_letter
from .parcels import is_outgoing, normalize_account_parcel

_LOGGER = logging.getLogger(__name__)

# bpost's own app asks for the same 30-day window.
LETTER_WINDOW_DAYS = 29


class BpostAccountCoordinator(DataUpdateCoordinator[dict[str, list[dict]]]):
    """Refresh the full account inbox; accounts never suspend polling."""

    def __init__(self, hass: HomeAssistant, client: BpostAccountClient, entry: ConfigEntry) -> None:
        """Initialise a continuously-polled account inbox coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} account",
            update_interval=timedelta(minutes=MID_INTERVAL_MINUTES),
        )
        self._client = client
        # None on the first update deliberately suppresses historical events.
        self._known_state: dict[str, ParcelStatus] | None = None
        self._known_delivery_times: dict[str, tuple[str | None, str | None]] | None = None
        self._known_outgoing_state: dict[str, ParcelStatus] | None = None
        self._cached_device_id: str | None = None
        self._delivered_codes: set[str] = set()
        self.last_success_time: datetime | None = None
        self._letters: list[dict[str, Any]] = []
        # None until the first successful letters fetch, so letters already
        # waiting when HA starts do not announce themselves.
        self._known_letter_ids: set[str] | None = None
        self.current_tier_minutes: int | None = MID_INTERVAL_MINUTES

    @property
    def delivered_codes(self) -> set[str]:
        """Account polls are batched; no individual parcel is skipped."""
        return self._delivered_codes

    def _device_id(self) -> str | None:
        """Resolve the account device id for event and device-trigger payloads."""
        if self._cached_device_id is not None:
            return self._cached_device_id
        registry = dr.async_get(self.hass)
        device = next(
            iter(dr.async_entries_for_config_entry(registry, self.config_entry.entry_id)),
            None,
        )
        if device is not None:
            self._cached_device_id = device.id
        return self._cached_device_id

    @property
    def letters(self) -> list[dict[str, Any]]:
        """Mail Ahead letters, without the fields that open their scans."""
        return [public_letter(letter) for letter in self._letters]

    def letter_image(self, letter_id: str) -> tuple[str | None, str | None] | None:
        """Return a letter's ``(image_ref, image_url)``, or None once it is gone."""
        for letter in self._letters:
            if letter["id"] == letter_id:
                return letter["image_ref"], letter["image_url"]
        return None

    async def async_fetch_letter_image(self, url: str) -> tuple[bytes, str | None]:
        """Fetch a letter scan through the account client."""
        return await self._client.async_get_letter_image(url)

    async def _async_update_letters(self) -> None:
        """Refresh letters; a failure keeps the previous list and the parcels."""
        today = date.today()
        try:
            images = await self._client.async_get_letters(
                (today - timedelta(days=LETTER_WINDOW_DAYS)).isoformat(),
                today.isoformat(),
            )
        except BpostAccountReauthRequired:
            raise
        except BpostAccountApiError as err:
            _LOGGER.warning("Unable to update bpost Mail Ahead letters: %s", err)
            return
        self._letters = extract_letters(images)
        self._fire_letter_events()
        self._known_letter_ids = {letter["id"] for letter in self._letters}

    def _fire_letter_events(self) -> None:
        """Fire ``bpost_letter_announced`` for letters not seen last time."""
        if self._known_letter_ids is None:
            return
        for letter in self._letters:
            if letter["id"] not in self._known_letter_ids:
                self.hass.bus.async_fire(
                    f"{DOMAIN}_letter_announced",
                    {**public_letter(letter), "carrier": "bpost", "device_id": self._device_id()},
                )

    def _fire_incoming_change_events(self, parcels: list[dict]) -> None:
        """Fire the receiver-side event set for this cycle's parcels."""
        fire_incoming_change_events(
            self.hass,
            parcels,
            self._known_state,
            self._known_delivery_times,
            self._device_id(),
        )

    def _fire_outgoing_change_events(self, parcels: list[dict]) -> None:
        """Fire the sender-side event set for this cycle's parcels."""
        fire_outgoing_change_events(
            self.hass,
            parcels,
            self._known_outgoing_state,
            self._device_id(),
        )

    async def _async_update_data(self) -> dict[str, list[dict]]:
        try:
            summaries = await self._client.async_get_parcel_summaries()
        except BpostAccountReauthRequired:
            raise
        except BpostAccountApiError as err:
            raise UpdateFailed("Unable to update bpost account inbox") from err

        include_history = bool(self.config_entry.options.get(CONF_INCLUDE_HISTORY, DEFAULT_INCLUDE_HISTORY))
        lang = resolve_lang(self.hass.config.language)
        parcels = [
            normalize_account_parcel(raw, include_history=include_history, lang=lang)
            for raw in summaries
        ]
        incoming = [parcel for raw, parcel in zip(summaries, parcels) if not is_outgoing(raw)]
        outgoing = [parcel for raw, parcel in zip(summaries, parcels) if is_outgoing(raw)]
        self._fire_outgoing_change_events(outgoing)
        self._known_outgoing_state = snapshot_states(outgoing)
        active = [parcel for parcel in incoming if not parcel["delivered"]]
        delivered = [parcel for parcel in incoming if parcel["delivered"]]
        outgoing_active = sort_parcels_by_ts(
            [parcel for parcel in outgoing if not parcel["delivered"]], "planned_from"
        )
        outgoing_delivered = apply_delivered_filter(
            sort_parcels_by_ts([parcel for parcel in outgoing if parcel["delivered"]], "delivered_at", descending=True), self.config_entry
        )
        incoming_delivered = apply_delivered_filter(
            sort_parcels_by_ts(delivered, "delivered_at", descending=True), self.config_entry
        )
        incoming_active = sort_parcels_by_ts(active, "planned_from")

        # Active + delivered, combined so the transition to delivered is
        # visible in one set — same shape the tracking coordinator diffs.
        seen_incoming = incoming_active + incoming_delivered
        self._fire_incoming_change_events(seen_incoming)
        self._known_state = snapshot_states(seen_incoming)
        self._known_delivery_times = snapshot_delivery_times(seen_incoming)

        await self._async_update_letters()

        self._delivered_codes = set()
        self.last_success_time = datetime.now(timezone.utc)
        return {
            "incoming_active": incoming_active,
            "incoming_delivered": incoming_delivered,
            "outgoing_active": outgoing_active,
            "outgoing_delivered": outgoing_delivered,
        }
