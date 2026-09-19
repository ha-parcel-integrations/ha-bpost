"""Config flow for the bpost parcel tracker integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .account.client import (
    BpostAccountApiError,
    BpostAccountClient,
    BpostAccountInvalidCredentials,
)
from .const import (
    CONF_BARCODE,
    CONF_DELIVERED_FILTER_AMOUNT,
    CONF_DELIVERED_FILTER_TYPE,
    CONF_EMAIL,
    CONF_INCLUDE_HISTORY,
    CONF_PARCELS,
    CONF_PASSWORD,
    CONF_POSTAL_CODE,
    CONF_SOURCE,
    DEFAULT_DELIVERED_FILTER_AMOUNT,
    DEFAULT_DELIVERED_FILTER_TYPE,
    DEFAULT_INCLUDE_HISTORY,
    DOMAIN,
    SOURCE_ACCOUNT,
    SOURCE_TRACKING,
)

_LOGGER = logging.getLogger(__name__)


def normalize_barcode(value: str) -> str:
    """Return the barcode trimmed, nothing else.

    No published regex or checksum exists for a bpost barcode, so this
    deliberately does not upper-case or strip separators — unlike a carrier
    with a confirmed format, guessing a transform here could turn a valid
    barcode into one the endpoint rejects.
    """
    return (value or "").strip()


def normalize_postal_code(value: str) -> str:
    """Return the postal code trimmed, nothing else.

    Passed through to the carrier verbatim — accepting any non-empty
    trimmed value (rather than a Belgian-only 4-digit rule) is deliberate,
    so a cross-border delivery is never blocked client-side.
    """
    return (value or "").strip()


def valid_barcode(value: str) -> bool:
    """Whether ``value`` is a non-empty barcode."""
    return bool(value)


def valid_postal_code(value: str) -> bool:
    """Whether ``value`` is a non-empty postal code."""
    return bool(value)


def _current_parcels(entry: ConfigEntry) -> list[dict[str, str]]:
    """Return a mutable copy of the tracked parcels list."""
    return [dict(item) for item in entry.options.get(CONF_PARCELS, [])]


def _clean_barcodes(values: list[str] | None) -> list[str]:
    """Normalise, drop blanks, and de-duplicate barcodes."""
    codes: list[str] = []
    for value in values or []:
        code = normalize_barcode(value)
        if code and code not in codes:
            codes.append(code)
    return codes


class BpostConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the UI-driven configuration flow for the bpost integration."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> BpostOptionsFlowHandler:
        """Return the options flow handler."""
        return BpostOptionsFlowHandler()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create a bpost hub — one per delivery postal code.

        bpost's public tracker requires both a barcode and a postal code per
        lookup, so the postal code becomes the hub default: multiple hubs
        are allowed (a household that also receives parcels addressed to a
        different postcode than its own creates a second hub for it), mirroring
        GLS's account-less, postcode-keyed model exactly. Setup does not hit
        the API — the endpoint needs a barcode too.
        """
        return self.async_show_menu(step_id="user", menu_options=[SOURCE_ACCOUNT, SOURCE_TRACKING])

    async def async_step_tracking(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the existing code-and-postcode tracking hub."""
        errors: dict[str, str] = {}

        if user_input is not None:
            postal_code = normalize_postal_code(user_input[CONF_POSTAL_CODE])
            if not valid_postal_code(postal_code):
                errors[CONF_POSTAL_CODE] = "invalid_postcode"
            else:
                await self.async_set_unique_id(postal_code)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"bpost ({postal_code})",
                    data={CONF_SOURCE: SOURCE_TRACKING},
                    options={
                        CONF_POSTAL_CODE: postal_code,
                        CONF_PARCELS: [],
                        CONF_DELIVERED_FILTER_TYPE: DEFAULT_DELIVERED_FILTER_TYPE,
                        CONF_DELIVERED_FILTER_AMOUNT: DEFAULT_DELIVERED_FILTER_AMOUNT,
                        CONF_INCLUDE_HISTORY: DEFAULT_INCLUDE_HISTORY,
                    },
                )

        return self.async_show_form(
            step_id=SOURCE_TRACKING,
            data_schema=vol.Schema({vol.Required(CONF_POSTAL_CODE): str}),
            errors=errors,
        )

    async def async_step_account(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Log in once and persist only the token pair, never the password."""
        errors: dict[str, str] = {}
        if user_input is not None:
            email = str(user_input[CONF_EMAIL]).strip().lower()
            password = str(user_input[CONF_PASSWORD])
            if not email or not password:
                errors["base"] = "invalid_auth"
            else:
                client = BpostAccountClient(async_get_clientsession(self.hass))
                try:
                    tokens = await client.async_login(email, password)
                except BpostAccountInvalidCredentials:
                    errors["base"] = "invalid_auth"
                except BpostAccountApiError:
                    errors["base"] = "cannot_connect"
                else:
                    await self.async_set_unique_id(f"account:{email}")
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=f"bpost ({email})",
                        data={CONF_SOURCE: SOURCE_ACCOUNT, CONF_EMAIL: email, **tokens},
                        options={
                            CONF_DELIVERED_FILTER_TYPE: DEFAULT_DELIVERED_FILTER_TYPE,
                            CONF_DELIVERED_FILTER_AMOUNT: DEFAULT_DELIVERED_FILTER_AMOUNT,
                            CONF_INCLUDE_HISTORY: DEFAULT_INCLUDE_HISTORY,
                        },
                    )
        return self.async_show_form(
            step_id=SOURCE_ACCOUNT,
            data_schema=vol.Schema({vol.Required(CONF_EMAIL): str, vol.Required(CONF_PASSWORD): str}),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Reauthenticate the fixed account; never silently change accounts."""
        self._reauth_entry = self._get_reauth_entry()
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Replace only the rotated tokens after a successful password login."""
        errors: dict[str, str] = {}
        entry = self._reauth_entry
        if user_input is not None:
            client = BpostAccountClient(async_get_clientsession(self.hass))
            try:
                tokens = await client.async_login(entry.data[CONF_EMAIL], user_input[CONF_PASSWORD])
            except BpostAccountInvalidCredentials:
                errors["base"] = "invalid_auth"
            except BpostAccountApiError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(entry.unique_id)
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(entry, data_updates=tokens)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
        )


