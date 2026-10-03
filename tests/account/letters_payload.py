"""Mail Ahead letters, reconstructed from the app's model with made-up values."""

LETTERS_IMAGES = {
    "2026-10-02": [
        {
            "itemId": "ITEM-OLD",
            "trackingId": "TRK-0001",
            "imageRefId": "REF-OLD",
            "imageUrl": "https://images.example.test/old.jpg?sig=abc",
            "imageType": "jpg",
            "plannedDistributionDate": "2026-10-02",
            "rotateValue": 0,
            "sender": {"name": "Example Bank", "logo": {"svg": None, "png": None}},
            "actions": {"shareAllowed": True},
        }
    ],
    "2026-10-03": [
        {
            "itemId": "ITEM-NEW",
            "trackingId": "TRK-0002",
            "imageRefId": "REF-NEW",
            "imageUrl": "https://images.example.test/new.jpg?sig=def",
            "imageType": "jpg",
            "plannedDistributionDate": "2026-10-03",
            "sender": None,
        }
    ],
}
