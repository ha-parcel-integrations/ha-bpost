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
    client._post = AsyncMock(
        side_effect=[
            {"response": {"items": [{"itemCode": "A", "Status": "ACTIVE"}]}},
            {
                "response": {
                    "active": {"incoming": [{"itemCode": "A"}]},
                    "history": [{"itemCode": "B"}],
                }
            },
        ]
    )
    assert await client.async_get_parcel_summaries() == [
        {"itemCode": "A"},
        {"itemCode": "B"},
    ]


async def test_listed_parcels_without_details_warn_once(caplog):
    client = BpostAccountClient(AsyncMock())
    listing = {"response": {"items": [{"itemCode": "A", "Status": "ACTIVE"}]}}
    empty = {"response": {"active": {"incoming": []}, "history": []}}
    client._post = AsyncMock(side_effect=[listing, empty, listing, empty])
    assert await client.async_get_parcel_summaries() == []
    assert await client.async_get_parcel_summaries() == []
    warnings = [r for r in caplog.records if "returned no details" in r.message]
    assert len(warnings) == 1


@pytest.mark.parametrize(
    ("listed", "batches"),
    [(1, [1]), (20, [20]), (21, [20, 1]), (29, [20, 9]), (41, [20, 20, 1])],
)
async def test_parcel_details_are_requested_in_batches(listed, batches):
    codes = [f"CODE{index}" for index in range(listed)]

    async def post(path, body):
        if path == "parcel/getparcelslist":
            return {"response": {"items": [{"itemCode": code} for code in codes]}}
        return {
            "response": {
                "active": {
                    "incoming": [{"itemCode": i["itemCode"]} for i in body["items"]]
                }
            }
        }

    client = BpostAccountClient(AsyncMock())
    client._post = AsyncMock(side_effect=post)

    entries = await client.async_get_parcel_summaries()

    assert [entry["itemCode"] for entry in entries] == codes
    detail_bodies = [call.args[1] for call in client._post.call_args_list[1:]]
    assert [len(body["items"]) for body in detail_bodies] == batches
    assert [body["isFirstPageCall"] for body in detail_bodies] == [
        index == 0 for index in range(len(batches))
    ]


async def test_a_batch_with_details_suppresses_the_empty_warning(caplog):
    client = BpostAccountClient(AsyncMock())
    client._post = AsyncMock(
        side_effect=[
            {"response": {"items": [{"itemCode": f"C{i}"} for i in range(21)]}},
            {"response": {"active": {}, "history": []}},
            {"response": {"active": {"incoming": [{"itemCode": "C20"}]}}},
        ]
    )
    assert await client.async_get_parcel_summaries() == [{"itemCode": "C20"}]
    assert "returned no details" not in caplog.text


async def test_login_keeps_only_rotatable_tokens():
    client = BpostAccountClient(AsyncMock())
    client._post = AsyncMock(
        return_value={"response": {"accessToken": "access", "refreshToken": "refresh"}}
    )
    assert await client.async_login("a@example.test", "password") == {
        "access_token": "access",
        "refresh_token": "refresh",
    }
    assert client._access_token == "access"


async def test_refresh_persists_rotated_tokens():
    callback = AsyncMock()
    client = BpostAccountClient(
        AsyncMock(), refresh_token="old", token_callback=callback
    )
    client._post = AsyncMock(
        return_value={"response": {"token": "access", "refreshToken": "new"}}
    )
    assert await client.async_refresh() == {
        "access_token": "access",
        "refresh_token": "new",
    }
    callback.assert_awaited_once_with(
        {"access_token": "access", "refresh_token": "new"}
    )


async def test_refresh_without_token_requires_reauth():
    with pytest.raises(BpostAccountReauthRequired):
        await BpostAccountClient(AsyncMock()).async_refresh()


