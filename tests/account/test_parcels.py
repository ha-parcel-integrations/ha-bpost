"""Tests for conservative account parcel normalisation."""
import logging

from custom_components.bpost.account.parcels import normalize_account_parcel
from custom_components.bpost.const import CAPABILITIES_BY_VARIANT, ParcelStatus
from custom_components.bpost.tracking.parcels import NEW_ISSUE_URL


def test_account_summary_uses_stable_candidate_code_and_unknown_status():
    parcel = normalize_account_parcel({"itemCode": "TEST-CODE", "currentStatus": "moving"})
    assert parcel["barcode"] == "TEST-CODE"
    assert parcel["status"] is ParcelStatus.UNKNOWN
    assert parcel["delivered"] is False


def test_account_summary_without_a_code_is_safe():
    parcel = normalize_account_parcel({"status": "anything"}, include_history=True)
    assert parcel["barcode"] is None
    assert parcel["history"] == []
    assert parcel["raw"] == {"status": "anything"}


def test_delivered_sender_return_is_outgoing_and_has_a_timestamp():
    parcel = normalize_account_parcel(
        {"itemCode": "TEST", "userType": "SENDER", "currentStatus": "DELIVERED_TO_SENDER", "actualDeliveryTime": {"day": "2026-07-03", "time": "05:02"}, "events": [{"date": "2026-07-03", "time": "05:02", "key": "distribution.normal-regular"}]},
        include_history=True,
    )
    assert parcel["status"] is ParcelStatus.DELIVERED
    assert parcel["delivered"] is True
    assert parcel["delivered_at"].startswith("2026-07-03T05:02")
    assert parcel["history"][0]["raw_status"] == "distribution.normal-regular"


def test_receiver_v3_payload_uses_the_same_eta_and_status_structure():
    parcel = normalize_account_parcel({"itemCode": "INCOMING", "userType": "RECEIVER", "currentStatus": "OUT_FOR_DELIVERY_HOME", "eta": {"day": "2026-09-20", "time1": "09:00", "time2": "12:00"}})
    assert parcel["status"] is ParcelStatus.OUT_FOR_DELIVERY
    assert parcel["planned_from"].startswith("2026-09-20T09:00")
    assert parcel["planned_to"].startswith("2026-09-20T12:00")
    assert parcel["url"] == (
        "https://track.bpost.cloud/btr/web/#/search?lang=en&itemCode=INCOMING"
    )


def test_pending_receiver_payload_is_registered_until_a_step_becomes_active():
    parcel = normalize_account_parcel({"itemCode": "PENDING", "userType": "RECEIVER", "parcelActiveStatus": "STATUS_PENDING", "deliverySteps": [{"name": "IN_PREPARATION", "status": "upcoming"}]})
    assert parcel["status"] is ParcelStatus.REGISTERED
    assert parcel["raw_status"] == "STATUS_PENDING"


def test_account_weight_and_dimensions_are_converted_to_the_canonical_units():
    parcel = normalize_account_parcel(
        {
            "itemCode": "OUTGOING",
            "weightInGrams": "1250",
            "dimensionsInCm": "30 x 20 x 10 cm",
        }
    )
    assert parcel["weight"] == 1.25
    assert parcel["dimensions"] == {
        "length": 30.0,
        "width": 20.0,
        "height": 10.0,
        "text": "30 x 20 x 10 cm",
    }


def test_known_account_pickup_and_problem_codes_are_normalized():
    pickup = normalize_account_parcel({"currentStatus": "AVAILABLE_IN_POST_POINT"})
    assert pickup["status"] is ParcelStatus.AT_PICKUP_POINT
    assert pickup["pickup"] is True
    assert normalize_account_parcel({"currentStatus": "REDELIVERY_NO_PICKUP"})["status"] is ParcelStatus.PROBLEM


# Shape of a real My bpost parcel headed for a bbox locker; values invented.
PARCEL_LOCKER_EN_ROUTE = {
    "itemCode": "LOCKER",
    "userType": "RECEIVER",
    "serviceProvider": "bpost",
    "currentStatus": "PROCESSING",
    "eta": {"day": "2026-10-06", "time1": "", "time2": ""},
    "deliverySteps": [
        {"name": "prepare", "status": "completed", "knownProcessStep": "IN_PREPARATION"},
        {"name": "processing", "status": "active", "knownProcessStep": "PROCESSING"},
        {"name": "out_for_delivery_onFoot", "status": "upcoming", "knownProcessStep": "ON_THE_WAY_TO_PARCEL_LOCKER"},
        {"name": "parcel_locker", "status": "upcoming", "knownProcessStep": "AVAILABLE_IN_PARCEL_LOCKER"},
        {"name": "delivered_parcel_locker", "status": "upcoming", "knownProcessStep": "PICKED_UP_IN_PARCEL_LOCKER"},
    ],
    "deliveryPoint": {
        "id": "1",
        "type": "PARCEL_LOCKER",
        "name": "Example bbox",
        "street": "Examplestraat",
        "streetNumber": "1",
        "postcode": "1000",
        "municipality": "Brussel",
        "description": "Outside, right on the parking lot.",
        "openingSchedules": [{"dayOfTheWeek": "MONDAY", "openingHours": [{"open": "08:00", "close": "20:00"}]}],
        "lockerDetails": {"lockerType": "Cubee Locker", "lockerProvider": "Cubee"},
    },
    "viewParcelDetails": [
        {"key": "productName", "title": "Mode of Shipping", "desc": "Cubee parcel locker"},
    ],
}


def test_parcel_locker_is_a_pickup_with_its_name_before_arrival(caplog):
    with caplog.at_level(logging.WARNING):
        parcel = normalize_account_parcel(PARCEL_LOCKER_EN_ROUTE)
    assert parcel["status"] is ParcelStatus.IN_TRANSIT
    assert parcel["pickup"] is True
    assert parcel["pickup_point"] == "Example bbox"
    assert caplog.text == ""


def test_unseen_delivery_point_type_still_populates_and_warns_once(caplog):
    raw = {**PARCEL_LOCKER_EN_ROUTE, "deliveryPoint": {"type": "POST_POINT", "name": "Shop"}}
    with caplog.at_level(logging.WARNING):
        parcel = normalize_account_parcel(raw)
        normalize_account_parcel(raw)
    assert parcel["pickup_point"] == "Shop"
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "POST_POINT" in warnings[0].getMessage()


def test_account_capabilities_match_the_confirmed_account_payload_fields():
    assert CAPABILITIES_BY_VARIANT["Account"] == {
        "weight",
        "dimensions",
        "delivery_window",
        "pickup_point",
        "url",
        "history",
    }


def test_unmapped_account_status_warns_once_with_the_issue_link(caplog):
    raw = {"itemCode": "IN", "currentStatus": "SOMETHING_NEW"}

    with caplog.at_level(logging.WARNING):
        normalize_account_parcel(raw)
        normalize_account_parcel(raw)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert NEW_ISSUE_URL in warnings[0].getMessage()
    assert "SOMETHING_NEW" in warnings[0].getMessage()