class BpostOptionsFlowHandler(OptionsFlow):
    """Manage tracked parcels separately from integration settings.

    ``async_step_init`` shows a menu (``parcels`` / ``settings``) rather than
    one long sectioned form. The ``parcels`` page edits the whole tracked-code
    list at once; ``settings`` holds delivered-parcel retention, history and
    polling. Adding a parcel needs only its barcode — the postal code is
    inherited from the hub. No live API validation on add (format-only,
    matching the template): a barcode is only confirmed real on the next poll.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer parcel management separately from integration settings."""
        menu_options = ["settings"]
        if self.config_entry.data.get(CONF_SOURCE, SOURCE_TRACKING) == SOURCE_TRACKING:
            menu_options.insert(0, "parcels")
        return self.async_show_menu(step_id="init", menu_options=menu_options)

    async def async_step_parcels(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show and handle the complete tracked-code list."""
        errors: dict[str, str] = {}
        if user_input is not None:
            codes = _clean_barcodes(user_input.get("tracking_codes"))
            if any(not valid_barcode(code) for code in codes):
                errors["base"] = "invalid_tracking_code"
            else:
                return self.async_create_entry(
                    title="",
                    data={
                        **self.config_entry.options,
                        CONF_PARCELS: [{CONF_BARCODE: code} for code in codes],
                    },
                )
        current_codes = [
            parcel[CONF_BARCODE] for parcel in _current_parcels(self.config_entry)
        ]
        schema = vol.Schema(
            {
                vol.Optional("tracking_codes"): selector.TextSelector(
                    selector.TextSelectorConfig(multiple=True)
                )
            }
        )
        return self.async_show_form(
            step_id="parcels",
            data_schema=self.add_suggested_values_to_schema(
                schema, {"tracking_codes": current_codes}
            ),
            errors=errors,
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show and handle the non-parcel integration settings."""
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={
                    **self.config_entry.options,
                    CONF_DELIVERED_FILTER_TYPE: user_input[CONF_DELIVERED_FILTER_TYPE],
                    CONF_DELIVERED_FILTER_AMOUNT: int(
                        user_input[CONF_DELIVERED_FILTER_AMOUNT]
                    ),
                    CONF_INCLUDE_HISTORY: bool(user_input[CONF_INCLUDE_HISTORY]),
                },
            )
        current = self.config_entry.options
        schema: dict[Any, Any] = {
            vol.Required(
                CONF_DELIVERED_FILTER_TYPE,
                default=current.get(
                    CONF_DELIVERED_FILTER_TYPE, DEFAULT_DELIVERED_FILTER_TYPE
                ),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=["days", "parcels"],
                    translation_key=CONF_DELIVERED_FILTER_TYPE,
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
            vol.Required(
                CONF_DELIVERED_FILTER_AMOUNT,
                default=current.get(
                    CONF_DELIVERED_FILTER_AMOUNT, DEFAULT_DELIVERED_FILTER_AMOUNT
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=365, step=1, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Required(
                CONF_INCLUDE_HISTORY,
                default=current.get(CONF_INCLUDE_HISTORY, DEFAULT_INCLUDE_HISTORY),
            ): selector.BooleanSelector(),
        }
        return self.async_show_form(step_id="settings", data_schema=vol.Schema(schema))
