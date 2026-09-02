# Examples

Ready-to-paste Home Assistant snippets for the bpost integration.

| Folder | Contents |
|---|---|
| [`automations/`](automations/) | YAML automations — copy them into your `automations.yaml` or paste them into the Automation editor in **raw editor** mode. |
| [`dashboards/`](dashboards/) | Lovelace snippets, including [`add_parcel_card.yaml`](dashboards/add_parcel_card.yaml) — track a new parcel straight from a dashboard via the `bpost.track_parcel` service. |

All examples assume a single bpost hub. Adjust entity IDs to match yours.

**Feeding bpost from e-mail:** bpost is code-based — every parcel must be registered by its barcode before it can be tracked (the hub already knows the delivery postal code). [`automations/track_parcels_from_email.yaml`](automations/track_parcels_from_email.yaml) extracts barcodes from incoming shipping mails (core IMAP integration + regex, with an optional AI fallback) and registers them automatically; setup guide and pitfalls in [`automations/track_parcels_from_email.md`](automations/track_parcels_from_email.md).

## Services

| Service | Description |
|---|---|
| `bpost.track_parcel` | Start tracking a parcel (`barcode`, optional `postal_code` to pick a hub when more than one is set up). |
| `bpost.untrack_parcel` | Stop tracking a parcel (`barcode`). |

## Events used in the examples

The coordinator fires these on the HA event bus:

| Event | When | Payload |
|---|---|---|
| `bpost_parcel_registered` | A new parcel appears in the active list | The full normalised parcel dict |
| `bpost_parcel_status_changed` | A parcel's canonical status changes | Same, plus `old_status` / `new_status` |
| `bpost_parcel_delivered` | A parcel reaches the delivered status | Same, plus `old_status` / `new_status` (fires *instead of* `status_changed` on that final hop) |
| `bpost_parcel_delivery_time_changed` | A parcel's expected delivery time changes | Same, plus `old_planned_from` / `new_planned_from` / `old_planned_to` / `new_planned_to` |

Events are suppressed on the first refresh after start-up.
