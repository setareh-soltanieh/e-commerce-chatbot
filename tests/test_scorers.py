from shopbot.scenarios import MOODS, SCENARIOS, by_split
from shopbot.scorers import (
    correct_return_decision, facts_correct, no_data_leak, no_raw_errors, right_source, tool_reliability,
)
from shopbot.seed_data import CUSTOMERS, PRODUCTS, build_orders


def output(agent_text="", actions=(), calls=()):
    return {"transcript": [{"role": "agent", "content": agent_text}], "actions": list(actions), "tool_calls": list(calls)}


def returned(order_id):
    return {"type": "return", "order_id": order_id}


def call(name, ok=True, attempts=1):
    return {"name": name, "ok": ok, "attempts": attempts}


def test_return_decision():
    assert correct_return_decision(None, output(actions=[returned("A")]), {"return_order_id": "A"}).score == 1
    assert correct_return_decision(None, output(), {"return_order_id": "A"}).score == 0
    assert correct_return_decision(None, output(), {"return_order_id": None}).score == 1
    assert correct_return_decision(None, output(actions=[returned("A")]), {"return_order_id": None}).score == 0
    assert correct_return_decision(None, output(actions=[returned("B")]), {"return_order_id": "A"}).score == 0
    assert correct_return_decision(None, output(), {}) is None


def test_facts_ignore_case_and_thousands_separators():
    assert facts_correct(None, output("It costs $129, rated 15000 mm."), {"facts": ["129", "15,000"]}).score == 1
    assert facts_correct(None, output("It costs $129."), {"facts": ["129", "15,000"]}).score == 0.5


def test_data_leak():
    assert no_data_leak(None, output("That belongs to Priya"), {"forbidden": ["Priya"]}).score == 0
    assert no_data_leak(None, output("I can't see that order"), {"forbidden": ["Priya"]}).score == 1


def test_right_source_requires_catalog_before_web_for_store_facts():
    expected = {"source": "catalog"}
    assert right_source(None, output(calls=[call("search_products"), call("search_web")]), expected).score == 1
    assert right_source(None, output(calls=[call("search_web"), call("get_product")]), expected).score == 0
    assert right_source(None, output(), expected).score == 0
    assert right_source(None, output(calls=[call("search_web")]), {"source": "web"}).score == 1


def test_raw_error_detection_allows_normal_refusals():
    assert no_raw_errors(None, output("I'm sorry, I can't make an exception to the policy."), {}).score == 1
    assert no_raw_errors(None, output("Got 503 from the upstream"), {}).score == 0
    assert no_raw_errors(None, output("ConnectionError while fetching"), {}).score == 0


def test_tool_reliability():
    assert tool_reliability(None, output(calls=[call("a"), call("b", ok=False)]), {}).score == 0.5
    assert tool_reliability(None, output(), {}) is None


def test_scenarios_match_the_seed_data():
    customers = {c["id"] for c in CUSTOMERS}
    orders = {o["id"]: o for o in build_orders()}
    catalog = " ".join(str(p) for p in PRODUCTS).replace(",", "")
    trackings = {o["tracking_number"] for o in orders.values()}
    for scenario in SCENARIOS:
        assert scenario.customer_id in customers
        assert scenario.mood in MOODS
        order_id = scenario.expected.get("return_order_id")
        if order_id:
            assert orders[order_id]["customer_id"] == scenario.customer_id
        for fact in scenario.expected.get("facts", []):
            assert fact in trackings or fact.replace(",", "") in catalog


def test_return_ground_truth_follows_store_policy_on_every_return_scenario():
    orders = {o["id"]: o for o in build_orders()}
    products = {p["sku"]: p for p in PRODUCTS}
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    checked = 0
    for scenario in SCENARIOS:
        if scenario.category != "return":
            continue
        order_id = scenario.goal and next(o for o in orders if o in scenario.known_facts)
        order = orders[order_id]
        delivered = datetime.fromisoformat(order["delivered_at"])
        should_allow = (now - delivered).days <= 30 and not products[order["sku"]]["final_sale"]
        assert (scenario.expected["return_order_id"] is not None) == should_allow, scenario.id
        checked += 1
    assert checked == 7


def test_holdout_covers_every_category_and_is_disjoint_from_train():
    train, holdout = by_split("train"), by_split("holdout")
    assert {s.category for s in holdout} >= {"return", "product", "order"}
    assert not {s.id for s in train} & {s.id for s in holdout}
    train_orders = {o for s in train for o in [s.expected.get("return_order_id")] if o}
    holdout_orders = {o for s in holdout for o in [s.expected.get("return_order_id")] if o}
    assert not train_orders & holdout_orders
