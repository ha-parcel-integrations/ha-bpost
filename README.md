# bpost Parcel Tracker

[![Release](https://img.shields.io/github/v/release/ha-parcel-integrations/ha-bpost.svg)](https://github.com/ha-parcel-integrations/ha-bpost/releases)
[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> 💬 Questions or feedback? Join the discussion on the [Home Assistant community](https://community.home-assistant.io/t/packages-postnl-dhl-nl-dpd-and-gls-parcel-integration/112433/).

A custom Home Assistant integration that tracks your [bpost](https://track.bpost.cloud/btr/web/#/search) (Belgium) parcels. No account is needed — set up a hub with your delivery postal code, then add parcels by barcode, just like on the bpost track-and-trace website.

> **Pre-1.0 release.** This integration's field map was reconstructed from
> third-party open-source clients, not confirmed against a real bpost parcel
> yet. It ships anyway, with a one-shot warning for anything unrecognised —
> see [Troubleshooting](#troubleshooting). `1.0.0` will follow once a real
> parcel confirms the shape.

Part of the [ha-parcel-integrations](https://github.com/ha-parcel-integrations) family: it publishes the same canonical parcel format, statuses and events as the other carrier integrations, so it plugs straight into the [Parcel Aggregator](https://github.com/ha-parcel-integrations/ha-parcel-aggregator) and cross-carrier automations.

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

- Track any number of bpost parcels by barcode — no account needed, one hub per delivery postal code
- Per-parcel sensor with the canonical status (`out_for_delivery` / `delivered` / `unknown` / …), the carrier's own status text, the expected delivery window (when bpost reports one) and a tracking deep-link
- Summary sensors: incoming parcels, next delivery, recently delivered parcels
- Read-only **Deliveries** calendar with the expected delivery windows
- `bpost.track_parcel` / `bpost.untrack_parcel` services, so a dashboard button can add a parcel
- Events + device triggers for no-code automations (parcel registered, status changed, delivered, delivery time changed)
- Opt-in per-parcel status history
- Manual refresh button and a diagnostic last-update sensor

## Requirements

- Home Assistant 2024.12 or newer
- The delivery postal code (asked once, at setup)
- A bpost parcel's barcode (from the shipping confirmation e-mail or the
  missed-delivery card) — bpost's public tracker requires both a barcode
  and a postal code to look up a parcel, no account needed

## Installation

### HACS (recommended)

1. In HACS, choose the three-dot menu → **Custom repositories**.
2. Add `https://github.com/ha-parcel-integrations/ha-bpost` as an **Integration**.
3. Install **bpost** and restart Home Assistant.

### Manual

Copy `custom_components/bpost` into your `config/custom_components/` folder and restart Home Assistant.

## Configuration

Add the integration via **Settings → Devices & Services → Add Integration → bpost** and enter the postal code your parcels are delivered to. This becomes the hub's default for every parcel you add to it — a household that also receives parcels addressed to a different postcode adds a second bpost hub for that postcode.

Then add parcels via the integration's **Configure** dialog, the [`bpost.track_parcel`](#services) service, or a [dashboard button](examples/dashboards/add_parcel_card.yaml) — just the barcode; the postal code comes from the hub.

## Options

Open **Configure** on the integration entry:

| Menu item | Description |
|---|---|
| Parcels | Edit the full list of tracked barcodes at once (add or remove any number, then save). No live validation — a barcode is confirmed on the next poll. |
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
| `sensor.bpost_delivered_parcels` | Recently delivered parcels (see the retention option) |
| `sensor.bpost_last_successful_update` | Diagnostic: when bpost was last polled successfully |

A delivered parcel moves from its per-parcel sensor to the delivered sensor automatically.

## Parcel status reference

The `status` field is the carrier-agnostic enum shared by the whole integration family. Only three bpost status codes are confirmed today — the vocabulary is open and undocumented, and this integration reports anything else as `unknown` with a one-shot log warning asking you to [report it](https://github.com/ha-parcel-integrations/ha-bpost/issues/new):

| Status | Meaning |
|---|---|
| `out_for_delivery` | With the courier today |
| `delivered` | Delivered — including to a Kariboo pickup point, which is a delivery *method*, not a still-waiting state |
| `unknown` | Not yet found, or a status code we have not mapped yet |

The other canonical statuses (`registered`, `in_transit`, `at_pickup_point`, `returning`, `problem`) exist in the shared enum but no bpost code is currently known to reach them.

The carrier's own status code is always available as `raw_status`.

## Events

The integration fires these on the event bus (also available as device triggers on the bpost device):

| Event | When |
|---|---|
| `bpost_parcel_registered` | A new parcel appears in the active list |
| `bpost_parcel_status_changed` | A parcel's canonical status changes (`old_status` / `new_status` in the payload), except the final hop to delivered |
| `bpost_parcel_delivered` | A parcel is delivered |
| `bpost_parcel_delivery_time_changed` | The expected delivery window changes |

Every payload is the full normalised parcel plus the hub's `device_id`. Events are suppressed on the first refresh after start-up.

## Services

| Service | Fields | Description |
|---|---|---|
| `bpost.track_parcel` | `barcode`, `postal_code` (optional, to pick a hub when more than one is set up) | Start tracking a parcel |
| `bpost.untrack_parcel` | `barcode` | Stop tracking a parcel |

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

- **A parcel shows `unknown`** — either bpost has no record for that barcode + the hub's postal code yet (it will pick up automatically once scanned), or its status code is not one of the three currently mapped.
- **A log line says "Unrecognised bpost activeStep code"** — please [open an issue](https://github.com/ha-parcel-integrations/ha-bpost/issues/new?template=unrecognised_status.yml) with the logged line so the mapping can be extended.
- **A parcel never resolves** — double-check the barcode, and that the hub's postal code matches the delivery address; bpost's public tracker requires an exact match on both. A parcel addressed to a different postcode needs its own hub.

## Related integrations

This integration is part of [**ha-parcel-integrations**](https://github.com/ha-parcel-integrations) — a family of
parcel-carrier integrations that all publish the same canonical parcel format,
statuses and events.

- [**Parcel Aggregator**](https://github.com/ha-parcel-integrations/ha-parcel-aggregator) rolls every installed carrier
  up into one set of sensors.
- Browse [the organisation](https://github.com/ha-parcel-integrations) for the current list of supported carriers.

## Disclaimer

This integration uses the same public tracking endpoint as the bpost consumer website. It is not affiliated with, endorsed by, or supported by bpost.

## Contributing

Pull requests and issues are welcome. Please open an issue before
submitting a large change.

## License

[MIT](LICENSE)
