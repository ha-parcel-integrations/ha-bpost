"""Tests for the account client's empty-inbox boundary."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.bpost.account.client import (
    BpostAccountApiError,
    BpostAccountClient,
    BpostAccountCompatibilityError,
    BpostAccountInvalidCredentials,
    BpostAccountReauthRequired,
)


class _Response:
    def __init__(self, status=200, payload=None, invalid_json=False):
        self.status = status
        self._payload = payload
        self._invalid_json = invalid_json

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def json(self, **kwargs):
        if self._invalid_json:
            raise ValueError
        return self._payload


def _client(response):
    session = MagicMock()
    session.post.return_value = response
    return BpostAccountClient(session), session


async def test_empty_account_database_error_is_an_empty_inbox():
    client = BpostAccountClient(AsyncMock())
    client._post = AsyncMock(return_value={"dbError": "Err_1005"})
    assert await client.async_get_parcel_summaries() == []


async def test_summary_lists_are_combined():
    client = BpostAccountClient(AsyncMock())
    client._post = AsyncMock(side_effect=[
        {"response": {"items": [{"itemCode": "A", "Status": "ACTIVE"}]}},
        {"response": {"active": {"incoming": [{"itemCode": "A"}]}, "history": [{"itemCode": "B"}]}},
    ])
    assert await client.async_get_parcel_summaries() == [{"itemCode": "A"}, {"itemCode": "B"}]


async def test_login_keeps_only_rotatable_tokens():
    client = BpostAccountClient(AsyncMock())
    client._post = AsyncMock(return_value={"response": {"accessToken": "access", "refreshToken": "refresh"}})
    assert await client.async_login("a@example.test", "password") == {"access_token": "access", "refresh_token": "refresh"}
    assert client._access_token == "access"


async def test_refresh_persists_rotated_tokens():
    callback = AsyncMock()
    client = BpostAccountClient(AsyncMock(), refresh_token="old", token_callback=callback)
    client._post = AsyncMock(return_value={"response": {"token": "access", "refreshToken": "new"}})
    assert await client.async_refresh() == {"access_token": "access", "refresh_token": "new"}
    callback.assert_awaited_once_with({"access_token": "access", "refresh_token": "new"})


async def test_refresh_without_token_requires_reauth():
    with pytest.raises(BpostAccountReauthRequired):
        await BpostAccountClient(AsyncMock()).async_refresh()


async def test_inbox_retries_once_after_refresh():
    client = BpostAccountClient(AsyncMock())
    client.async_refresh = AsyncMock()
    client._post = AsyncMock(side_effect=[
        BpostAccountReauthRequired("expired"),
        {"dbError": "Err_1005"},
    ])
    assert await client.async_get_parcel_summaries() == []
    client.async_refresh.assert_awaited_once()


async def test_post_maps_login_auth_and_compatibility_failures():
    client, _ = _client(_Response(401))
    with pytest.raises(BpostAccountInvalidCredentials):
        await client._post("users/login", {}, include_auth=False)
    client, _ = _client(_Response(403, {"code": "invalid_token"}))
    with pytest.raises(BpostAccountReauthRequired):
        await client._post("parcel/getparcelslist", {})
    client, _ = _client(_Response(403, {"code": "APPVERSION_NOT_SUPPORTED"}))
    with pytest.raises(BpostAccountCompatibilityError):
        await client._post("users/refreshtoken", {}, include_auth=False)
    client, _ = _client(_Response(401))
    with pytest.raises(BpostAccountReauthRequired):
        await client._post("parcel/getparcelslist", {})


async def test_refresh_does_not_send_an_expired_access_token_or_static_headers():
    client, session = _client(_Response(200, {"response": {"accessToken": "new", "refreshToken": "next"}}))
    client._access_token = "expired"
    client._refresh_token = "old-refresh"

    await client.async_refresh()

    headers = session.post.call_args.kwargs["headers"]
    assert "Authorization" not in headers
    assert "appVersion" not in headers
    assert "appLang" not in headers


async def test_post_handles_http_and_invalid_json():
    client, _ = _client(_Response(500))
    with pytest.raises(BpostAccountApiError):
        await client._post("parcel/getparcelslist", {})
    client, _ = _client(_Response(invalid_json=True))
    with pytest.raises(BpostAccountApiError):
        await client._post("parcel/getparcelslist", {})


async def test_summary_rejects_unknown_envelopes():
    client = BpostAccountClient(AsyncMock())
    client._post = AsyncMock(return_value=[])
    with pytest.raises(BpostAccountApiError):
        await client.async_get_parcel_summaries()
    client._post = AsyncMock(return_value={"response": "wrong"})
    with pytest.raises(BpostAccountApiError):
        await client.async_get_parcel_summaries()