async def test_inbox_retries_once_after_refresh():
    client = BpostAccountClient(AsyncMock())
    client.async_refresh = AsyncMock()
    client._post = AsyncMock(
        side_effect=[
            BpostAccountReauthRequired("expired"),
            {"dbError": "Err_1005"},
        ]
    )
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
    client, session = _client(
        _Response(200, {"response": {"accessToken": "new", "refreshToken": "next"}})
    )
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
    client._post = AsyncMock(
        return_value={"status": "success", "response": {"images": {"2026-10-03": []}}}
    )
    assert await client.async_get_letters("2026-09-04", "2026-10-03") == {
        "2026-10-03": []
    }
    client._post.assert_awaited_once_with(
        "mmt/retrieveImages",
        {"appLang": "en", "fromDate": "2026-09-04", "toDate": "2026-10-03"},
    )


async def test_letters_without_images_are_empty():
    client = BpostAccountClient(AsyncMock())
    client._post = AsyncMock(return_value={"response": {}})
    assert await client.async_get_letters("a", "b") == {}


@pytest.mark.parametrize(
    "payload", [{"response": None}, {"response": {"images": []}}, []]
)
async def test_letters_reject_unexpected_shapes(payload):
    client = BpostAccountClient(AsyncMock())
    client._post = AsyncMock(return_value=payload)
    with pytest.raises(BpostAccountApiError):
        await client.async_get_letters("a", "b")


async def test_letters_retry_once_after_refresh():
    client = BpostAccountClient(AsyncMock())
    client.async_refresh = AsyncMock()
    client._post = AsyncMock(
        side_effect=[
            BpostAccountReauthRequired("expired"),
            {"response": {"images": {}}},
        ]
    )
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
    assert await client.async_get_letter_image("https://images.example.test/a.jpg") == (
        b"jpeg",
        "image/jpeg",
    )
    session.get.assert_called_once_with("https://images.example.test/a.jpg")


async def test_letter_image_failure_raises():
    session = MagicMock()
    session.get.return_value = _ImageResponse(403)
    with pytest.raises(BpostAccountApiError):
        await BpostAccountClient(session).async_get_letter_image(
            "https://images.example.test/a.jpg"
        )


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
        (
            [{"response": {"items": [{"itemCode": "A"}]}}, {"response": None}],
            BpostAccountApiError,
        ),
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


def _on_round_inbox(detail, chunk):
    """Return a ``_post`` side effect for one parcel plus its round lookup."""

    async def post(path, body):
        if path == "parcel/getparcelslist":
            return {"response": {"items": [{"itemCode": "ROUND"}]}}
        if path == "parcel/getparcelsv3":
            return {"response": {"active": {"incoming": [detail]}}}
        assert path == "parcel/getparcelchunks"
        return chunk

    return post


_ON_ROUND_DETAIL = {
    "itemCode": "ROUND",
    "currentStatus": "ON_THE_WAY_TO_YOU",
    "viewsVisibility": ["KIZ_PARCEL_SHOW_MAP", "KIZ_PARCEL_ON_ROUND_STOPS"],
    "receiver": {"postcode": "1000"},
}

_ON_ROUND_CHUNK = {
    "response": {
        "type": "LOCATION_INFO",
        "data": {
            "status": "OK",
            "autoRefreshTimeInSeconds": "60",
            "itemOnRoundStatus": {
                "nrOfStopsUntilTarget": ["3"],
                "progressUntilTarget": ["80"],
                "estimatedDeliveryTimeWindow": ["10:20 - 13:35"],
                "lastKnownLocation": [{"latitude": 50.8, "longitude": 4.3}],
                "targetLocation": [{"latitude": 50.9, "longitude": 4.4}],
            },
        },
    }
}


