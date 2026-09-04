"""Sample bpost ``track/items`` payloads shared by the test modules.

Every shape below is read off a third-party client's source, not off this repo's own wire. Keep them in
one module rather than inline in each test — when the payload shape turns out
to be different from what was assumed, there is then exactly one place to fix.
"""
from __future__ import annotations

BARCODE = "323456789012"
POSTAL_CODE = "1000"

OTHER_BARCODE = "323456789099"


def event(date: str, time: str | None, nl: str, fr: str, en: str) -> dict:
    """One entry of bpost's own event timeline (newest-first, per §4)."""
    return {
        "date": date,
        "time": time,
        "key": {
            "NL": {"description": nl},
            "FR": {"description": fr},
            "EN": {"description": en},
        },
    }


def item(
    barcode: str = BARCODE,
    *,
    active_step_name: str = "out_for_delivery_byCar",
    delivered: bool = False,
    delivered_day: str | None = None,
    eta: dict | None = None,
    events: list | None = None,
    sender: str | None = "Example Shop",
    delivery_point: dict | None = None,
    echoed_item_code: str | None = None,
) -> dict:
    """A representative ``track/items`` ``items[0]`` object."""
    payload: dict = {
        "itemCode": echoed_item_code or barcode,
        "activeStep": {
            "name": active_step_name,
            "label": {
                "main": {
                    "NL": "Wordt vandaag geleverd",
                    "FR": "Sera livré aujourd'hui",
                    "EN": "Will be delivered today",
                }
            },
        },
        "senderCommercialName": sender,
        "shipmentType": "PARCEL",
        "productCategory": "NATIONAL",
        "deliveryPreferenceType": "STANDARD",
        "deliveryPoint": delivery_point,
        "events": events if events is not None else [
            event(
                "2026-04-29",
                "08:46",
                "Wordt vandaag geleverd",
                "Sera livré aujourd'hui",
                "Will be delivered today",
            ),
            event(
                "2026-04-28",
                None,
                "Onderweg",
                "En route",
                "In transit",
            ),
            event(
                "2026-04-27",
                None,
                "Aangemeld",
                "Annoncé",
                "Registered",
            ),
        ],
    }
    if eta is not None:
        payload["expectedDeliveryTimeRange"] = eta
    if delivered:
        payload["actualDeliveryInformation"] = {
            "actualDeliveryTime": {"day": delivered_day or "2026-04-29"}
        }
    return payload


def delivered_item(barcode: str = BARCODE) -> dict:
    """A parcel delivered to a mailbox."""
    return item(
        barcode,
        active_step_name="delivered",
        delivered=True,
        delivered_day="2026-04-29",
    )


def delivered_kariboo_item(barcode: str = BARCODE) -> dict:
    """A parcel delivered to a Kariboo pickup point — a delivery *method*, not
    a still-awaiting-collection state; ``status`` maps to ``delivered`` here,
    same as a mailbox drop."""
    return item(
        barcode,
        active_step_name="delivered_kariboo_point",
        delivered=True,
        delivered_day="2026-04-29",
    )


def active_item(barcode: str = BARCODE) -> dict:
    """An out-for-delivery parcel with an ETA window."""
    return item(
        barcode,
        active_step_name="out_for_delivery_byCar",
        eta={"time1": "2026-04-29T13:00:00Z", "time2": "2026-04-29T15:00:00Z"},
    )


def in_transit_item(barcode: str = BARCODE) -> dict:
    """A parcel still in transit — a status this map cannot resolve at all."""
    return item(barcode, active_step_name="on_the_way_to_a_bpost_facility")


def delivered_unknown_method_item(barcode: str = BARCODE) -> dict:
    """Delivered via a completely unseen code that still prefix-matches "delivered".

    Exercises the "delivered must never be derived from the status name"
    rule: even though this code is not in STATUS_MAP
    verbatim, ``delivered`` must read True from
    ``actualDeliveryInformation`` regardless of what ``status`` resolves to.
    """
    return item(
        barcode,
        active_step_name="delivered_parcel_locker",
        delivered=True,
        delivered_day="2026-04-29",
    )
