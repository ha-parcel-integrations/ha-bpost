"""Tests for Mail Ahead letter parsing."""
import logging

from custom_components.bpost.account.letters import extract_letters

from .letters_payload import LETTERS_IMAGES


def test_letters_are_flattened_newest_first():
    letters = extract_letters(LETTERS_IMAGES)
    assert [letter["id"] for letter in letters] == ["ITEM-NEW", "ITEM-OLD"]
    assert letters[1] == {
        "id": "ITEM-OLD",
        "date": "2026-10-02",
        "planned_delivery": "2026-10-02",
        "sender": "Example Bank",
        "raw": LETTERS_IMAGES["2026-10-02"][0],
    }
    assert letters[0]["sender"] is None


def test_raw_is_the_untouched_record():
    letter = extract_letters(LETTERS_IMAGES)[1]
    assert letter["raw"] is LETTERS_IMAGES["2026-10-02"][0]
    assert letter["raw"]["imageUrl"] == "https://images.example.test/old.jpg?sig=abc"


def test_unsubscribed_or_malformed_maps_are_empty():
    assert extract_letters({}) == []
    assert extract_letters(None) == []
    assert extract_letters([]) == []


def test_duplicate_item_ids_collapse():
    images = {"2026-10-02": LETTERS_IMAGES["2026-10-02"], "2026-10-03": LETTERS_IMAGES["2026-10-02"]}
    assert len(extract_letters(images)) == 1


def test_first_letter_logs_its_shape_once_without_sender_or_link(caplog):
    caplog.set_level(logging.WARNING)
    extract_letters(LETTERS_IMAGES)
    extract_letters(LETTERS_IMAGES)
    warnings = [r for r in caplog.records if "first time" in r.getMessage()]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "plannedDistributionDate" in message
    assert "Example Bank" not in message
    assert "sig=" not in message


def test_unreadable_entries_are_skipped_and_reported_once(caplog):
    caplog.set_level(logging.WARNING)
    images = {"2026-10-01": "nope", "2026-10-02": [{"imageUrl": "x"}, "nope"]}
    assert extract_letters(images) == []
    warnings = [r for r in caplog.records if "cannot read" in r.getMessage()]
    assert len(warnings) == 1
