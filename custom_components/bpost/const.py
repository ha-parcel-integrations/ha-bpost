"""Constants for the bpost parcel tracker integration."""
from enum import StrEnum

from homeassistant.const import Platform

DOMAIN = "bpost"


class ParcelStatus(StrEnum):
    """Carrier-agnostic parcel status.

    **Do not extend or rename these members.** Every integration in the parcel
    suite publishes exactly this vocabulary on the ``status`` field of each
    normalised parcel, so cross-carrier automations and the aggregator can
    target ``status: out_for_delivery`` regardless of carrier. Listed in
    roughly the order a parcel moves through.
    """

    REGISTERED = "registered"               # Sender announced the parcel; not handed over yet
    IN_TRANSIT = "in_transit"               # In the carrier's network
    OUT_FOR_DELIVERY = "out_for_delivery"   # On a delivery vehicle today
    AT_PICKUP_POINT = "at_pickup_point"     # Ready to collect at a pickup location
    DELIVERED = "delivered"                 # Handed over
    RETURNING = "returning"                 # Failed delivery, going back to sender
    PROBLEM = "problem"                     # Carrier reports an exception/issue
    UNKNOWN = "unknown"                     # Raw status we have not mapped yet


PLATFORMS = [Platform.BUTTON, Platform.CALENDAR, Platform.SENSOR]

# Every optional key the parcel contract defines. CAPABILITIES below must be a
# subset of this — it exists so a typo in CAPABILITIES fails a test instead of
# silently dropping a carrier off a table on the docs site.
KNOWN_CAPABILITIES = frozenset(
    {"weight", "dimensions", "delivery_window", "pickup_point", "url", "history"}
)

# bpost's public tracker: no weight/dimensions on this route, ever; pickup_point is deliberately never
# populated (deliveryPoint's contents are unconfirmed — see parcels.py); the
# ETA window and event history are implemented, and the deep link is always
# built (it needs no carrier data beyond the barcode/postcode the user
# supplied). Keep in sync with parcels.normalize_parcel().
CAPABILITIES = frozenset({"delivery_window", "url", "history"})

# Two keyless, unauthenticated JSON routes on track.bpost.cloud — no headers,
# no cookies, no key. Code model: both the barcode (bpost calls it
# itemIdentifier) and the postal code are required; a barcode-only request was
# probed and returned HTTP 400.
TRACKING_API_URL = (
    "https://track.bpost.cloud/track/items"
    "?itemIdentifier={barcode}&postalCode={postal_code}"
)
ITEM_ON_ROUND_STATUS_URL = (
    "https://track.bpost.cloud/track/itemonroundstatus"
    "?itemIdentifier={barcode}&postalCode={postal_code}"
)

# Human-facing deep link surfaced on each parcel's ``url`` field. ``{lang}``
# is resolved from hass.config.language, limited to nl/fr/en (see
# parcels.resolve_lang) — the only three the source client's label object
# ever carries.
TRACKING_URL = (
    "https://track.bpost.cloud/btr/web/#/search"
    "?lang={lang}&itemCode={barcode}&postalCode={postal_code}"
)

# Tracked parcels live in the config entry options as a list of ``{barcode}``
# dicts, scoped to one hub per postal code — the postal code is a hub-level
# default (``entry.options[CONF_POSTAL_CODE]``), set once at setup and used
# for every parcel added afterwards. Mirrors GLS's account-less,
# postcode-keyed hub model: a household needing a different postcode creates
# a second hub for it, rather than supplying a postcode per parcel.
CONF_PARCELS = "parcels"
CONF_BARCODE = "barcode"

# Standard service field name shared by every parcel-suite carrier. The
# stored options key above stays bpost's own vocabulary; only the public
# service surface is suite-standard, mirroring GLS.
CONF_TRACKING_CODE = "tracking_code"
CONF_POSTAL_CODE = "postal_code"

# Delivered-parcels retention: keep delivered parcels visible for the last N
# days, or keep only the N most recent — identical across the suite.
CONF_DELIVERED_FILTER_TYPE = "delivered_filter_type"
CONF_DELIVERED_FILTER_AMOUNT = "delivered_filter_amount"
DEFAULT_DELIVERED_FILTER_TYPE = "days"
DEFAULT_DELIVERED_FILTER_AMOUNT = 7

# Dynamic, status-driven polling — unconditional across the suite, no
# user-facing interval option (see scaffold/CLAUDE.md's "Dynamic polling"
# section for the full algorithm and the reasoning behind it). bpost's own
# rate limit is unmeasured (the 15-minute-while-active cadence a community
# client ships is a shipped datapoint, not a measured limit), so this stays
# at the suite defaults
# rather than a carrier-specific override.
#
# Quiet window: no polling between these local hours except the two anchors
# below, for overnight / end-of-day catch-up.
QUIET_WINDOW_START_HOUR = 0
QUIET_WINDOW_END_HOUR = 6

# Cadence while polling is active (minutes). Hot = at least one tracked,
# not-yet-delivered parcel is out_for_delivery within HOT_LOOKAHEAD_HOURS of
# its planned_from (or has no planned_from at all); mid = anything else still
# in flight (registered, in_transit, at_pickup_point, unknown, problem,
# returning).
HOT_INTERVAL_MINUTES = 15
MID_INTERVAL_MINUTES = 45
HOT_LOOKAHEAD_HOURS = 1

# Small, stable per-install offset added to every computed interval so
# different installs don't all hit an anchor or tier boundary at the same
# second. Deterministic (hash of the config entry id), not random.
STAGGER_MINUTES = 7

# Per-parcel status history is opt-in and off by default, identical across the
# suite. Keep it off by default even when — as here — the timeline arrives in
# the same response and costs no extra request: it is a large attribute, and on
# carriers that need a second call per parcel the cost is real.
CONF_INCLUDE_HISTORY = "include_history"
DEFAULT_INCLUDE_HISTORY = False

# Cap each parcel's history to the most recent N events so the attribute stays
# well under HA's ~16 KB state-attribute limit.
HISTORY_MAX_EVENTS = 20
