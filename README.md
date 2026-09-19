# bpost Parcel Tracker

[![Release](https://img.shields.io/github/v/release/ha-parcel-integrations/ha-bpost.svg)](https://github.com/ha-parcel-integrations/ha-bpost/releases)
[![Downloads](https://img.shields.io/github/downloads/ha-parcel-integrations/ha-bpost/total.svg)](https://github.com/ha-parcel-integrations/ha-bpost/releases)
[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> 💬 Questions or feedback? Join the discussion on the [Home Assistant community](https://community.home-assistant.io/t/packages-postnl-dhl-nl-dpd-and-gls-parcel-integration/112433/).

A custom Home Assistant integration that tracks your [bpost](https://track.bpost.cloud/btr/web/#/search) (Belgium) parcels. Choose either tracking codes with a delivery postal code, or your My bpost account inbox.

Part of the [ha-parcel-integrations](https://ha-parcel-integrations.github.io/) family: it publishes the same canonical parcel format, statuses and events as the other carrier integrations, so it plugs straight into the [Parcel Aggregator](https://github.com/ha-parcel-integrations/ha-parcel-aggregator) and cross-carrier automations.

## Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Options](#options)
- [Removal](#removal)
- [Sensors](#sensors)
- [Parcel status reference](#parcel-status-reference)
- [Events](#events)
- [Services](#services)
- [Examples](#examples)
- [Debugging](#debugging)
- [Troubleshooting](#troubleshooting)
- [Related integrations](#related-integrations)
- [Disclaimer](#disclaimer)
- [Contributing](#contributing)
- [License](#license)

## Features

- Track any number of bpost parcels by tracking code — no account needed, one hub per delivery postal code
- My bpost account inbox: sign in once and every parcel in it is imported and kept up to date, incoming and outgoing; only rotating tokens are stored, never your password
- Per-parcel sensor with the canonical status (`out_for_delivery` / `delivered` / `unknown` / …), the carrier's own status text, the expected delivery window (when bpost reports one) and a tracking deep-link
- Summary sensors: incoming parcels, next delivery, recently delivered parcels,
  plus outgoing and delivered-outgoing parcels for account entries
- Read-only **Deliveries** calendar with the expected delivery windows
- `bpost.track_parcel` / `bpost.untrack_parcel` services, so a dashboard button can add a parcel
- Events + device triggers for no-code automations, including outgoing status
  changes and delivery for account entries
- Opt-in per-parcel status history
- Manual refresh button and a diagnostic last-update sensor

## Requirements

- Home Assistant 2024.12 or newer
- For tracking codes: the delivery postal code (asked once, at setup) and a
  parcel's tracking code (from the shipping confirmation e-mail or the
  missed-delivery card) — bpost's public tracker requires both to look up a
  parcel, no account needed
- For the account route: the e-mail address and password of your My bpost
  account. Home Assistant asks you to sign in again if bpost stops accepting
  the stored tokens.

## Installation

### HACS (recommended)

1. In HACS, choose the three-dot menu → **Custom repositories**.
2. Add `https://github.com/ha-parcel-integrations/ha-bpost` as an **Integration**.
3. Install **bpost** and restart Home Assistant.

### Manual

Copy `custom_components/bpost` into your `config/custom_components/` folder and restart Home Assistant.

## Configuration

Add the integration via **Settings → Devices & Services → Add Integration → bpost**, then choose **Tracking codes** or **Account (automatic import)**. Both kinds can be set up side by side.

**Tracking codes** ask for the delivery postal code, which becomes the hub default for every parcel you add to it. Add parcels via the integration's **Configure** dialog, the [`bpost.track_parcel`](#services) service, or a [dashboard button](examples/dashboards/add_parcel_card.yaml) — just the tracking code; the postal code comes from the hub.

**Account (automatic import)** asks for your My bpost e-mail address and password once, then keeps its parcel list in step with your inbox — nothing to add by hand. Only the rotating tokens bpost hands back are stored; your password is not.

## Options

Open **Configure** on the integration entry:

| Menu item | Description |
|---|---|
| Parcels | Edit the full list of tracked codes at once (add or remove any number, then save). No live validation — a tracking code is confirmed on the next poll. Tracking-code entries only; an account entry has no list to edit. |
| Settings | Delivered-parcel retention (filter by / amount) and the opt-in status-history attribute. |

Changes apply immediately, no restart.

Polling isn't one of these settings: the integration polls on a dynamic,
status-driven schedule (quiet overnight window, faster when a parcel is out
for delivery, stopped entirely once nothing is left to track) with nothing to
configure. See [CLAUDE.md](CLAUDE.md) for the details.

## Removal

Standard HA removal applies: **Settings → Devices & Services → bpost → ⋮ → Delete**. Nothing is stored on bpost's side.

## Sensors

| Entity | Description |
|---|---|
| `sensor.bpost_incoming_parcels` | Number of active tracked parcels, full list under the `parcels` attribute |
| `sensor.bpost_parcel_<barcode>` | One per tracked parcel; state is the canonical status, attributes carry the full normalised parcel |
| `sensor.bpost_next_delivery` | Earliest expected delivery moment across all active parcels |
| `sensor.bpost_awaiting_pickup` | Incoming parcels that are ready to collect at a pickup point |
| `sensor.bpost_delivered_parcels` | Recently delivered parcels (see the retention option) |
| `sensor.bpost_outgoing_parcels` | Active sender parcels; account entries only |
| `sensor.bpost_outgoing_delivered_parcels` | Recently delivered sender parcels; account entries only |
| `sensor.bpost_last_successful_update` | Diagnostic: when bpost was last polled successfully |

A delivered parcel moves from its per-parcel sensor to the delivered sensor automatically.

## Parcel status reference

The `status` field is the carrier-agnostic enum shared by the whole integration family. Both the public tracker and the account inbox report the same bpost status vocabulary, and it is mapped in full — preparation, transit, out-for-delivery, ready-to-collect, delivered, return and customs states. An unseen delivery method is still matched on its family prefix, and any code that stays unmapped is reported as `unknown` with a one-shot log warning asking you to [report it](https://github.com/ha-parcel-integrations/ha-bpost/issues/new):

| Status | Meaning |
|---|---|
| `registered`, `in_transit`, `out_for_delivery` | Announced, moving through the network, or with the courier today |
| `at_pickup_point`, `returning`, `problem` | Ready to collect, returning to sender, or a delivery exception |
| `delivered` | Delivered — including to a Kariboo pickup point, which is a delivery *method*, not a still-waiting state |
| `unknown` | Not yet found, or a status code we have not mapped yet |

The carrier's own status code is always available as `raw_status`.

## Events

The integration fires these on the event bus (also available as device triggers on the bpost device):

| Event | When |
|---|---|
| `bpost_parcel_registered` | A new parcel appears in the active list |
| `bpost_parcel_status_changed` | A parcel's canonical status changes (`old_status` / `new_status` in the payload), except the final hop to delivered |
| `bpost_parcel_delivered` | A parcel is delivered |
| `bpost_parcel_delivery_time_changed` | The expected delivery window changes |
| `bpost_outgoing_parcel_status_changed` | An account sender parcel's canonical status changes (`old_status` / `new_status`) |
| `bpost_outgoing_parcel_delivered` | An account sender parcel is delivered or returned to its sender |

Every payload is the full normalised parcel plus the hub's `device_id`. Events are suppressed on the first refresh after start-up.

## Services

| Service | Fields | Description |
|---|---|---|
| `bpost.track_parcel` | `tracking_code`, `postal_code` (optional, to pick a hub when more than one is set up) | Start tracking a parcel |
| `bpost.untrack_parcel` | `tracking_code` | Stop tracking a parcel |

Both act on tracking-code entries; account entries follow your My bpost inbox and are never edited by hand.

## Examples

Ready-to-paste automations and dashboard snippets live in [`examples/`](examples/), including tracking a new parcel straight from a dashboard.

### Community Lovelace cards

Third-party cards that work with this integration's sensors:

- [jonisnet/hki-parcels-card](https://github.com/jonisnet/hki-parcels-card)
- [klaptafel/ha-package-tracker-card](https://github.com/klaptafel/ha-package-tracker-card)

## Debugging

```yaml
logger:
  logs:
    custom_components.bpost: debug
```

## Troubleshooting

- **A parcel shows `unknown`** — either bpost has no record for that tracking code + the hub's postal code yet (it will pick up automatically once scanned), or bpost is reporting a status code that is not in the mapped vocabulary yet — the log says which one.
- **A log line says "Unrecognised bpost … status"** — please [open an issue](https://github.com/ha-parcel-integrations/ha-bpost/issues/new?template=unrecognised_status.yml) with the logged line so the mapping can be extended.
- **"bpost needs reauthentication"** — bpost stopped accepting the stored
  tokens for an account entry. Open the repair Home Assistant offers and enter
  that account's password again; nothing else is lost.
- **A parcel never resolves** — double-check the tracking code, and that the hub's postal code matches the delivery address; bpost's public tracker requires an exact match on both. A parcel addressed to a different postcode needs its own hub.

## Related integrations

This integration is part of [**ha-parcel-integrations**](https://ha-parcel-integrations.github.io/) — a family of
parcel-carrier integrations that all publish the same canonical parcel format,
statuses and events.

- [**Parcel Aggregator**](https://github.com/ha-parcel-integrations/ha-parcel-aggregator) rolls every installed carrier
  up into one set of sensors.
- Browse [the organisation](https://ha-parcel-integrations.github.io/) for the current list of supported carriers.

## Disclaimer

This integration uses the same public tracking endpoint as the bpost consumer website. It is not affiliated with, endorsed by, or supported by bpost.

## Contributing

Pull requests and issues are welcome. Please open an issue before
submitting a large change.

## License

[MIT](LICENSE)
