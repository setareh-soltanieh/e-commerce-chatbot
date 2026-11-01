import os
import re

from supabase import create_client


def _search_tokens(query: str) -> list[str]:
    # PostgREST filter strings treat commas, dots and parentheses as syntax, so only
    # plain words from model-written queries may reach the filter.
    return re.findall(r"[^\W_]+", query.lower())[:6]


class SupabaseStore:
    def __init__(self, url: str | None = None, key: str | None = None):
        self._db = create_client(
            url or os.environ["SUPABASE_URL"],
            key or os.environ["SUPABASE_SERVICE_ROLE_KEY"],
        )

    def get_customer(self, customer_id: str) -> dict | None:
        rows = self._db.table("customers").select("*").eq("id", customer_id).execute().data
        return rows[0] if rows else None

    def list_orders(self, customer_id: str) -> list[dict]:
        return (
            self._db.table("orders")
            .select("*, products(name)")
            .eq("customer_id", customer_id)
            .order("ordered_at", desc=True)
            .execute()
            .data
        )

    def get_order(self, customer_id: str, order_id: str) -> dict | None:
        rows = (
            self._db.table("orders")
            .select("*, products(*)")
            .eq("customer_id", customer_id)
            .eq("id", order_id)
            .execute()
            .data
        )
        return rows[0] if rows else None

    def search_products(self, query: str, max_price: float | None = None) -> list[dict]:
        request = self._db.table("products").select("*")
        tokens = _search_tokens(query)
        if tokens:
            request = request.or_(",".join(
                f"{column}.ilike.%{token}%"
                for token in tokens
                for column in ("name", "description", "category")
            ))
        if max_price is not None:
            request = request.lte("price", max_price)
        return request.order("price").limit(10).execute().data

    def get_product(self, sku: str) -> dict | None:
        rows = self._db.table("products").select("*").eq("sku", sku).execute().data
        return rows[0] if rows else None

    def get_policy(self, topic: str) -> dict | None:
        rows = self._db.table("policies").select("*").eq("topic", topic).execute().data
        return rows[0] if rows else None

    def create_return(self, customer_id: str, order_id: str, reason: str) -> dict:
        self._db.table("returns").upsert(
            {"customer_id": customer_id, "order_id": order_id, "reason": reason},
            on_conflict="order_id",
            ignore_duplicates=True,
        ).execute()
        return self._db.table("returns").select("*").eq("order_id", order_id).execute().data[0]

    def create_ticket(self, customer_id: str, reason: str) -> dict:
        return self._db.table("support_tickets").insert(
            {"customer_id": customer_id, "reason": reason}
        ).execute().data[0]
