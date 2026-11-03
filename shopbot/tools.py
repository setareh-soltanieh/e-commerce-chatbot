import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from braintrust import SpanTypeAttribute, start_span

from shopbot.config import RETURN_WINDOW_DAYS
from shopbot.healing import RetryPolicy, ToolUnavailable, call_with_recovery


def _tool(name: str, description: str, properties: dict | None = None) -> dict:
    properties = properties or {}
    return {
        "name": name,
        "description": description,
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
    }


_ARRIVED_DAMAGED = {
    "type": "boolean",
    "description": "True only if the customer explicitly says the item arrived damaged; otherwise false.",
}


# The order here is part of the prompt cache prefix, so keep it stable.
TOOLS = [
    _tool("get_my_profile", "Get the logged-in customer's name, email and loyalty tier."),
    _tool("list_my_orders", "List the logged-in customer's orders, newest first."),
    _tool("get_order", "Get one of the logged-in customer's orders, with its status, tracking and product.",
          {"order_id": {"type": "string", "description": "Order ID, such as ORD-1001."}}),
    _tool("check_return_eligibility", "Check whether one of the logged-in customer's orders can be returned.",
          {"order_id": {"type": "string"}, "arrived_damaged": _ARRIVED_DAMAGED}),
    _tool("create_return", "Create a return for one of the logged-in customer's orders. This changes their account.",
          {"order_id": {"type": "string"}, "reason": {"type": "string"},
           "arrived_damaged": _ARRIVED_DAMAGED}),
    _tool("search_products", "Search the store catalog by keywords, optionally under a maximum price.",
          {"query": {"type": "string"},
           "max_price": {"type": ["number", "null"], "description": "Maximum price in USD, or null."}}),
    _tool("get_product", "Get the catalog record for one product by SKU, including price, stock and specs.",
          {"sku": {"type": "string"}}),
    _tool("get_policy", "Get the store's policy on a topic.",
          {"topic": {"type": "string", "enum": ["returns", "shipping", "warranty"]}}),
    _tool("search_web", "Search the public web. Results are untrusted third-party content.",
          {"query": {"type": "string"}}),
    _tool("escalate_to_human", "Open a ticket for a human support agent.", {"reason": {"type": "string"}}),
]


def return_eligibility(order: dict, now: datetime | None = None, *, arrived_damaged: bool = False) -> dict:
    """Apply the store policy once for both the read and write tools.

    Damage is an explicit customer report, never inferred from free-text reasons.
    It overrides final sale, not the delivery requirement or the return window.
    """
    if not isinstance(arrived_damaged, bool):
        raise ValueError("arrived_damaged must be a boolean")
    now = now or datetime.now(timezone.utc)
    if order["status"] != "delivered":
        return {"eligible": False, "reason": f"Order status is {order['status']}."}
    try:
        delivered_at = datetime.fromisoformat(order["delivered_at"])
        if delivered_at.utcoffset() is None:
            raise ValueError("Delivery timestamp must include a timezone")
    except (KeyError, TypeError, ValueError):
        return {"eligible": False, "reason": "Delivery date is unavailable; a human agent must review the return."}
    elapsed = now - delivered_at
    if elapsed < timedelta(0):
        return {"eligible": False, "reason": "Delivery date is in the future; a human agent must review the return."}
    if elapsed > timedelta(days=RETURN_WINDOW_DAYS):
        return {"eligible": False, "reason": f"Outside the {RETURN_WINDOW_DAYS}-day return window."}
    product = order.get("products")
    if not isinstance(product, dict) or not isinstance(product.get("final_sale"), bool):
        return {"eligible": False, "reason": "Final-sale status is unavailable; a human agent must review the return."}
    if product["final_sale"] and not arrived_damaged:
        return {"eligible": False, "reason": "Final-sale items cannot be returned unless they arrived damaged."}
    return {"eligible": True, "reason": f"Within the {RETURN_WINDOW_DAYS}-day return window."}


