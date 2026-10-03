"""Account credential redaction tests."""
from homeassistant.components.diagnostics import async_redact_data

from custom_components.bpost.diagnostics import TO_REDACT


def test_account_credentials_and_personal_fields_are_redacted():
    redacted = async_redact_data(
        {"email": "person@example.test", "access_token": "secret", "receiver": {"phone": "123"}},
        TO_REDACT,
    )
    assert redacted["email"] == "**REDACTED**"
    assert redacted["access_token"] == "**REDACTED**"
    assert redacted["receiver"] == "**REDACTED**"


async def test_account_diagnostics_list_letters_without_sender_or_link(hass):
    from unittest.mock import AsyncMock, MagicMock

    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.bpost.account.coordinator import BpostAccountCoordinator
    from custom_components.bpost.const import DOMAIN
    from custom_components.bpost.diagnostics import async_get_config_entry_diagnostics

    from .letters_payload import LETTERS_IMAGES

    client = AsyncMock()
    client.async_get_parcel_summaries.return_value = []
    client.async_get_letters.return_value = LETTERS_IMAGES
    coordinator = BpostAccountCoordinator(hass, client, MockConfigEntry(domain=DOMAIN))
    coordinator.data = await coordinator._async_update_data()
    entry = MagicMock()
    entry.data = {}
    entry.options = {}
    entry.runtime_data.coordinator = coordinator
    result = await async_get_config_entry_diagnostics(hass, entry)
    assert result["counts"]["letters"] == 2
    assert result["letters"][1]["sender"] == "**REDACTED**"
    assert "sig=" not in str(result)
