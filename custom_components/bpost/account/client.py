"""Minimal client for the My bpost account inbox.

The account API is deliberately isolated from the public tracking client: it
uses a user-owned token pair and a revocable app compatibility key.  Responses
are returned as raw dictionaries; normalisation belongs in ``parcels.py``.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp

from ..const import ACCOUNT_API_KEY, ACCOUNT_API_URL, ACCOUNT_APP_VERSION

TokenCallback = Callable[[dict[str, Any]], Awaitable[None]]


class BpostAccountApiError(Exception):
    """An unexpected account API response without sensitive response data."""

    def __init__(self, detail: str, *, status_code: int | None = None) -> None:
        """Store safe failure metadata without retaining the response body."""
        super().__init__(detail)
        self.status_code = status_code


class BpostAccountInvalidCredentials(BpostAccountApiError):
    """The supplied email/password was rejected."""


class BpostAccountReauthRequired(BpostAccountApiError):
    """Stored user tokens cannot be refreshed."""


class BpostAccountCompatibilityError(BpostAccountApiError):
    """The app key or accepted app version is no longer valid."""


def _tokens(payload: Any) -> dict[str, Any]:
    """Extract the only token fields persisted by the integration."""
    response = payload.get("response") if isinstance(payload, dict) else None
    if not isinstance(response, dict):
        raise BpostAccountApiError("missing login response")
    access_token = response.get("accessToken") or response.get("token")
    refresh_token = response.get("refreshToken")
    if not isinstance(access_token, str) or not isinstance(refresh_token, str):
        raise BpostAccountApiError("missing account tokens")
    return {"access_token": access_token, "refresh_token": refresh_token}


class BpostAccountClient:
    """My bpost account API client with raw-token authorisation."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        access_token: str | None = None,
        refresh_token: str | None = None,
        token_callback: TokenCallback | None = None,
    ) -> None:
        """Initialise the client with entry-owned tokens and persistence hook."""
        self._session = session
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._token_callback = token_callback

    def _headers(
        self, *, include_auth: bool = True, include_static: bool = True
    ) -> dict[str, str]:
        """Build endpoint-specific mobile API headers.

        The refresh endpoint is deliberately unauthenticated: bpost expects
        the refresh token in its JSON body, not an expired access token in an
        ``Authorization`` header. It also omits the app-version headers in the
        official client's request.
        """
        headers = {
            "x-api-key": ACCOUNT_API_KEY,
            "Content-Type": "application/json",
            "os": "android",
            "osVersion": "14",
        }
        if include_static:
            headers["appVersion"] = ACCOUNT_APP_VERSION
            headers["appLang"] = "en"
        if include_auth and self._access_token:
            # This API rejects a Bearer prefix: the raw token is required.
            headers["Authorization"] = self._access_token
        return headers

    async def _post(
        self,
        path: str,
        body: dict[str, Any],
        *,
        include_auth: bool = True,
        include_static: bool = True,
    ) -> Any:
        async with self._session.post(
            f"{ACCOUNT_API_URL}/{path}",
            json=body,
            headers=self._headers(
                include_auth=include_auth, include_static=include_static
            ),
        ) as response:
            if response.status in (401, 403):
                try:
                    error = await response.json(content_type=None)
                except ValueError:
                    error = None
                error_code = error.get("code") if isinstance(error, dict) else None
                if (
                    error_code == "APPVERSION_NOT_SUPPORTED"
                    and not include_auth
                ):
                    raise BpostAccountCompatibilityError(
                        "account API rejected app compatibility",
                        status_code=response.status,
                    )
                if path == "users/login":
                    raise BpostAccountInvalidCredentials("login rejected", status_code=response.status)
                raise BpostAccountReauthRequired(
                    "account token rejected", status_code=response.status
                )
            if response.status != 200:
                raise BpostAccountApiError("account API request failed", status_code=response.status)
            try:
                return await response.json(content_type=None)
            except ValueError as err:
                raise BpostAccountApiError("account API returned invalid JSON") from err

    async def async_login(self, email: str, password: str) -> dict[str, Any]:
        """Authenticate once; callers persist only the returned token pair."""
        tokens = _tokens(
            await self._post(
                "users/login",
                {"userName": email, "password": password, "appLang": "en", "mandatoryConsent": True, "optionalConsent": False},
                include_auth=False,
            )
        )
        self._access_token, self._refresh_token = tokens.values()
        return tokens

    async def async_refresh(self) -> dict[str, Any]:
        """Rotate the stored token pair once and notify the entry owner."""
        if not self._refresh_token:
            raise BpostAccountReauthRequired("no refresh token")
        tokens = _tokens(
            await self._post(
                "users/refreshtoken",
                {"refreshToken": self._refresh_token},
                include_auth=False,
                include_static=False,
            )
        )
        self._access_token, self._refresh_token = tokens.values()
        if self._token_callback:
            await self._token_callback(tokens)
        return tokens

    async def async_get_parcel_summaries(self) -> list[dict[str, Any]]:
        """Return inbox summaries; documented ``Err_1005`` is an empty inbox."""
        try:
            payload = await self._post("parcel/getparcelslist", {"appLang": "en"})
        except BpostAccountReauthRequired:
            # A token can expire between polls. Rotate once, then retry the
            # original read exactly once; a second rejection starts HA reauth.
            await self.async_refresh()
            payload = await self._post("parcel/getparcelslist", {"appLang": "en"})
        if not isinstance(payload, dict):
            raise BpostAccountApiError("unexpected parcel-list envelope")
        if payload.get("dbError") == "Err_1005":
            return []
        response = payload.get("response", payload)
        if not isinstance(response, dict):
            raise BpostAccountApiError("unexpected parcel-list response")
        items = response.get("items", [])
        if not isinstance(items, list):
            raise BpostAccountApiError("unexpected parcel-list items")
        summaries = [item for item in items if isinstance(item, dict) and item.get("itemCode")]
        if not summaries:
            return []
        detail_payload = await self._post("parcel/getparcelsv3", {"appLang": "en", "isFirstPageCall": True, "items": [{"itemCode": item["itemCode"], "Status": item.get("Status"), "LatestEventTimestamp": item.get("LatestEventTimestamp")} for item in summaries]})
        detail_response = detail_payload.get("response") if isinstance(detail_payload, dict) else None
        if not isinstance(detail_response, dict):
            raise BpostAccountApiError("unexpected parcel-detail response")
        active = detail_response.get("active", {})
        active_lists = active.values() if isinstance(active, dict) else ()
        entries = [item for group in active_lists if isinstance(group, list) for item in group if isinstance(item, dict)]
        history = detail_response.get("history", [])
        if isinstance(history, list):
            entries.extend(item for item in history if isinstance(item, dict))
        return entries
