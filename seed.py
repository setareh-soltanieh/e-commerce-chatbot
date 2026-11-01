"""Load the demo data into Supabase. Run supabase/schema.sql first. Safe to re-run: rows are upserted by key.

    uv run seed.py
"""

from shopbot.config import PROJECT  # noqa: F401  (loads .env)
from shopbot.seed_data import CUSTOMERS, POLICIES, PRODUCTS, build_orders
from shopbot.store import SupabaseStore


def main() -> None:
    db = SupabaseStore()._db
    orders = build_orders()
    db.table("customers").upsert(CUSTOMERS).execute()
    db.table("products").upsert(PRODUCTS).execute()
    db.table("orders").upsert(orders).execute()
    db.table("policies").upsert(POLICIES).execute()
    print(f"Seeded {len(CUSTOMERS)} customers, {len(PRODUCTS)} products, {len(orders)} orders, {len(POLICIES)} policies.")


if __name__ == "__main__":
    main()
