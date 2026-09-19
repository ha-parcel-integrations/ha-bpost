"""bpost's own parcel status vocabulary, shared by both sources.

The account route reports these codes as ``currentStatus`` and the public
tracking route as ``activeStep.knownProcessStep`` — one vocabulary behind two
field names, so the map lives here and neither source can drift from it.
"""
from __future__ import annotations

from .const import ParcelStatus

# Where users report a status/shape we do not handle yet. The ``?template=``
# parameter matters: without it the link opens a blank form, missing the
# version and the log line we need.
NEW_ISSUE_URL = (
    "https://github.com/ha-parcel-integrations/ha-bpost/issues/new"
    "?template=unrecognised_status.yml"
)

KNOWN_PROCESS_STEP_MAP: dict[str, ParcelStatus] = {
    # Announced or being prepared; bpost has the data, not the parcel.
    "IN_PREPARATION": ParcelStatus.REGISTERED,
    "IN_PREPARATION_AWAITING_DROPOFF": ParcelStatus.REGISTERED,
    "IN_PREPARATION_AWAITING_PICKUP": ParcelStatus.REGISTERED,
    "IN_PREPARATION_AWAITING_PICKUPDROPOFF": ParcelStatus.REGISTERED,
    "IN_PREPARATION_INTERNATIONAL": ParcelStatus.REGISTERED,
    "IN_PREPARATION_INTERNATIONAL_AWAITING_DROPOFF": ParcelStatus.REGISTERED,
    "IN_PREPARATION_INTERNATIONAL_AWAITING_PICKUP": ParcelStatus.REGISTERED,
    "IN_PREPARATION_INTERNATIONAL_AWAITING_PICKUPDROPOFF": ParcelStatus.REGISTERED,
    "PENDING_APPROVAL": ParcelStatus.REGISTERED,
    "PREPARATION": ParcelStatus.REGISTERED,
    "PREPARATION_AWAITING_DROPOFF": ParcelStatus.REGISTERED,
    "PREPARATION_AWAITING_PICKUP": ParcelStatus.REGISTERED,
    "PREPARATION_AWAITING_PICKUPDROPOFF": ParcelStatus.REGISTERED,
    "STATUS_PENDING": ParcelStatus.REGISTERED,
    # A shipping label that exists while the parcel does not yet.
    "mpcPrinted": ParcelStatus.REGISTERED,

    # Moving through the network, customs included while nothing is owed.
    "AWAITING": ParcelStatus.IN_TRANSIT,
    "CUSTOMS": ParcelStatus.IN_TRANSIT,
    "CUSTOMS_PAYMENT_NOT_REQUIRED": ParcelStatus.IN_TRANSIT,
    "CUSTOMS_PAYMENT_SUCCESSFUL": ParcelStatus.IN_TRANSIT,
    "EXPECTED": ParcelStatus.IN_TRANSIT,
    "ON_THE_WAY": ParcelStatus.IN_TRANSIT,
    "PROCESSING": ParcelStatus.IN_TRANSIT,
    "PROCESSING_HOME": ParcelStatus.IN_TRANSIT,
    "PROCESSING_INTERNATIONAL": ParcelStatus.IN_TRANSIT,
    "PROCESSING_KARIBOO_POINT": ParcelStatus.IN_TRANSIT,
    "PROCESSING_OUTBOUND_ABROAD": ParcelStatus.IN_TRANSIT,
    "PROCESSING_OUTBOUND_ABROAD_PARCEL_LOCKER": ParcelStatus.IN_TRANSIT,
    "PROCESSING_OUTBOUND_ABROAD_POST_POINT": ParcelStatus.IN_TRANSIT,
    "PROCESSING_OUTBOUND_BPOST": ParcelStatus.IN_TRANSIT,
    "PROCESSING_PARCEL_LOCKER": ParcelStatus.IN_TRANSIT,
    "PROCESSING_PARCEL_LOCKER_AVISE": ParcelStatus.IN_TRANSIT,
    "PROCESSING_POST_OFFICE": ParcelStatus.IN_TRANSIT,
    "PROCESSING_POST_POINT": ParcelStatus.IN_TRANSIT,
    "PROCESSING_SECOND_PRESENTATION": ParcelStatus.IN_TRANSIT,
    "PROCESSING_SHOP": ParcelStatus.IN_TRANSIT,

    # On the round today, whether to an address or to a pickup location.
    "ON_THE_WAY_TO_KARIBOO_POINT": ParcelStatus.OUT_FOR_DELIVERY,
    "ON_THE_WAY_TO_PARCEL_LOCKER": ParcelStatus.OUT_FOR_DELIVERY,
    "ON_THE_WAY_TO_PARCIFY_HUB": ParcelStatus.OUT_FOR_DELIVERY,
    "ON_THE_WAY_TO_POSTAL_OFFICE": ParcelStatus.OUT_FOR_DELIVERY,
    "ON_THE_WAY_TO_POST_OFFICE": ParcelStatus.OUT_FOR_DELIVERY,
    "ON_THE_WAY_TO_POST_POINT": ParcelStatus.OUT_FOR_DELIVERY,
    "ON_THE_WAY_TO_SHOP": ParcelStatus.OUT_FOR_DELIVERY,
    "ON_THE_WAY_TO_YOU": ParcelStatus.OUT_FOR_DELIVERY,
    "OUT_FOR_DELIVERY_HOME": ParcelStatus.OUT_FOR_DELIVERY,
    "OUT_FOR_DELIVERY_KARIBOO_POINT": ParcelStatus.OUT_FOR_DELIVERY,
    "OUT_FOR_DELIVERY_PARCIFY_HUB": ParcelStatus.OUT_FOR_DELIVERY,
    "OUT_FOR_DELIVERY_POST_OFFICE": ParcelStatus.OUT_FOR_DELIVERY,
    "OUT_FOR_DELIVERY_POST_POINT": ParcelStatus.OUT_FOR_DELIVERY,
    # The round-mode variants are the one family bpost spells in camelCase.
    "out_for_delivery_onFoot": ParcelStatus.OUT_FOR_DELIVERY,
    "out_for_delivery_byBike": ParcelStatus.OUT_FOR_DELIVERY,
    "out_for_delivery_byCar": ParcelStatus.OUT_FOR_DELIVERY,
    "out_for_delivery_byEbike": ParcelStatus.OUT_FOR_DELIVERY,
    "out_for_delivery_byECar": ParcelStatus.OUT_FOR_DELIVERY,

    # Waiting to be collected — the set the app itself warns the user about.
    "AVAILABLE": ParcelStatus.AT_PICKUP_POINT,
    "AVAILABLE_ADVISED_POST_POINT": ParcelStatus.AT_PICKUP_POINT,
    "AVAILABLE_INTERNATIONAL_PARCEL_LOCKER": ParcelStatus.AT_PICKUP_POINT,
    "AVAILABLE_INTERNATIONAL_POST_POINT": ParcelStatus.AT_PICKUP_POINT,
    "AVAILABLE_IN_KARIBOO_POINT": ParcelStatus.AT_PICKUP_POINT,
    "AVAILABLE_IN_PARCEL_LOCKER": ParcelStatus.AT_PICKUP_POINT,
    "AVAILABLE_IN_PARCEL_LOCKER_INTERNATIONAL": ParcelStatus.AT_PICKUP_POINT,
    "AVAILABLE_IN_POST_OFFICE": ParcelStatus.AT_PICKUP_POINT,
    "AVAILABLE_IN_POST_POINT": ParcelStatus.AT_PICKUP_POINT,
    "AVAILABLE_IN_POST_POINT_INTERNATIONAL": ParcelStatus.AT_PICKUP_POINT,
    "AVAILABLE_IN_SHOP": ParcelStatus.AT_PICKUP_POINT,
    "AVAILABLE_KARIBOO_POINT": ParcelStatus.AT_PICKUP_POINT,
    "AVAILABLE_PARCEL_LOCKER": ParcelStatus.AT_PICKUP_POINT,
    "AVAILABLE_PARCEL_LOCKER_INTERNATIONAL": ParcelStatus.AT_PICKUP_POINT,
    "AVAILABLE_POST_OFFICE": ParcelStatus.AT_PICKUP_POINT,
    "AVAILABLE_POST_POINT": ParcelStatus.AT_PICKUP_POINT,
    "AVAILABLE_POST_POINT_INTERNATIONAL": ParcelStatus.AT_PICKUP_POINT,
    "AVAILABLE_SHOP": ParcelStatus.AT_PICKUP_POINT,
    "REDELIVERY_CAN_PICKUP_POST_POINT": ParcelStatus.AT_PICKUP_POINT,

    # Terminal for the recipient: handed over, dropped off, or collected.
    "DELIVERED": ParcelStatus.DELIVERED,
    "DELIVERED_AT_FORCED_NB": ParcelStatus.DELIVERED,
    "DELIVERED_AT_FORCED_SP": ParcelStatus.DELIVERED,
    "DELIVERED_AT_HOME": ParcelStatus.DELIVERED,
    "DELIVERED_AT_NEIGHBOUR": ParcelStatus.DELIVERED,
    "DELIVERED_IN_MAILBOX": ParcelStatus.DELIVERED,
    "DELIVERED_MANUALLY": ParcelStatus.DELIVERED,
    "DELIVERED_TO_KARIBOO": ParcelStatus.DELIVERED,
    "DELIVERED_TO_SAFEPLACE": ParcelStatus.DELIVERED,
    "PICKED_UP": ParcelStatus.DELIVERED,
    "PICKED_UP_AT_INTERNATIONAL_PARCEL_LOCKER": ParcelStatus.DELIVERED,
    "PICKED_UP_AT_INTERNATIONAL_POST_POINT": ParcelStatus.DELIVERED,
    "PICKED_UP_IN_KARIBOO_POINT": ParcelStatus.DELIVERED,
    "PICKED_UP_IN_PARCEL_LOCKER": ParcelStatus.DELIVERED,
    "PICKED_UP_IN_PARCEL_LOCKER_INTERNATIONAL": ParcelStatus.DELIVERED,
    "PICKED_UP_IN_POST_OFFICE": ParcelStatus.DELIVERED,
    "PICKED_UP_IN_POST_POINT": ParcelStatus.DELIVERED,
    "PICKED_UP_IN_POST_POINT_INTERNATIONAL": ParcelStatus.DELIVERED,
    "PICKED_UP_IN_SHOP": ParcelStatus.DELIVERED,
    # A return leg that has arrived is terminal, not in flight: the parcel
    # never moves again, so it belongs in the delivered bucket rather than
    # sitting in the active one forever. ``raw_status`` still names the leg.
    "BTS_DELIVERED": ParcelStatus.DELIVERED,
    "DELIVERED_TO_SENDER": ParcelStatus.DELIVERED,
    "DELIVERED_TO_SENDER_RETURN": ParcelStatus.DELIVERED,
    "PICKED_UP_BY_SENDER": ParcelStatus.DELIVERED,
    "RETOUR_DELIVERED": ParcelStatus.DELIVERED,

    # Still heading back to the sender. The BTS_/RETOUR_ families are the
    # return leg of a delivery round; while it is in flight the direction is
    # what matters, so even its "available at a point" codes stay here — that
    # point is the sender's, not a collection the user can act on.
    "BTS_AVAILABLE_PARCEL_LOCKER": ParcelStatus.RETURNING,
    "BTS_AVAILABLE_POST_POINT": ParcelStatus.RETURNING,
    "BTS_OUT_FOR_DELIVERY_HOME": ParcelStatus.RETURNING,
    "BTS_OUT_FOR_DELIVERY_KARIBOO_POINT": ParcelStatus.RETURNING,
    "BTS_OUT_FOR_DELIVERY_PARCEL_LOCKER": ParcelStatus.RETURNING,
    "BTS_OUT_FOR_DELIVERY_POST_OFFICE": ParcelStatus.RETURNING,
    "BTS_OUT_FOR_DELIVERY_POST_POINT": ParcelStatus.RETURNING,
    "ON_THE_WAY_TO_SENDER": ParcelStatus.RETURNING,
    "OUT_FOR_DELIVERY_SENDER": ParcelStatus.RETURNING,
    "RETOUR_AVAILABLE_POST_POINT": ParcelStatus.RETURNING,
    "RETOUR_OUT_FOR_DELIVERY_HOME": ParcelStatus.RETURNING,
    "RETOUR_OUT_FOR_DELIVERY_KARIBOO_POINT": ParcelStatus.RETURNING,
    "RETOUR_OUT_FOR_DELIVERY_POST_OFFICE": ParcelStatus.RETURNING,
    "RETOUR_OUT_FOR_DELIVERY_POST_POINT": ParcelStatus.RETURNING,
    "RETURN_TO_SENDER": ParcelStatus.RETURNING,
    "RETURN_TO_SENDER_INTERNATIONAL": ParcelStatus.RETURNING,

    # Stuck: money owed, a payment that failed, or a collection deadline missed.
    "AWAITING_CUSTOMS_PAYMENT": ParcelStatus.PROBLEM,
    "CUSTOMS_PAYMENT_CHALLENGED": ParcelStatus.PROBLEM,
    "CUSTOMS_PAYMENT_EXPIRED": ParcelStatus.PROBLEM,
    "CUSTOMS_PAYMENT_REFUSED": ParcelStatus.PROBLEM,
    "EXCEPTION": ParcelStatus.PROBLEM,
    "REDELIVERY_NO_PICKUP": ParcelStatus.PROBLEM,
}


def map_known_process_step(code: str | None) -> ParcelStatus | None:
    """Map one of bpost's own status codes, or ``None`` if it is not one."""
    if not code:
        return None
    return KNOWN_PROCESS_STEP_MAP.get(code)
