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


async def test_letters_return_the_date_keyed_map_for_the_requested_window():
    client = BpostAccountClient(AsyncMock())
    client._post = AsyncMock(return_value={"status": "success", "response": {"images": {"2026-10-03": []}}})
    assert await client.async_get_letters("2026-09-04", "2026-10-03") == {"2026-10-03": []}
    client._post.assert_awaited_once_with(
        "mmt/retrieveImages", {"appLang": "en", "fromDate": "2026-09-04", "toDate": "2026-10-03"}
    )


async def test_letters_without_images_are_empty():
    client = BpostAccountClient(AsyncMock())
    client._post = AsyncMock(return_value={"response": {}})
    assert await client.async_get_letters("a", "b") == {}


@pytest.mark.parametrize("payload", [{"response": None}, {"response": {"images": []}}, []])
async def test_letters_reject_unexpected_shapes(payload):
    client = BpostAccountClient(AsyncMock())
    client._post = AsyncMock(return_value=payload)
    with pytest.raises(BpostAccountApiError):
        await client.async_get_letters("a", "b")


async def test_letters_retry_once_after_refresh():
    client = BpostAccountClient(AsyncMock())
    client.async_refresh = AsyncMock()
    client._post = AsyncMock(side_effect=[BpostAccountReauthRequired("expired"), {"response": {"images": {}}}])
    assert await client.async_get_letters("a", "b") == {}
    client.async_refresh.assert_awaited_once()


class _ImageResponse:
    def __init__(self, status, body=b"jpeg", content_type="image/jpeg"):
        self.status = status
        self._body = body
        self.content_type = content_type

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def read(self):
        return self._body


async def test_letter_image_is_fetched_without_any_header():
    session = MagicMock()
    session.get.return_value = _ImageResponse(200)
    client = BpostAccountClient(session, access_token="secret")
    assert await client.async_get_letter_image("https://images.example.test/a.jpg") == (b"jpeg", "image/jpeg")
    session.get.assert_called_once_with("https://images.example.test/a.jpg")


async def test_letter_image_failure_raises():
    session = MagicMock()
    session.get.return_value = _ImageResponse(403)
    with pytest.raises(BpostAccountApiError):
        await BpostAccountClient(session).async_get_letter_image("https://images.example.test/a.jpg")


@pytest.mark.parametrize("payload", [{}, {"response": {"accessToken": "a"}}])
async def test_login_without_a_token_pair_is_an_api_error(payload):
    client = BpostAccountClient(AsyncMock())
    client._post = AsyncMock(return_value=payload)
    with pytest.raises(BpostAccountApiError):
        await client.async_login("a@example.test", "password")


async def test_rejection_with_an_unreadable_body_still_requires_reauth():
    client, _ = _client(_Response(401, invalid_json=True))
    with pytest.raises(BpostAccountReauthRequired):
        await client._post("parcel/getparcelslist", {})


@pytest.mark.parametrize(
    ("responses", "expected"),
    [
        ([{"response": {"items": [{"Status": "ACTIVE"}]}}], []),
        ([{"response": {"items": "nope"}}], BpostAccountApiError),
        ([{"response": {"items": [{"itemCode": "A"}]}}, {"response": None}], BpostAccountApiError),
    ],
)
async def test_inbox_shapes_without_usable_items(responses, expected):
    client = BpostAccountClient(AsyncMock())
    client._post = AsyncMock(side_effect=responses)
    if expected == []:
        assert await client.async_get_parcel_summaries() == []
    else:
        with pytest.raises(expected):
            await client.async_get_parcel_summaries()