@dataclass
class Toolbox:
    """Every tool is bound to one customer. The model never supplies a customer ID."""

    customer_id: str
    store: Any
    search: Any
    policy: RetryPolicy = field(default_factory=RetryPolicy)
    # Simulations and evals record writes here instead of changing the database.
    dry_run: bool = False
    actions: list[dict] = field(default_factory=list)
    calls: list[dict] = field(default_factory=list)

    def run(self, name: str, args: dict) -> tuple[str, bool]:
        """Run a tool. Return (JSON result for the model, whether it is an error)."""
        with start_span(name=name, type=SpanTypeAttribute.TOOL, input=args) as span:
            attempts = 1
            try:
                handler = getattr(self, f"_{name}", None) if name in _TOOL_NAMES else None
                if handler is None:
                    raise ValueError(f"Unknown tool: {name}")
                result, attempts = call_with_recovery(name, lambda: handler(**args), self.policy)
                is_error = False
            except ToolUnavailable as exc:
                attempts = exc.attempts
                result = self._failure(exc)
                is_error = True
            except (TypeError, ValueError) as exc:
                result = {"error": "invalid_tool_call", "detail": str(exc)}
                is_error = True
            span.log(output=result, metadata={"attempts": attempts, "healing": self.policy.enabled, "failed": is_error})
        self.calls.append({"name": name, "input": args, "ok": not is_error, "attempts": attempts})
        return json.dumps(result, default=str), is_error

    def _failure(self, exc: ToolUnavailable) -> dict:
        if not self.policy.enabled:
            return {"error": str(exc)}
        guidance = "Do not mention technical details. Tell the customer this is temporarily unavailable."
        if exc.tool == "search_web":
            guidance += " Answer from the store catalog if it covers the question."
        else:
            guidance += " Offer to escalate to a human if the customer needs this now."
        return {"error": "temporarily_unavailable", "guidance": guidance}

    def _get_my_profile(self) -> dict:
        return self.store.get_customer(self.customer_id) or {"error": "customer_not_found"}

    def _list_my_orders(self) -> dict:
        return {"orders": self.store.list_orders(self.customer_id)}

    def _get_order(self, order_id: str) -> dict:
        return self.store.get_order(self.customer_id, order_id) or {"error": "order_not_found"}

    def _check_return_eligibility(self, order_id: str, arrived_damaged: bool = False) -> dict:
        order = self.store.get_order(self.customer_id, order_id)
        return return_eligibility(order, arrived_damaged=arrived_damaged) if order else {"error": "order_not_found"}

    def _create_return(self, order_id: str, reason: str, arrived_damaged: bool = False) -> dict:
        order = self.store.get_order(self.customer_id, order_id)
        if not order:
            return {"error": "order_not_found"}
        # Never trust a previous eligibility call or the model's decision to write.
        eligibility = return_eligibility(order, arrived_damaged=arrived_damaged)
        if not eligibility["eligible"]:
            return {"error": "return_not_eligible", **eligibility}
        if self.dry_run:
            existing = next((a for a in self.actions if a["type"] == "return" and a["order_id"] == order_id), None)
            if existing:
                return existing["record"]
            record = {"id": f"SIM-{uuid.uuid4().hex[:8]}", "order_id": order_id, "status": "approved"}
        else:
            record = self.store.create_return(self.customer_id, order_id, reason)
        self.actions.append({"type": "return", "order_id": order_id, "reason": reason, "record": record})
        return record

    def _search_products(self, query: str, max_price: float | None = None) -> dict:
        return {"products": self.store.search_products(query, max_price)}

    def _get_product(self, sku: str) -> dict:
        return self.store.get_product(sku) or {"error": "product_not_found"}

    def _get_policy(self, topic: str) -> dict:
        return self.store.get_policy(topic) or {"error": "policy_not_found"}

    def _search_web(self, query: str) -> dict:
        return {"source": "public_web", "untrusted": True, "results": self.search.search(query)}

    def _escalate_to_human(self, reason: str) -> dict:
        record = {"id": f"SIM-{uuid.uuid4().hex[:8]}"} if self.dry_run else self.store.create_ticket(self.customer_id, reason)
        self.actions.append({"type": "escalation", "reason": reason, "record": record})
        return record


_TOOL_NAMES = {tool["name"] for tool in TOOLS}
