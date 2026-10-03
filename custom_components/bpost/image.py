"""Image platform for bpost: scans of Mail Ahead letters (account source only)."""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timezone
from typing import Any

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import BpostConfigEntry
from .account.coordinator import BpostAccountCoordinator
from .const import CONF_SOURCE, DOMAIN, SOURCE_ACCOUNT
from .device import ATTRIBUTION, build_device_info

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


def _letter_day(letter: dict | None) -> datetime | None:
    """Return the letter's group date as a UTC datetime, or None."""
    try:
        day = date.fromisoformat(str((letter or {}).get("date")))
    except ValueError:
        return None
    return datetime.combine(day, time.min, tzinfo=timezone.utc)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BpostConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add one image entity per letter and keep the set in sync."""
    if entry.data.get(CONF_SOURCE) != SOURCE_ACCOUNT:
        return
    coordinator: BpostAccountCoordinator = entry.runtime_data.coordinator
    unique_prefix = f"{entry.entry_id}_letter_image_"
    known_ids: set[str] = set()

    @callback
    def _sync_letters() -> None:
        current_ids = {
            letter["id"]
            for letter in coordinator.letters
            if (coordinator.letter_image(letter["id"]) or (None, None))[1]
        }
        new_ids = current_ids - known_ids
        if new_ids:
            async_add_entities(
                BpostLetterImage(hass, coordinator, entry, letter_id)
                for letter_id in sorted(new_ids)
            )
            known_ids.update(new_ids)
        stale_ids = known_ids - current_ids
        if stale_ids:
            # Removed via the registry, not self-removal, to avoid ghost entities.
            registry = er.async_get(hass)
            for letter_id in stale_ids:
                entity_id = registry.async_get_entity_id(
                    "image", DOMAIN, f"{unique_prefix}{letter_id}"
                )
                if entity_id:
                    registry.async_remove(entity_id)
            known_ids.difference_update(stale_ids)

    _sync_letters()
    entry.async_on_unload(coordinator.async_add_listener(_sync_letters))


class BpostLetterImage(CoordinatorEntity[BpostAccountCoordinator], ImageEntity):
    """The scan of a single Mail Ahead letter."""

    _attr_has_entity_name = True
    _attr_translation_key = "letter_image"
    _attr_content_type = "image/jpeg"
    _attr_attribution = ATTRIBUTION

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: BpostAccountCoordinator,
        entry: ConfigEntry,
        letter_id: str,
    ) -> None:
        """Initialise the image entity."""
        CoordinatorEntity.__init__(self, coordinator)
        ImageEntity.__init__(self, hass)
        self._letter_id = letter_id
        self._attr_unique_id = f"{entry.entry_id}_letter_image_{letter_id}"
        self._attr_device_info = build_device_info(entry)
        self._attr_image_last_updated = _letter_day(self._letter()) or dt_util.utcnow()
        self._image_ref = self._image()[0]
        self._cached_bytes: bytes | None = None
        letter = self._letter() or {}
        self._attr_translation_placeholders = {
            "title": letter.get("sender") or letter.get("date") or letter_id
        }

    def _letter(self) -> dict | None:
        return next(
            (letter for letter in self.coordinator.letters if letter["id"] == self._letter_id),
            None,
        )

    def _image(self) -> tuple[str | None, str | None]:
        return self.coordinator.letter_image(self._letter_id) or (None, None)

    @property
    def available(self) -> bool:
        """Return whether the letter is still in bpost's window."""
        return super().available and self._letter() is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Mirror the letter as the sensor lists it; the scan is the state."""
        return self._letter() or {}

    @callback
    def _handle_coordinator_update(self) -> None:
        image_ref = self._image()[0]
        if image_ref != self._image_ref:
            # A signed link may change every poll; only a new scan invalidates.
            self._image_ref = image_ref
            self._cached_bytes = None
            self._attr_image_last_updated = dt_util.utcnow()
        super()._handle_coordinator_update()

    async def async_image(self) -> bytes | None:
        """Return the scan, fetched server-side so its link never leaves HA."""
        if self._cached_bytes is not None:
            return self._cached_bytes
        url = self._image()[1]
        if not url:
            return None
        try:
            image_bytes, content_type = await self.coordinator.async_fetch_letter_image(url)
        except Exception as err:  # noqa: BLE001 - a failed scan must not break the entity
            # async_image may only raise cancellation/timeout/content-type errors.
            _LOGGER.warning("Could not fetch bpost letter image: %s", type(err).__name__)
            return None
        if content_type and content_type.startswith("image/"):
            self._attr_content_type = content_type
        self._cached_bytes = image_bytes
        return image_bytes
