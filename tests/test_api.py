"""Tests for the bpost API client."""
import json
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.bpost.api import BpostApiClient, BpostApiError

from .payloads import BARCODE, POSTAL_CODE, active_item, delivered_item, item


def _session_returning(*bodies: tuple[int, object]) -> MagicMock:
    """Return a session whose ``get()`` yields one response per call, in order."""
    responses = []
    for status, body in bodies:
        response = AsyncMock()
        response.status = status
        if isinstance(body, str):
            response.json = AsyncMock(side_effect=json.JSONDecodeError("x", body, 0))
        else:
            response.json = AsyncMock(return_value=body)
        responses.append(response)

    contexts = []
    for response in responses:
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=response)
        ctx.__aexit__ = AsyncMock(return_value=False)
        contexts.append(ctx)

    session = MagicMock()
    session.get = MagicMock(side_effect=contexts)
    return session


def _single(status: int, body: object) -> MagicMock:
    return _session_returning((status, body))


# ---------------------------------------------------------------------------
# no headers at all — the whole keyless claim
# ---------------------------------------------------------------------------


async def test_get_item_sends_no_headers_no_cookies():
    session = _single(200, {"items": [item()]})
    client = BpostApiClient(session)

    await client.async_get_item(BARCODE, POSTAL_CODE)

    call = session.get.call_args
    assert call.kwargs == {} or not any(
        key in call.kwargs for key in ("headers", "cookies", "auth")
    )
    assert BARCODE in call.args[0]
    assert POSTAL_CODE in call.args[0]


# ---------------------------------------------------------------------------
# async_get_item — the bare track/items lookup
# ---------------------------------------------------------------------------


async def test_get_item_returns_items_zero_on_success():
    parcel = item()
    session = _single(200, {"items": [parcel]})
    client = BpostApiClient(session)

    result = await client.async_get_item(BARCODE, POSTAL_CODE)

    assert result == parcel


async def test_get_item_returns_none_on_error_envelope():
    client = BpostApiClient(_single(200, {"error": "NO_DATA_FOUND"}))
    assert await client.async_get_item(BARCODE, POSTAL_CODE) is None


async def test_get_item_returns_none_on_empty_items():
    client = BpostApiClient(_single(200, {"items": []}))
    assert await client.async_get_item(BARCODE, POSTAL_CODE) is None


async def test_get_item_raises_on_400():
    """A barcode-only request (no postal code) was probed and returned HTTP 400."""
    client = BpostApiClient(_single(400, {}))
    with pytest.raises(BpostApiError):
        await client.async_get_item(BARCODE, POSTAL_CODE)


async def test_get_item_raises_on_non_json_body():
    client = BpostApiClient(_single(200, "not json"))
    with pytest.raises(BpostApiError):
        await client.async_get_item(BARCODE, POSTAL_CODE)


async def test_get_item_raises_on_non_object_body():
    client = BpostApiClient(_single(200, ["not", "a", "dict"]))
    with pytest.raises(BpostApiError):
        await client.async_get_item(BARCODE, POSTAL_CODE)


async def test_get_item_raises_on_items_not_a_list():
    client = BpostApiClient(_single(200, {"items": "oops"}))
    assert await client.async_get_item(BARCODE, POSTAL_CODE) is None


async def test_get_item_propagates_network_error():
    session = MagicMock()
    session.get = MagicMock(side_effect=aiohttp.ClientError("boom"))
    client = BpostApiClient(session)
    with pytest.raises(aiohttp.ClientError):
        await client.async_get_item(BARCODE, POSTAL_CODE)


# ---------------------------------------------------------------------------
# async_get_parcel — composes track/items with the optional round-status call
# ---------------------------------------------------------------------------


async def test_get_parcel_skips_round_status_when_delivered():
    parcel = delivered_item()
    session = _single(200, {"items": [parcel]})
    client = BpostApiClient(session)

    result = await client.async_get_parcel(BARCODE, POSTAL_CODE)

    assert result == parcel
    assert session.get.call_count == 1  # no second (round-status) call


async def test_get_parcel_skips_round_status_without_eta():
    parcel = item(eta=None)
    session = _single(200, {"items": [parcel]})
    client = BpostApiClient(session)

    await client.async_get_parcel(BARCODE, POSTAL_CODE)

    assert session.get.call_count == 1


async def test_get_parcel_fetches_round_status_when_active_with_eta():
    parcel = active_item()
    round_status = {
        "itemOnRoundStatus": {
            "nrOfStopsUntilTarget": [3],
            "progressUntilTarget": [0.5],
            "lastKnownLocation": [{"lat": 50.8, "long": 4.3}],
            "targetLocation": [{"lat": 50.9, "long": 4.4}],
        }
    }
    session = _session_returning((200, {"items": [parcel]}), (200, round_status))
    client = BpostApiClient(session)

    result = await client.async_get_parcel(BARCODE, POSTAL_CODE)

    assert session.get.call_count == 2
    assert result["itemOnRoundStatus"] == {
        "nrOfStopsUntilTarget": 3,
        "progressUntilTarget": 0.5,
        "lastKnownLocation": {"lat": 50.8, "long": 4.3},
        "targetLocation": {"lat": 50.9, "long": 4.4},
    }


async def test_get_parcel_returns_none_when_item_not_found():
    session = _single(200, {"error": "NO_DATA_FOUND"})
    client = BpostApiClient(session)
    assert await client.async_get_parcel(BARCODE, POSTAL_CODE) is None


@pytest.mark.parametrize(
    "second_response",
    [
        (404, {}),
        (200, {"error": "No round status info can be rendered"}),
        (200, None),
        (200, "not json"),
    ],
)
async def test_round_status_failure_never_fails_the_refresh(second_response):
    """Any non-200/error/unparseable round-status body is "no data", not a failure."""
    parcel = active_item()
    session = _session_returning((200, {"items": [parcel]}), second_response)
    client = BpostApiClient(session)

    result = await client.async_get_parcel(BARCODE, POSTAL_CODE)

    assert result is not None
    assert "itemOnRoundStatus" not in result


async def test_round_status_network_error_is_swallowed():
    parcel = active_item()
    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(return_value={"items": [parcel]})
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=response)
    ctx.__aexit__ = AsyncMock(return_value=False)

    session = MagicMock()
    session.get = MagicMock(side_effect=[ctx, aiohttp.ClientError("boom")])
    client = BpostApiClient(session)

    result = await client.async_get_parcel(BARCODE, POSTAL_CODE)
    assert "itemOnRoundStatus" not in result
