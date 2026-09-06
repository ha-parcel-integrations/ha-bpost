# Working in this repository

Home Assistant custom integration for **bpost** parcel tracking.
Distributed via HACS; not part of HA core. One carrier in the
[ha-parcel-integrations](https://github.com/ha-parcel-integrations) suite,
**generated from ha-carrier-template** — everything outside *Carrier-specific
notes* is suite-wide; when in doubt check the template or a sibling repo.
No DTO layer.

## Shared conventions — fetch when relevant

Suite-wide rules live in
[`.github/CONVENTIONS.md`](https://github.com/ha-parcel-integrations/.github/blob/main/CONVENTIONS.md)
and are **not** repeated here. Don't fetch it every session — fetch it **before**
you act in one of these areas:

| Before you … | Fetch `CONVENTIONS.md` § |
|---|---|
| touch entities, sensors, config/options flow, coordinator, diagnostics, translations | *Home Assistant developer docs* (its table points on to the canonical HA page — don't rely on memory) |
| add/rename a parcel field, a `ParcelStatus`, or a bus event; change the sort/first-refresh; touch unmapped-status logging | *Parcel contract* — exact key set, units, sort, events + suppression; `test_parcels.py::test_normalize_publishes_exactly_the_canonical_keys` guards the key set |
| change which optional field this carrier populates vs. always returns `None` | Update `const.py`'s `CAPABILITIES` in the same commit — it feeds the comparison table on the docs site, so a field that starts (or stops) coming back non-null and isn't reflected there is a wrong claim on the website, not just a stale comment. If this carrier has more than one backend (a country-specific transport, not just a config option) with genuinely different field support, `CAPABILITIES` should be a `CAPABILITIES_BY_VARIANT` dict instead — one frozenset per backend, so a field only some backends populate doesn't get silently intersected away or overclaimed for the rest |
| ship anything while below 1.0.0 (unconfirmed data) | *Pre-1.0 releases* — one-shot WARNINGs for every guessed shape/code |
| consider "fixing" a lint/pattern the skill flags (poll interval, inline client, sync requests) | *Deliberate skill divergences* — likely intentional, don't re-flag |
| commit, bump, tag, release, or write release notes; add a feature without a test | *Workflow / Commits / Versioning / Testing* |

**Suite-wide tripwires, kept inline on purpose:**
- **First refresh in `__init__.py`, before `async_forward_entry_setups`** — from
  a forwarded platform HA can't catch `ConfigEntryNotReady` and half-sets-up the
  entry. Runtime-only; tests don't catch a regression.
- **Setup stale-entity sweep is scoped to `domain == "sensor"` and skips
  `non_parcel_unique_ids`** — else it deletes the refresh button / the
  summary+diagnostic sensors. Add a new non-parcel sensor's unique_id to the set.
- **Per-parcel sensors are removed by the summary sensor** via
  `entity_registry.async_remove` (self-removal races and leaves ghosts).
- **If this carrier can reach `ParcelStatus.AT_PICKUP_POINT` from a real raw
  status/code**, it needs an `awaiting_pickup` sensor — see *Parcel contract*
  in `CONVENTIONS.md`. Say "pickup point", not "ServicePoint"/"parcel
  shop"/"locker", for the generic concept. `ha-dhl-nl`, `ha-dpd`, `ha-gls`,
  `ha-inpost` are reference implementations; `bpost` here does not
  demonstrate it yet.

## Carrier-specific notes

**API mechanics live in `carrier-research/bpost/api/` (private research
repo)** — the endpoint URLs, the full request/response envelope, the
`activeStep.name` vocabulary as evidenced so far, and the field-by-field
reconstruction this build was generated from. Do not duplicate them here;
this section is integration-level decisions only.

**`payload: reconstructed` — still true; two real bpost parcels (2026-09-03,
2026-09-06) confirmed part of the field map, not all of it.** Every lookup in
`parcels.py` was originally read off a third-party client's source, not off
this repo's own wire, so this shipped pre-1.0 (0.x) with the one-shot
WARNING net of `const.STATUS_MAP`/`parcels.py` active, matching the Correos
and DPD-DE precedent in this suite. **Confirmed so far:** the envelope
shape, `actualDeliveryTime`'s exact shape (date-only, no time component),
`delivered`/`delivered_at`, the `history`/`events[]` shape (newest-first,
each entry with no status code of its own), and `deliveryPoint: null` for a
home delivery (three samples, all home deliveries, all null) — no new
`activeStep.name` code beyond `delivered`/`out_for_delivery_byCar` has been
seen. **Still open, and no in-transit or pickup-point sample has been
available to close them:** the `expectedDeliveryTimeRange` shape
(`time1`/`time2` vs. `{date, startTime, endTime}` vs. a plain string —
`time1`/`time2` is implemented, the others degrade to `None` without
raising), and `deliveryPoint`'s actual (non-`null`) contents.
`parcels.py`'s `_warn_eta_first_sighting` and
`_warn_delivery_point_first_sighting` fire the moment a real parcel settles
either question — treat either warning firing as the trigger to re-open this
question, confirm the shape, and only then move `payload` to `confirmed` and
consider a `1.0.0`. Help-wanted issues are open on this repo for both gaps
(2026-09-06) rather than holding the gate open indefinitely; the private
`carrier-research/bpost/api/BUILD_PLAN.md` this section was folded from has
been deleted, per this suite's normal deleted-on-release rule.

**Domain collision with the HACS default store's `bpost` — accepted, not
resolved (decided 2026-09-02).**
`myTselectionPublic/homeassistant-bpost-integration` already ships HA domain
`bpost` in the HACS default store (`therealabradolf/ha-bpost-tracker` ships
`bpost_tracker`, no collision there). HA refuses to load two custom
components sharing one domain if a user has both installed — accepted as-is:
a user who hits it chooses which integration to keep. **Do not rename this
repo's domain to dodge the collision without a fresh maintainer decision** —
`manifest.json`'s `bpost` domain is deliberate, not a placeholder.

**Neither community source integration was approached before this repo was
built (decided 2026-09-02).** Both `therealabradolf/ha-bpost-tracker` and
`myTselectionPublic/homeassistant-bpost-integration` are MIT and were read as
sources for the field map; per a one-off maintainer decision this repo skipped
the courteous outreach step other adoptions in this suite have used. No
attribution beyond what the private research doc already records.

**Endpoint: three keyless routes on `track.bpost.cloud`, no headers at all.**
`GET /track/items?itemIdentifier=<barcode>&postalCode=<postal_code>` is the
route the coordinator polls (`api.async_get_item`). `api.async_get_parcel`
composes that with the optional `GET /track/itemonroundstatus` enrichment —
fetched only when the parcel is not yet delivered *and* carries an
`expectedDeliveryTimeRange`, mirroring the source client this route was
reconstructed from — and any failure on that second call is swallowed as "no
data", never raised. A barcode-only request (no postal code) was probed and
returned HTTP 400, so both fields stay required on every fetch — only *where*
the postal code value comes from changed (the hub default, not a per-parcel
input; see below). `track.bpost.cloud` has a different WAF posture from
`www.bpost.be`/`login.bpost.be` — do not add a browser fingerprint or
`curl_cffi` here; `manifest.json` keeps `"requirements": []` on purpose.

**Code model: account-less, postcode-keyed hubs, mirroring GLS exactly.**
bpost's public tracker requires both a barcode *and* a postal code per
lookup, so — like GLS — the postal code is asked once at setup and becomes
the hub's default (`entry.options[CONF_POSTAL_CODE]`); every parcel added
afterwards needs only its barcode. This replaced the original per-parcel
`{barcode, postal_code}` model (bpost 0.1.0–0.x), whose stated reason was "a
household can receive a parcel addressed to a different postcode than its
own" — the maintainer decided that flexibility is not worth diverging from
the suite's hub-per-postcode convention: a household needing a different
postcode now creates a second bpost hub for it, exactly as a GLS household
with two delivery addresses does.
- **Setup (`async_step_user`) asks only the postal code**, stored as the hub
  default; `CONF_PARCELS` starts empty. Setup does **not** hit the API (the
  endpoint needs a barcode too). Multiple hubs allowed, one per postcode —
  `unique_id = postal_code`, `_abort_if_unique_id_configured`. Device/entry
  title `f"bpost ({postal_code})"`. `single_config_entry` is deliberately
  **absent** from `manifest.json`.
- **Tracked parcels live in `entry.options[CONF_PARCELS]`** as `{barcode}`
  dicts — no live API validation on add (format-only, matching the
  template): a barcode is only confirmed real on the next poll. Added via the
  options flow's `parcels` step (whole-list multi-value text field, like
  GLS/the template), the `bpost.track_parcel` service, or a Lovelace button.
  The unique key for dedup is `parcels.parcel_key(barcode)` — the barcode
  alone, scoped within one hub; the same barcode tracked in two different
  hubs is not a duplicate, since each hub is a separate device.
- **Options menu is `parcels` / `settings`** (not `add_parcel` /
  `remove_parcel` / `settings`) — the template's whole-list pattern, not the
  old per-item add/remove steps.
- **The service field is `tracking_code`, not `barcode`** — the suite-standard
  name every carrier exposes (`CONF_TRACKING_CODE`), even though bpost's own
  vocabulary is "barcode" everywhere else. The *stored* options key stays
  `barcode` (`CONF_BARCODE`), exactly as GLS keeps `parcel_no` behind a
  `tracking_code` service field, so no entry migration is involved. Renamed in
  0.10.0; automations written against 0.9.0's `barcode:` field must be updated.
- **`bpost.track_parcel` keeps an optional `postal_code` field** (mirroring
  GLS's own service) purely to pick *which* hub when more than one is
  configured; `bpost.untrack_parcel` takes only `tracking_code` and removes it
  from whichever hub(s) track it. With exactly one hub, `postal_code` is never
  needed.
- **Services are shared across hubs** — `async_unload_entry` only calls
  `async_unload_services` once no other hub is still loaded (GLS's pattern).

**Status map: three known `activeStep.name` codes, matched exact → prefix →
`unknown`.** `parcels.STATUS_MAP` only has `delivered`,
`delivered_kariboo_point` and `out_for_delivery_byCar` — the vocabulary is
open and undocumented. An unseen code is matched by expanding every known
key into its leading `_`-segment prefixes once (`_build_prefix_table`), then
trying the unseen code's own decreasing-length prefixes against that table —
`out_for_delivery_byBike` resolves to `out_for_delivery` this way. A prefix
hit still logs its own one-shot WARNING (distinct wording from a pure
`unknown`), since a prefix match is a mitigation, not evidence.

**`delivered` is never derived from the status name.** It reads
`bool(actualDeliveryInformation.actualDeliveryTime)` — `activeStep.name`
varies by delivery method (`delivered` for a mailbox drop,
`delivered_kariboo_point` for a Kariboo pickup point), so the status name is
not a reliable delivered signal. This must survive any refactor;
`test_parcels.py::test_delivered_is_never_derived_from_the_status_name`
guards it with both a known pickup-point code and a wholly unseen delivered
method.

**`pickup`/`pickup_point` follow the same rule as every other suite
carrier — `pickup: status is ParcelStatus.AT_PICKUP_POINT`, never a delivery
*method*.** `delivered_kariboo_point` is a *method of an already-delivered*
parcel (`status` maps it to `DELIVERED`, same as a mailbox drop) — it is not
a still-awaiting-collection state, so it must not flip `pickup` to `True`.
No confirmed `activeStep.name` code reaches `AT_PICKUP_POINT` at all, so
`pickup` is always `False` today; `pickup_point` stays `None` unconditionally
regardless — `deliveryPoint`'s contents are unconfirmed and never read by
either source client, so `normalize_parcel` does not guess at them
(`parcels._warn_delivery_point_first_sighting` logs its first sighting
instead). This mirrors BoxNow Greece's `pickup`/`pickup_point` handling
exactly, for the same reason: a delivery-method code is not a pickup-pending
state, and an unconfirmed field is not populated from a guess.

**`raw` is the untouched payload, like every other suite carrier —
corrected 2026-09-06.** An earlier revision (through 0.10.0) copied through
only an allowlist of five fields, which meant a real diagnostics export
never actually carried the `expectedDeliveryTimeRange`/`deliveryPoint` shape
the §0.3 gate needs, defeating the point of asking a user for one. Two real
parcels (2026-09-06, both home deliveries) confirmed `deliveryPoint: null`
again but could not settle the ETA-window shape, either question — this
allowlist is exactly why: `raw` at the time only ever showed the five
curated keys, never the field that would have answered it. `normalize_parcel`
now returns `raw` verbatim.

**Diagnostics: `raw_status` and `description` are deliberately over-redacted.**
The canonical top-level `raw_status` field (`activeStep.name`, no PII) and
each `history[]` entry's own `raw_status` (a localised event *description*,
potentially PII) share the same key name, and `async_redact_data` redacts by
key, not by position — it cannot tell the two apart. `raw_status` is in
`diagnostics.TO_REDACT`, mirroring Ceska Posta's `id` over-redaction
precedent. Now that `raw` is verbatim, the same event-description text
reappears under different key names at
`raw["events"][i]["key"]["<LANG>"]["description"]` — `"description"` is in
`TO_REDACT` for exactly that. `raw["sender"]` (a nested dict, unlike the
canonical top-level `sender` string) is caught by the existing `"sender"`
key already in `TO_REDACT` — `async_redact_data` blanks it wholesale, no
separate entry needed. The one-shot WARNING log lines (not diagnostics)
remain the channel that carries `activeStep.name` in the clear for
status-map reports.

**No camera entity.** The delivery-photo route
(`GET /track/asset?refId=...`, base64-*text* body) is documented in the
plan but not implemented — nothing canonical depends on it, and it is more
than this first release needs. Add it later as a `camera` platform reading
`raw.safeplacePicture.refId` if there is demand; `refId` and the photo body
must never reach diagnostics or a log line.

**Do not build:** the mybpost app API (`mybpost.bpost.cloud/prod_v2/`,
requires a shared, revocable `x-api-key`); the mijn-bpost web-scrape surface
(SAML login, HTML scraping, `curl_cffi` browser impersonation); an
account/inbox model (this surface cannot discover parcels — manual barcode +
postal code entry is the intentional model, not a deficiency); barcode
enumeration or the bulk `POST /track/items {barcodes:[]}` form; broadcasting
a barcode to another carrier integration or a third-party tracking proxy;
deriving `delivered`, an ETA, a pickup point, weight, dimensions or a
receiver from a field that has not been observed in a real payload.

## Options and reloads

For code-based carriers, the options flow starts with exactly `Parcels` and
`Settings`. `Parcels` is one editable multi-code list; `Settings` is
a flat form. Changes apply without a restart. Two models, **do not mix them**:
- **Account-less carriers** (the default) apply changes live: an update listener
  calls `async_request_refresh()`, so added/removed parcel sensors appear
  immediately (this is also the resume path after polling has fully
  suspended — see "Dynamic polling" below).
- **Account-based carriers** call `async_schedule_reload` on submit and register
  **no** update listener. Combining a listener with a reload-on-update flow is
  deprecated, an error in HA 2026.12+.

## Dynamic polling

There is no user-facing polling interval — this is a deliberate suite-wide
choice, not a gap. `coordinator.py` recomputes `update_interval` at the end of
every refresh:

- **Quiet window:** no polling 00:00–06:00 local time, except two daily
  anchors (~00:00 and ~06:00) for overnight / end-of-day catch-up.
- **Tiers while polling:** *hot* (15 min) when a tracked, not-yet-delivered
  parcel is `out_for_delivery` within an hour of its `planned_from` (or has no
  `planned_from` at all); *mid* (45 min) for anything else still in flight —
  `problem`/`returning` included, deliberately not hot. Account-based carriers
  never fully stop even with nothing hot or in transit: the mid-tier poll is
  also how a new shipment gets discovered.
- **Full stop (account-less carriers only):** `update_interval = None` when
  nothing is tracked or every tracked parcel is delivered. Resumes the moment
  a parcel is added back, via the options-flow refresh above.
- **Stagger:** a small, stable per-install offset (hash of the config entry
  id) is added to every computed interval so installs don't all hit an anchor
  or tier boundary at the same second.
- **429 backoff:** a 429 anywhere in a poll raises `UpdateFailed` with
  `retry_after` — the carrier's own `Retry-After` header if present, otherwise
  an exponential backoff tracked per-coordinator. `api.py`'s
  `…ApiError.status_code` / `.retry_after` carry this from the HTTP layer.

A carrier that genuinely throttles or soft-bans traffic harder than the 429
backoff handles is a documented, local divergence from this in that one
repo's own `CLAUDE.md` — not a generator flag.

## Module layout

| File | Carrier-specific? |
|---|---|
| `api.py` (HTTP client, error types) | **yes** |
| `const.py` (domain, URLs, `ParcelStatus`, option keys) | partly (URLs) |
| `parcels.py` (status map, `normalize_parcel`, history, sort, filters — pure, no I/O) | partly (`_STATUS_MAP`, `normalize_parcel`) |
| `coordinator.py` (fetch, cache, event firing) | mostly not |
| `config_flow.py` | partly (code validation) |
| `sensor.py` / `button.py` / `calendar.py` / `device_trigger.py` | no |
| `diagnostics.py` | partly (`TO_REDACT`) |
| `services.py` (`track_parcel` / `untrack_parcel`, account-less only) | no |

`parcels.py` is deliberately free of I/O and HA objects so the per-carrier part
stays unit-testable without Home Assistant. Config: `ConfigEntry.runtime_data`
(typed, no `hass.data`), `PARALLEL_UPDATES = 0`, coordinator takes
`config_entry=entry`. `aiohttp.ClientError` is caught **per parcel** in the gather
loop (one bad parcel doesn't fail the poll) but **not** around the whole update
(the coordinator wraps that). Entities: `has_entity_name` + `translation_key`,
`icons.json`, translated units, `_attr_attribution`, `_unrecorded_attributes` on
anything with a parcel list or `raw`. Over-redact diagnostics — they get pasted
into public issues.

## Running tests

```
python -m pytest tests/ --cov=custom_components.bpost
```

Coverage must stay **above 95%** (silver `test-coverage` rule). Run before
committing. A code change updates the README + this file + `docs/` in the same
commit; the API reference lives in your own private research notes, never in
this repo.
