"""Tests for the Mail Ahead letter image entities."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bpost.account.client import BpostAccountApiError
from custom_components.bpost.const import (
    CONF_EMAIL,
    CONF_SOURCE,
    DOMAIN,
    SOURCE_ACCOUNT,
)
from custom_components.bpost.image import BpostLetterImage

from .account.letters_payload import LETTERS_IMAGES

LETTERS = "custom_components.bpost.account.client.BpostAccountClient.async_get_letters"
SUMMARIES = "custom_components.bpost.account.client.BpostAccountClient.async_get_parcel_summaries"


async def _setup_account(hass, letters):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="account:me@example.test",
        data={CONF_SOURCE: SOURCE_ACCOUNT, CONF_EMAIL: "me@example.test", "access_token": "a", "refresh_token": "r"},
    )
    entry.add_to_hass(hass)
    with patch(SUMMARIES, new=AsyncMock(return_value=[])), patch(LETTERS, new=AsyncMock(return_value=letters)):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


def _letter_entities(hass, entry):
    return [
        e for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        if e.domain == "image"
    ]


async def test_one_image_per_letter_and_gone_letters_are_removed(hass):
    entry = await _setup_account(hass, LETTERS_IMAGES)
    assert {e.unique_id for e in _letter_entities(hass, entry)} == {
        f"{entry.entry_id}_letter_image_ITEM-NEW",
        f"{entry.entry_id}_letter_image_ITEM-OLD",
    }
    state = hass.states.get(_letter_entities(hass, entry)[0].entity_id)
    assert "image_url" not in state.attributes
    assert all("sig=" not in str(value) for value in state.attributes.values())

    coordinator = entry.runtime_data.coordinator
    with patch(SUMMARIES, new=AsyncMock(return_value=[])), patch(
        LETTERS, new=AsyncMock(return_value={"2026-10-03": LETTERS_IMAGES["2026-10-03"]})
    ):
        await coordinator.async_refresh()
        await hass.async_block_till_done()
    assert [e.unique_id for e in _letter_entities(hass, entry)] == [f"{entry.entry_id}_letter_image_ITEM-NEW"]


async def test_a_letter_without_a_scan_gets_no_image_entity(hass):
    without_scan = {"2026-10-03": [{**LETTERS_IMAGES["2026-10-03"][0], "imageUrl": None}]}
    entry = await _setup_account(hass, without_scan)
    assert _letter_entities(hass, entry) == []
    assert len(entry.runtime_data.coordinator.letters) == 1


async def test_tracking_entries_get_no_image_entities(hass):
    from custom_components.bpost.image import async_setup_entry

    entry = MagicMock()
    entry.data = {}
    add = MagicMock()
    await async_setup_entry(hass, entry, add)
    add.assert_not_called()


def _entity(hass, letters=None, image=("REF", "https://x.test/a.jpg")):
    coordinator = MagicMock()
    coordinator.letters = letters if letters is not None else [
        {"id": "ID", "date": "2026-10-03", "planned_delivery": "2026-10-03", "sender": None}
    ]
    coordinator.letter_image.return_value = image
    coordinator.async_fetch_letter_image = AsyncMock(return_value=(b"png", "image/png"))
    entry = MagicMock()
    entry.entry_id = "e1"
    entry.options = {}
    entry.data = {}
    return BpostLetterImage(hass, coordinator, entry, "ID"), coordinator


async def test_scan_is_fetched_once_and_served_from_cache(hass):
    entity, coordinator = _entity(hass)
    assert entity.image_last_updated == datetime(2026, 10, 3, tzinfo=timezone.utc)
    assert entity._attr_translation_placeholders == {"title": "2026-10-03"}
    assert await entity.async_image() == b"png"
    assert await entity.async_image() == b"png"
    coordinator.async_fetch_letter_image.assert_awaited_once()
    assert entity.content_type == "image/png"


async def test_a_new_signed_link_alone_does_not_refetch_but_a_new_scan_does(hass):
    entity, coordinator = _entity(hass)
    entity.async_write_ha_state = MagicMock()
    await entity.async_image()
    coordinator.letter_image.return_value = ("REF", "https://x.test/a.jpg?sig=new")
    entity._handle_coordinator_update()
    await entity.async_image()
    assert coordinator.async_fetch_letter_image.await_count == 1
    before = entity.image_last_updated
    coordinator.letter_image.return_value = ("REF2", "https://x.test/b.jpg")
    entity._handle_coordinator_update()
    await entity.async_image()
    assert coordinator.async_fetch_letter_image.await_count == 2
    assert entity.image_last_updated != before


async def test_fetch_failure_or_missing_link_returns_none(hass, caplog):
    entity, coordinator = _entity(hass)
    coordinator.async_fetch_letter_image.side_effect = BpostAccountApiError("403")
    assert await entity.async_image() is None
    assert "x.test" not in caplog.text
    entity, _ = _entity(hass, image=None)
    assert await entity.async_image() is None


async def test_letter_gone_makes_the_entity_unavailable(hass):
    entity, _ = _entity(hass, letters=[], image=None)
    assert entity.image_last_updated is not None
    assert entity.available is False
    assert entity.extra_state_attributes == {}
