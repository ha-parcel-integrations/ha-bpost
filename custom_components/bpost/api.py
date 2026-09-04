"""bpost public tracking API client.

Three keyless, unauthenticated JSON routes on ``track.bpost.cloud``.
**No headers at all** — no ``Authorization``, no ``x-api-key``, no
cookie, no ``User-Agent`` override, no ``lang`` query parameter, no
``Referer``. ``track.bpost.cloud`` has a different WAF posture from
``www.bpost.be``/``login.bpost.be``, which do need a browser fingerprint —
that machinery does not belong on this client and must never be added here.
"""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import aiohttp

from .const import ITEM_ON_ROUND_STATUS_URL, TRACKING_API_URL

_LOGGER = logging.getLogger(__name__)


class BpostApiError(Exception):
    """Raised when the main bpost tracking call returns an unexpected response."""

    def __init__(
        self,
        detail: str,
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        """Store the status code and the ``Retry-After`` header, if any."""
        super().__init__(f"bpost API request failed: {detail}")
        self.detail = detail
        self.status_code = status_code
        self.retry_after = retry_after


def _quoted(value: str) -> str:
    """URL-encode a barcode/postal code for the query string."""
    return quote(value, safe="")


class BpostApiClient:
    """Client for the three keyless bpost tracking routes.

    ``async_get_parcel`` is the one method the coordinator and the config
    flow's live validation both call. It composes the main ``track/items``
    lookup with the optional ``track/itemonroundstatus`` enrichment, exactly
    as the source client this route was reconstructed from does: the
    enrichment is only fetched when the parcel is not yet delivered *and*
    carries an ``expectedDeliveryTimeRange`` — and any failure on that second
    call is swallowed as "no data", never raised.
    """

    def __init__(self, session: aiohttp.ClientSession) -> None:
        """Initialise the client with an aiohttp session."""
        self._session = session

    async def async_get_parcel(
        self, barcode: str, postal_code: str
    ) -> dict[str, Any] | None:
        """Fetch one parcel by barcode + postal code, with its bonus enrichment.

        Returns the ``items[0]`` object (plus a dearrayed ``itemOnRoundStatus``
        key when the enrichment fired and returned data), or ``None`` when
        bpost reports the pair as unknown — a top-level ``error`` key or an
        empty ``items`` list, never an HTTP error. Any other failure raises
        :class:`BpostApiError`; network errors propagate as
        ``aiohttp.ClientError``.
        """
        item = await self.async_get_item(barcode, postal_code)
        if item is None:
            return None

        delivered = bool(
            (item.get("actualDeliveryInformation") or {}).get("actualDeliveryTime")
        )
        if not delivered and item.get("expectedDeliveryTimeRange"):
            round_status = await self._async_get_item_on_round_status(
                barcode, postal_code
            )
            if round_status is not None:
                item = {**item, "itemOnRoundStatus": _dearray(round_status)}
        return item

    async def async_get_item(
        self, barcode: str, postal_code: str
    ) -> dict[str, Any] | None:
        """Fetch the bare ``track/items`` result — no enrichment.

        Used by the config/options flow's live validation, which validates by
        actually calling ``track/items`` and must not also trigger the
        round-status call.
        """
        url = TRACKING_API_URL.format(
            barcode=_quoted(barcode), postal_code=_quoted(postal_code)
        )
        async with self._session.get(url) as response:
            if response.status != 200:
                raise BpostApiError(
                    f"HTTP {response.status}", status_code=response.status
                )
            try:
                # content_type=None: consumer endpoints routinely serve JSON as
                # text/plain, and aiohttp would otherwise refuse to parse it.
                payload = await response.json(content_type=None)
            except ValueError as err:
                raise BpostApiError(f"unparseable body ({err})") from err

        if not isinstance(payload, dict):
            raise BpostApiError("unexpected body (not a JSON object)")

        if "error" in payload:
            return None
        items = payload.get("items")
        if not isinstance(items, list) or not items or not isinstance(items[0], dict):
            return None
        return items[0]

    async def _async_get_item_on_round_status(
        self, barcode: str, postal_code: str
    ) -> dict[str, Any] | None:
        """Fetch the bonus on-round enrichment; any failure means "no data".

        Any non-200 or error body is swallowed as "no data" and must never
        fail the refresh or mark the parcel unavailable. A network error is
        swallowed the same way — this call
        backs one bonus attribute set, never a canonical field.
        """
        url = ITEM_ON_ROUND_STATUS_URL.format(
            barcode=_quoted(barcode), postal_code=_quoted(postal_code)
        )
        try:
            async with self._session.get(url) as response:
                if response.status != 200:
                    return None
                payload = await response.json(content_type=None)
        except (aiohttp.ClientError, ValueError):
            return None
        if not isinstance(payload, dict) or "error" in payload:
            return None
        status = payload.get("itemOnRoundStatus")
        return status if isinstance(status, dict) else None


def _dearray(round_status: dict[str, Any]) -> dict[str, Any]:
    """Unwrap every 1-element-array value in an ``itemOnRoundStatus`` object.

    ``nrOfStopsUntilTarget``, ``progressUntilTarget``, ``lastKnownLocation``
    and ``targetLocation`` each arrive as a 1-element array — index ``[0]`` before use.
    """
    return {
        key: (value[0] if isinstance(value, list) and value else value)
        for key, value in round_status.items()
    }
