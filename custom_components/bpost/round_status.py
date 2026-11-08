"""Shared shape of bpost's on-round (live courier) enrichment.

Each source fetches it from its own endpoint, but bpost wraps every value in a
1-element array on both, so the unwrapping lives here instead of in either
source.
"""

from __future__ import annotations

from typing import Any

ROUND_STATUS_KEY = "itemOnRoundStatus"

# The round response carries its own ``status`` — the result of that lookup,
# not the parcel's. The parcel record already holds the real ``status``, which
# the account normaliser reads as a status fallback, so the lookup's copy is
# dropped instead of merged over it. Everything else bpost sends is kept.
DROPPED_KEYS = frozenset({"status"})


def dearray_round_status(round_status: dict[str, Any]) -> dict[str, Any]:
    """Unwrap every 1-element-array value in an ``itemOnRoundStatus`` object.

    ``nrOfStopsUntilTarget``, ``progressUntilTarget``,
    ``estimatedDeliveryTimeWindow``, ``lastKnownLocation`` and
    ``targetLocation`` each arrive as a 1-element array — index ``[0]`` before
    use.
    """
    return {
        key: (value[0] if isinstance(value, list) and value else value)
        for key, value in round_status.items()
    }


def round_status_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the round response ready to merge into a parcel's ``raw``.

    Everything bpost answered with is kept, not only the fields this
    integration happens to read, so a user's diagnostics export carries the
    whole response.
    """
    return {
        key: (
            dearray_round_status(value)
            if key == ROUND_STATUS_KEY and isinstance(value, dict)
            else value
        )
        for key, value in payload.items()
        if key not in DROPPED_KEYS
    }
