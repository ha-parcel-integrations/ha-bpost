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

**Structure, options flow, dynamic polling and module layout are suite-wide**
and identical in every carrier — the authoritative spec is
[`ha-carrier-template/scaffold/CLAUDE.md`](https://github.com/ha-parcel-integrations/ha-carrier-template/blob/main/scaffold/CLAUDE.md).
This repo follows it exactly.

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
  `ha-inpost` are reference implementations; bpost reaches it on the account
  route (the `AVAILABLE_*` family) but never on the public tracker.

## Carrier-specific notes

**API mechanics live in `carrier-research/bpost/api/` (private research
repo)** — the endpoint URLs, the full request/response envelope, the
status vocabulary, and the field-by-field
reconstruction this build was generated from. Do not duplicate them here;
this section is integration-level decisions only.

**`payload: reconstructed` — narrowing, not closed.** The field map began as a
reconstruction rather than a reading of this repo's own wire, so this ships
pre-1.0 (0.x) with the one-shot WARNING net in `tracking/parcels.py` active,
matching the Correos and DPD-DE precedent in this suite. Which fields are
confirmed, which assumptions were corrected and what is still open is the
research doc's job — the **gate** is what belongs here: `payload` moves to
`confirmed` and `1.0.0` becomes possible once the `expectedDeliveryTimeRange`
shape or `deliveryPoint`'s non-`null` contents is settled by a real parcel.
`_warn_eta_first_sighting` and `_warn_delivery_point_first_sighting` fire the
moment one of them is, and help-wanted issues
[#2](https://github.com/ha-parcel-integrations/ha-bpost/issues/2) and
[#3](https://github.com/ha-parcel-integrations/ha-bpost/issues/3) hold the
question open publicly rather than blocking the release.
deleted-on-release rule.

**Domain collision with the HACS default store's `bpost` — accepted, not
resolved (decided 2026-09-02).**
Another community integration in the HACS default store already ships HA
domain `bpost`. HA refuses to load two custom
components sharing one domain if a user has both installed — accepted as-is:
a user who hits it chooses which integration to keep. **Do not rename this
repo's domain to dodge the collision without a fresh maintainer decision** —
`manifest.json`'s `bpost` domain is deliberate, not a placeholder.

**Two sources in one domain — `tracking/` and `account/` subpackages.** bpost
is the suite's second carrier (after USPS) to serve two genuinely different
backends from one domain: the keyless public tracker, and the My bpost
account inbox that discovers parcels by itself. Each owns its client,
coordinator and normaliser under `custom_components/bpost/<source>/`;
`api.py`, `coordinator.py` and `parcels.py` at package root are
re-export shims kept so existing imports and test paths still resolve. The
tests mirror the split (`tests/tracking/`, `tests/account/`); the
source-agnostic platforms (`sensor`, `calendar`, `button`) keep their tests
at the top level.
- **One status vocabulary, in `status.py`.** Both routes report bpost's own
  codes — the account route as `currentStatus`, the tracker as
  `activeStep.knownProcessStep` — so the map lives one level up and neither
  source can drift from it. The tracker's `activeStep.name` is the same
  vocabulary with the case flattened, matched case-insensitively against it.
  What is *not* merged is normalisation: there is no generic
  `normalize_parcel`, each source shapes its own payload, and both carry their
  own one-shot WARNING net.
- **What *is* shared lives one level up.** `events.py` holds the HA-bus
  contract (both the incoming set and the sender-only outgoing pair) so the
  two coordinators cannot drift apart on it; `measurements.py` holds the
  gram/centimetre conversions, since bpost names its units in the field names
  and both routes return them; `tracking/parcels.py`'s `apply_delivered_filter`
  / `resolve_lang` / `sort_parcels_by_ts` are generic list helpers both sources
  call. Nothing else crosses the boundary.
- **`CAPABILITIES_BY_VARIANT`, not `CAPABILITIES`** — both routes report weight
  and dimensions, so the two variants are identical today; keep the dict, it
  makes a future divergence a one-line change. `CAPABILITIES` stays aliased to
  `Tracking` for the docs-site table.

**An entry's source is `entry.data[CONF_SOURCE]` (`tracking` / `account`).**
The setup flow opens on a menu picking one. A pre-0.11.0 entry has no `data`
at all, so **every** read must default to `SOURCE_TRACKING` — that default is
the migration, and there is no entry version bump. Deviation worth knowing:
the build plan specified deriving the source from `access_token` presence via
one `is_account_entry()` helper; the explicit key was chosen instead, so the
cost is that the check is open-coded at each dispatch site (`__init__.py`,
`sensor.py`, `services.py`, `config_flow.py`) — keep the default on every new
one.

**An account entry has no tracked-parcel list, and therefore no parcel
management.** Its options menu is `settings` only (no `parcels` step), and
`bpost.track_parcel` / `bpost.untrack_parcel` only ever see tracking hubs —
including the single-hub shortcut, which counts tracking entries so an
account entry can never silently absorb a parcel. An account-only setup
registers no services at all, and the shared services are removed when the
last *tracking* hub unloads, not the last entry.

**Account credentials: tokens are stored, the password never is.** Login
exchanges email + password for a rotating access/refresh token pair written
back to `entry.data`; the client refreshes on its own and calls back to
persist the new pair. A rejected refresh raises into HA's reauth flow, which
re-asks only the password and keeps the entry's unique id
(`account:<lowercased email>`, so the same mailbox cannot be added twice in
different casing). A rejected API key or app version is a *compatibility*
failure, deliberately not a reauth prompt — asking every user to log in again
would not fix it. The transport constants in `const.py`
(`ACCOUNT_API_KEY`, `ACCOUNT_APP_VERSION`) are shared app material, not user
secrets, and must never reach the UI, diagnostics or a log line; `email` and
both tokens are in `diagnostics.TO_REDACT`.

**Account parcels are both incoming and outgoing.** `userType` decides;
anything unrecognised counts as incoming so a new value can never make
parcels disappear. Incoming parcels fire the full canonical event set,
outgoing only `_outgoing_parcel_status_changed` / `_outgoing_parcel_delivered`
— a parcel you sent yourself is not news when it first appears, and its ETA
is the recipient's business. Account polling never suspends: the inbox is one
batched call, so there is no per-parcel fetch to skip and `delivered_codes`
stays empty by design.

**Two account status-mapping decisions (2026-09-19).** The vocabulary itself
lives in the research doc — what matters here is how it lands on canonical
statuses:
- **`AVAILABLE_*` is the `AT_PICKUP_POINT` set**, which makes that status
  reachable for the first time in this repo, so the `awaiting_pickup` sensor
  now has a real trigger. `pickup_point` still stays `None` — the status proves
  a parcel is waiting somewhere, not where.
- **A return leg in flight is `RETURNING`; a return leg that arrived is
  `DELIVERED`.** The `BTS_*`/`RETOUR_*` families report direction rather than
  their own phase while the parcel is moving — for a household dashboard the
  useful fact is that it is going back — but `DELIVERED_TO_SENDER`,
  `BTS_DELIVERED`, `RETOUR_DELIVERED`, `DELIVERED_TO_SENDER_RETURN` and
  `PICKED_UP_BY_SENDER` are terminal: the parcel never moves again, and the
  contract has no "returned" terminal, so leaving them `RETURNING` would park
  them in the active bucket forever. bpost's own app derives the same split.
  `raw_status` still names the leg, so an automation can tell them apart.

The map is **complete** — an unmapped code arriving means bpost extended its
vocabulary, which is what the one-shot WARNING is for. Never add a code that
is not in the documented vocabulary.

**Transport tripwire: `track.bpost.cloud` takes no headers at all and
`manifest.json` keeps `"requirements": []`.** Its WAF posture differs from
`www.bpost.be`/`login.bpost.be` — do not add a browser fingerprint or
`curl_cffi` to this route. Routes, parameters and the enrichment call's
fetch condition: research doc.

**Code model: postcode-keyed hubs, mirroring GLS exactly.** The postal code is
asked once at setup and becomes the hub's default
(`entry.options[CONF_POSTAL_CODE]`); every parcel added afterwards needs only
its barcode. This replaced a per-parcel `{barcode, postal_code}` model
(0.1.0–0.x) whose reason was that a household can receive a parcel addressed
to another postcode — the maintainer chose not to diverge from the suite's
hub-per-postcode convention: that household adds a second hub, as a GLS one
does. **The postcode is not a lookup requirement** (a barcode-only request
returns 200); it is bpost's PII gate — without it `sender`, `receiver` and
`isGDPRCompliant` are withheld. The hub model therefore stands on the canonical
fields it unlocks, not on the endpoint rejecting the request.
- **Setup asks only the postal code** and does **not** hit the API.
  `unique_id = postal_code`, `_abort_if_unique_id_configured`, entry title
  `f"bpost ({postal_code})"`, `CONF_PARCELS` starts empty. Multiple hubs are
  allowed, so `single_config_entry` is deliberately **absent** from
  `manifest.json`.
- **Dedup key is `parcel_key(barcode)`, scoped to one hub** — the same barcode
  in two hubs is not a duplicate, because each hub is its own device.
- **The user-facing word is "tracking code", not "barcode"** — service field,
  labels and the `invalid_tracking_code` error, as the other carriers word it,
  even though bpost says "barcode" everywhere else. The *stored* key stays
  `CONF_BARCODE`, as does the `barcode` contract field and the
  `sensor.bpost_parcel_<barcode>` entity id, so no entry migration is
  involved. The service field was renamed in 0.10.0 — automations written
  against 0.9.0's `barcode:` must be updated.
- **`bpost.track_parcel`'s optional `postal_code` only picks which hub** when
  more than one exists; `untrack_parcel` removes the code from whichever
  hub(s) hold it. Services are shared across hubs, so `async_unload_entry`
  only unregisters them once the last tracking hub is gone.
**Status map: `knownProcessStep` → name → prefix → `unknown`, and a prefix hit
is not evidence.** `map_parcel_status` tries bpost's own code first, then the
case-flattened `activeStep.name`, then that name's `_`-segment family prefix
(`_build_prefix_table`), each fallback logging its own one-shot WARNING —
worded differently from a pure `unknown`, because a family match is a
mitigation. A `knownProcessStep` outside the vocabulary warns even when the
name beside it still resolves: that means bpost added a code. Codes and
vocabulary: research doc.

**`delivered` is never derived from the status name.** It reads
`bool(actualDeliveryInformation.actualDeliveryTime)` — `activeStep.name`
varies by delivery method (`delivered` for a mailbox drop,
`delivered_kariboo_point` for a Kariboo pickup point), so the status name is
not a reliable delivered signal. This must survive any refactor;
`test_parcels.py::test_delivered_is_never_derived_from_the_status_name`
guards it with both a known pickup-point code and a wholly unseen delivered
method.

**`pickup` is a state, never a delivery *method*** —
`pickup: status is ParcelStatus.AT_PICKUP_POINT`, as everywhere in the suite.
`delivered_kariboo_point` is a method of an *already-delivered* parcel, so it
maps to `DELIVERED` and must not flip `pickup`. `pickup_point` stays `None`
unconditionally on both routes: `deliveryPoint` has never been seen populated,
and an unconfirmed field is not populated from a guess (BoxNow Greece set this
precedent). `_warn_delivery_point_first_sighting` logs its first sighting.

**`raw` is the untouched payload — corrected 2026-09-06.** Through 0.10.0 it
was an allowlist of five curated keys, so a user's diagnostics export could
never carry the very ETA/`deliveryPoint` shape the pre-1.0 gate asks them for.
Keep it verbatim.

**Diagnostics: `raw_status` and `description` are deliberately over-redacted.**
The canonical top-level `raw_status` field (bpost's own status code, no PII) and
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

**No camera entity.** The delivery-photo route exists but is not implemented —
nothing canonical depends on it. If demand appears, add a `camera` platform
reading `raw.safeplacePicture.refId`; `refId` and the photo body must never
reach diagnostics or a log line.

**Do not build:** the mijn-bpost web-scrape surface
(SAML login, HTML scraping, `curl_cffi` browser impersonation); barcode
enumeration or the bulk `POST /track/items {barcodes:[]}` form; broadcasting
a barcode to another carrier integration or a third-party tracking proxy;
deriving `delivered`, an ETA or a pickup point from a field that has not been
observed in a real payload.

## Running tests

```
python -m pytest tests/ --cov=custom_components.bpost
```

Coverage must stay **above 95%** (silver `test-coverage` rule). Run before
committing. A code change updates the README + this file + `docs/` in the same
commit; the API reference lives in your own private research notes, never in
this repo.
