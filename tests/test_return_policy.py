"""Regression coverage for policy decisions and the return write boundary."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from shopbot.config import RETURN_WINDOW_DAYS
from shopbot.seed_data import build_orders
from shopbot.tools import TOOLS, Toolbox, return_eligibility
from tests.fakes import FakeSearch, FakeStore


NOW = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)


@pytest.fixture
def store(monkeypatch):
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz)

    monkeypatch.setattr("shopbot.tools.datetime", FixedDatetime)
    store = FakeStore()
    store.orders = build_orders(NOW)
    return store


def invoke(box, name, **args):
    payload, is_error = box.run(name, args)
    assert not is_error  # Policy denials are structured business results.
    return json.loads(payload)


@pytest.mark.parametrize("customer,order_id", [("C002", "ORD-1002"), ("C005", "ORD-1005")])
@pytest.mark.parametrize("dry_run", [True, False])
def test_backordered_returns_use_delivery_date(store, customer, order_id, dry_run):
    box = Toolbox(customer, store, FakeSearch(), dry_run=dry_run)
    order = store.get_order(customer, order_id)
    assert NOW - datetime.fromisoformat(order["ordered_at"]) > timedelta(days=RETURN_WINDOW_DAYS)
    assert invoke(box, "check_return_eligibility", order_id=order_id)["eligible"] is True
    record = invoke(box, "create_return", order_id=order_id, reason="changed mind")
    assert record["order_id"] == order_id
    assert len(box.actions) == 1
    assert len(store.returns) == (0 if dry_run else 1)


@pytest.mark.parametrize("customer,order_id", [
    ("C003", "ORD-1003"), ("C006", "ORD-1006"),  # Clearance and open box.
    ("C004", "ORD-1004"), ("C005", "ORD-1007"),  # Delivered too long ago.
    ("C001", "ORD-1008"), ("C006", "ORD-1009"),  # Not delivered.
    ("C004", "ORD-1010"),  # Still processing.
])
@pytest.mark.parametrize("dry_run", [True, False])
def test_ineligible_orders_cannot_create_returns_without_a_prior_check(store, customer, order_id, dry_run):
    box = Toolbox(customer, store, FakeSearch(), dry_run=dry_run)
    # Call the write directly: the model must not be able to bypass the policy.
    denied = invoke(box, "create_return", order_id=order_id, reason="changed mind")
    decision = invoke(box, "check_return_eligibility", order_id=order_id)
    assert decision["eligible"] is False
    assert denied == {"error": "return_not_eligible", **decision}
    assert box.actions == []
    assert store.returns == []


@pytest.mark.parametrize("customer,order_id", [("C003", "ORD-1003"), ("C006", "ORD-1006")])
@pytest.mark.parametrize("dry_run", [True, False])
def test_explicit_arrival_damage_allows_final_sale_return(store, customer, order_id, dry_run):
    box = Toolbox(customer, store, FakeSearch(), dry_run=dry_run)
    assert invoke(box, "check_return_eligibility", order_id=order_id, arrived_damaged=True)["eligible"] is True
    record = invoke(box, "create_return", order_id=order_id, reason="arrived torn", arrived_damaged=True)
    assert record["order_id"] == order_id
    assert len(box.actions) == 1
    assert len(store.returns) == (0 if dry_run else 1)


def test_damage_is_not_inferred_from_free_text(store):
    box = Toolbox("C003", store, FakeSearch(), dry_run=False)
    denied = invoke(box, "create_return", order_id="ORD-1003", reason="not damaged, changed mind")
    assert denied["error"] == "return_not_eligible"
    assert not store.returns


@pytest.mark.parametrize("customer,order_id", [("C004", "ORD-1004"), ("C001", "ORD-1008")])
def test_damage_does_not_override_window_or_delivery_status(store, customer, order_id):
    box = Toolbox(customer, store, FakeSearch(), dry_run=False)
    denied = invoke(box, "create_return", order_id=order_id, reason="arrived damaged", arrived_damaged=True)
    assert denied["error"] == "return_not_eligible"
    assert not box.actions and not store.returns


@pytest.mark.parametrize("dry_run", [True, False])
def test_creation_rechecks_current_order_after_a_successful_check(store, dry_run):
    box = Toolbox("C001", store, FakeSearch(), dry_run=dry_run)
    assert invoke(box, "check_return_eligibility", order_id="ORD-1001")["eligible"] is True
    store.orders[0]["delivered_at"] = (NOW - timedelta(days=31)).isoformat()
    assert invoke(box, "create_return", order_id="ORD-1001", reason="changed mind")["error"] == "return_not_eligible"
    assert not box.actions and not store.returns


@pytest.mark.parametrize("dry_run", [True, False])
def test_damage_exception_does_not_bypass_customer_scope(store, dry_run):
    box = Toolbox("C001", store, FakeSearch(), dry_run=dry_run)
    assert invoke(box, "check_return_eligibility", order_id="ORD-1003", arrived_damaged=True) == {"error": "order_not_found"}
    assert invoke(box, "create_return", order_id="ORD-1003", reason="damaged", arrived_damaged=True) == {"error": "order_not_found"}
    assert not box.actions and not store.returns


@pytest.mark.parametrize("elapsed,eligible", [
    (timedelta(days=30) - timedelta(microseconds=1), True),
    (timedelta(days=30), True),
    (timedelta(days=30, microseconds=1), False),
    (timedelta(days=-1), False),
])
def test_exact_return_window_boundary(store, elapsed, eligible):
    order = store.get_order("C001", "ORD-1001")
    order["delivered_at"] = (NOW - elapsed).isoformat()
    assert return_eligibility(order, NOW)["eligible"] is eligible


def test_delivery_timestamp_offsets_are_respected(store):
    order = store.get_order("C001", "ORD-1001")
    order["delivered_at"] = (NOW - timedelta(days=30)).astimezone(timezone(timedelta(hours=5))).isoformat()
    assert return_eligibility(order, NOW)["eligible"] is True


@pytest.mark.parametrize("delivered_at", [None, "bad timestamp", "2026-10-30T12:00:00"])
@pytest.mark.parametrize("dry_run", [True, False])
def test_missing_or_invalid_delivery_dates_fail_closed(store, delivered_at, dry_run):
    store.orders[0]["delivered_at"] = delivered_at
    box = Toolbox("C001", store, FakeSearch(), dry_run=dry_run)
    assert invoke(box, "check_return_eligibility", order_id="ORD-1001")["eligible"] is False
    assert invoke(box, "create_return", order_id="ORD-1001", reason="changed mind")["error"] == "return_not_eligible"
    assert not box.actions and not store.returns


@pytest.mark.parametrize("product", [None, {}, {"final_sale": "false"}])
def test_unknown_final_sale_status_requires_review(store, product):
    order = store.get_order("C001", "ORD-1001")
    order["products"] = product
    assert return_eligibility(order, NOW)["eligible"] is False


def test_cancelled_orders_and_missing_delivery_dates_require_review(store):
    order = store.get_order("C001", "ORD-1001")
    order.pop("delivered_at")
    assert return_eligibility(order, NOW)["eligible"] is False
    order["status"] = "cancelled"
    assert return_eligibility(order, NOW, arrived_damaged=True)["eligible"] is False


def test_tool_schemas_expose_explicit_damage_report():
    for tool in TOOLS:
        if tool["name"] in {"check_return_eligibility", "create_return"}:
            schema = tool["input_schema"]
            assert schema["properties"]["arrived_damaged"]["type"] == "boolean"
            assert "arrived_damaged" in schema["required"]


@pytest.mark.parametrize("value", ["true", "false", 1, None])
def test_damage_flag_must_be_boolean(store, value):
    order = store.get_order("C003", "ORD-1003")
    with pytest.raises(ValueError, match="must be a boolean"):
        return_eligibility(order, NOW, arrived_damaged=value)