async def test_round_status_is_merged_dearrayed_into_the_parcel_detail():
    client = BpostAccountClient(AsyncMock())
    client._post = AsyncMock(
        side_effect=_on_round_inbox(dict(_ON_ROUND_DETAIL), _ON_ROUND_CHUNK)
    )

    entries = await client.async_get_parcel_summaries()

    assert entries[0]["itemOnRoundStatus"] == {
        "nrOfStopsUntilTarget": "3",
        "progressUntilTarget": "80",
        "estimatedDeliveryTimeWindow": "10:20 - 13:35",
        "lastKnownLocation": {"latitude": 50.8, "longitude": 4.3},
        "targetLocation": {"latitude": 50.9, "longitude": 4.4},
    }
    # raw is everything bpost sent, except the lookup's own status: the
    # parcel record's real status must survive the merge.
    assert entries[0]["autoRefreshTimeInSeconds"] == "60"
    assert entries[0]["currentStatus"] == "ON_THE_WAY_TO_YOU"
    assert "status" not in entries[0]
    chunk_body = client._post.call_args_list[-1].args[1]
    assert chunk_body == {
        "appLang": "en",
        "itemCode": "ROUND",
        "data": {"postalCode": "1000"},
        "type": "LOCATION_INFO",
    }


@pytest.mark.parametrize(
    "detail",
    [
        {"itemCode": "ROUND", "receiver": {"postcode": "1000"}},
        {
            "itemCode": "ROUND",
            "viewsVisibility": ["KIZ_PARCEL_ON_ROUND_STOPS"],
            "receiver": {"postcode": "1000"},
        },
        {
            "itemCode": "ROUND",
            "viewsVisibility": ["KIZ_PARCEL_SHOW_MAP"],
            "receiver": {},
        },
        {
            "itemCode": "ROUND",
            "viewsVisibility": ["KIZ_PARCEL_SHOW_MAP"],
            "receiver": {"postcode": "1000"},
            "actualDeliveryTime": {"day": "2026-11-08", "time": "11:02"},
        },
    ],
    ids=["no-visibility", "map-not-allowed", "no-postcode", "delivered"],
)
async def test_round_status_is_not_requested_without_bpost_s_own_condition(detail):
    client = BpostAccountClient(AsyncMock())
    client._post = AsyncMock(side_effect=_on_round_inbox(detail, _ON_ROUND_CHUNK))

    entries = await client.async_get_parcel_summaries()

    assert "itemOnRoundStatus" not in entries[0]
    assert [call.args[0] for call in client._post.call_args_list] == [
        "parcel/getparcelslist",
        "parcel/getparcelsv3",
    ]


async def test_round_status_accepts_the_stringified_visibility_shape():
    detail = dict(_ON_ROUND_DETAIL, viewsVisibility="[KIZ_PARCEL_SHOW_MAP]")
    client = BpostAccountClient(AsyncMock())
    client._post = AsyncMock(side_effect=_on_round_inbox(detail, _ON_ROUND_CHUNK))

    entries = await client.async_get_parcel_summaries()

    assert entries[0]["itemOnRoundStatus"]["nrOfStopsUntilTarget"] == "3"


@pytest.mark.parametrize(
    "chunk",
    [
        BpostAccountReauthRequired("token rejected"),
        BpostAccountApiError("round lookup failed"),
        {"response": {"type": "LOCATION_INFO", "data": None}},
        {"response": None},
        None,
    ],
    ids=["reauth", "api-error", "no-data", "no-response", "no-envelope"],
)
async def test_a_failed_round_lookup_never_breaks_the_refresh(chunk):
    detail = dict(_ON_ROUND_DETAIL)

    async def post(path, body):
        if path == "parcel/getparcelslist":
            return {"response": {"items": [{"itemCode": "ROUND"}]}}
        if path == "parcel/getparcelsv3":
            return {"response": {"active": {"incoming": [detail]}}}
        if isinstance(chunk, Exception):
            raise chunk
        return chunk

    client = BpostAccountClient(AsyncMock())
    client._post = AsyncMock(side_effect=post)

    entries = await client.async_get_parcel_summaries()

    assert entries == [detail]
    assert "itemOnRoundStatus" not in entries[0]


async def test_the_round_lookup_never_overwrites_the_parcel_s_own_status():
    detail = dict(_ON_ROUND_DETAIL, status="PENDING")
    chunk = {"response": {"data": {"status": "OK", "itemOnRoundStatus": {}}}}
    client = BpostAccountClient(AsyncMock())
    client._post = AsyncMock(side_effect=_on_round_inbox(detail, chunk))

    entries = await client.async_get_parcel_summaries()

    assert entries[0]["status"] == "PENDING"
