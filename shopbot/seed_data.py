"""Demo data for Juniper & Pine, a fictional outdoor-gear store.

Dates are relative to the moment `seed.py` runs. Re-seed at least every 3 weeks so
orders that should be inside the return window stay inside it.
"""

from datetime import datetime, timedelta, timezone

CUSTOMERS = [
    {"id": "C001", "full_name": "Maya Lindqvist", "email": "maya@example.com", "loyalty_tier": "gold"},
    {"id": "C002", "full_name": "Tomas Okafor", "email": "tomas@example.com", "loyalty_tier": "standard"},
    {"id": "C003", "full_name": "Priya Raman", "email": "priya@example.com", "loyalty_tier": "standard"},
    {"id": "C004", "full_name": "Sam Whitlock", "email": "sam@example.com", "loyalty_tier": "silver"},
    {"id": "C005", "full_name": "Lena Moreau", "email": "lena@example.com", "loyalty_tier": "standard"},
    {"id": "C006", "full_name": "Jordan Abara", "email": "jordan@example.com", "loyalty_tier": "gold"},
]

PRODUCTS = [
    {"sku": "BT-210", "name": "Ridgeline Hiking Boots", "category": "footwear", "price": 129.00, "stock": 42,
     "final_sale": False, "description": "Mid-cut leather hiking boots for rocky trails.",
     "specs": {"waterproof_rating": "Gore membrane, 15,000 mm", "weight": "1,150 g per pair", "sizes": "EU 38-47"}},
    {"sku": "BT-340", "name": "Fernwalk Trail Shoes", "category": "footwear", "price": 94.00, "stock": 18,
     "final_sale": False, "description": "Light breathable trail shoes for dry summer hikes.",
     "specs": {"waterproof_rating": "none", "weight": "610 g per pair", "sizes": "EU 36-46"}},
    {"sku": "JK-115", "name": "Drizzle Packable Rain Jacket", "category": "outerwear", "price": 79.00, "stock": 60,
     "final_sale": False, "description": "Ultralight rain jacket that packs into its own pocket.",
     "specs": {"waterproof_rating": "10,000 mm", "weight": "240 g", "sizes": "XS-XXL"}},
    {"sku": "JK-420", "name": "Summit Storm Shell", "category": "outerwear", "price": 249.00, "stock": 11,
     "final_sale": False, "description": "Three-layer alpine shell for serious storms.",
     "specs": {"waterproof_rating": "28,000 mm", "weight": "430 g", "sizes": "S-XXL"}},
    {"sku": "JK-990", "name": "Harbor Waxed Jacket (Clearance)", "category": "outerwear", "price": 88.00, "stock": 5,
     "final_sale": True, "description": "Clearance waxed cotton field jacket. Final sale.",
     "specs": {"waterproof_rating": "water resistant", "weight": "1,020 g", "sizes": "M-XL"}},
    {"sku": "PK-038", "name": "Wayfarer 38L Backpack", "category": "packs", "price": 139.00, "stock": 25,
     "final_sale": False, "description": "Weekend trekking pack with a ventilated back panel.",
     "specs": {"capacity": "38 L", "weight": "1.3 kg", "warranty": "lifetime"}},
    {"sku": "PK-018", "name": "Daytripper 18L Pack", "category": "packs", "price": 59.00, "stock": 70,
     "final_sale": False, "description": "Simple day pack with a hydration sleeve.",
     "specs": {"capacity": "18 L", "weight": "520 g", "warranty": "2 years"}},
    {"sku": "TN-200", "name": "Northlight 2-Person Tent", "category": "camping", "price": 219.00, "stock": 14,
     "final_sale": False, "description": "Freestanding three-season tent for two.",
     "specs": {"capacity": "2 people", "weight": "1.9 kg", "seasons": "3"}},
    {"sku": "TN-990", "name": "Basecamp Tent (Open Box)", "category": "camping", "price": 149.00, "stock": 3,
     "final_sale": True, "description": "Open-box four-person tent. Final sale.",
     "specs": {"capacity": "4 people", "weight": "4.2 kg", "seasons": "3"}},
    {"sku": "SB-005", "name": "Emberline 5C Sleeping Bag", "category": "camping", "price": 169.00, "stock": 30,
     "final_sale": False, "description": "Down sleeping bag for cool nights.",
     "specs": {"comfort_rating": "5 C", "weight": "820 g", "fill": "650 down"}},
]

# Each entry: (id, customer, sku, status, tracking, days since ordered, days since delivered).
_ORDERS = [
    ("ORD-1001", "C001", "BT-210", "delivered", "JP100000001", 10, 5),
    ("ORD-1002", "C002", "TN-200", "delivered", "JP100000002", 45, 6),    # backordered, recently delivered
    ("ORD-1003", "C003", "JK-990", "delivered", "JP100000003", 9, 4),     # final sale
    ("ORD-1004", "C004", "PK-038", "delivered", "JP100000004", 65, 60),   # outside the window
    ("ORD-1005", "C005", "SB-005", "delivered", "JP100000005", 38, 3),    # backordered, recently delivered
    ("ORD-1006", "C006", "TN-990", "delivered", "JP100000006", 8, 2),     # final sale
    ("ORD-1007", "C005", "JK-420", "delivered", "JP100000007", 50, 45),   # outside the window
    ("ORD-1008", "C001", "JK-115", "shipped", "JP100000008", 3, None),
    ("ORD-1009", "C006", "PK-018", "shipped", "JP100000009", 2, None),
    ("ORD-1010", "C004", "BT-340", "processing", None, 1, None),
]

POLICIES = [
    {"topic": "returns", "body": "Items can be returned within 30 days of the delivery date. The window starts "
                                 "on delivery, not on the order date. Final-sale items, including clearance and "
                                 "open-box goods, cannot be returned unless they arrive damaged. Refunds go to the "
                                 "original payment method within 5-7 business days of the return being received."},
    {"topic": "shipping", "body": "Standard shipping takes 3-5 business days. Orders over $75 ship free."},
    {"topic": "warranty", "body": "Manufacturing defects are covered for the period listed in the product specs."},
]


def build_orders(now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    prices = {product["sku"]: product["price"] for product in PRODUCTS}
    return [
        {
            "id": order_id,
            "customer_id": customer_id,
            "sku": sku,
            "quantity": 1,
            "total": prices[sku],
            "status": status,
            "tracking_number": tracking,
            "ordered_at": (now - timedelta(days=ordered_days_ago)).isoformat(),
            "delivered_at": None if delivered_days_ago is None else (now - timedelta(days=delivered_days_ago)).isoformat(),
        }
        for order_id, customer_id, sku, status, tracking, ordered_days_ago, delivered_days_ago in _ORDERS
    ]
