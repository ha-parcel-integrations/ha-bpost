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
