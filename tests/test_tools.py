import json

import pytest

from shopbot.healing import RetryPolicy, TransientToolError, call_with_recovery
from shopbot.store import _search_tokens
from shopbot.tavily_mcp import CachedSearch
from shopbot.tools import TOOLS, Toolbox
from tests.fakes import FakeSearch, FakeStore


def toolbox(customer="C001", **kwargs):
    kwargs.setdefault("dry_run", True)
    return Toolbox(customer, FakeStore(), FakeSearch(), **kwargs)


def result(box, name, **args):
    content, is_error = box.run(name, args)
    return json.loads(content), is_error


def test_every_declared_tool_has_a_handler_and_no_customer_id_argument():
    for tool in TOOLS:
        assert hasattr(Toolbox, f"_{tool['name']}")
        assert "customer_id" not in tool["input_schema"]["properties"]
        assert tool["input_schema"]["additionalProperties"] is False


def test_orders_are_scoped_to_the_logged_in_customer():
    box = toolbox("C001")
    other_order, _ = result(box, "get_order", order_id="ORD-1003")
    assert other_order == {"error": "order_not_found"}
    assert result(box, "check_return_eligibility", order_id="ORD-1003")[0] == {"error": "order_not_found"}
    assert result(box, "create_return", order_id="ORD-1003", reason="x")[0] == {"error": "order_not_found"}
    assert box.actions == []


def test_dry_run_records_a_return_without_writing_and_does_not_duplicate():
    box = toolbox("C001", dry_run=True)
    first, _ = result(box, "create_return", order_id="ORD-1001", reason="changed my mind")
    second, _ = result(box, "create_return", order_id="ORD-1001", reason="again")
    assert first == second
    assert len(box.actions) == 1
    assert box.store.returns == []


def test_live_mode_writes_the_return():
    box = toolbox("C001", dry_run=False)
    result(box, "create_return", order_id="ORD-1001", reason="changed my mind")
    assert box.store.returns[0]["customer_id"] == "C001"


def test_unknown_tool_returns_an_error_instead_of_raising():
    payload, is_error = result(toolbox(), "drop_tables")
    assert is_error and payload["error"] == "invalid_tool_call"


def test_private_methods_cannot_be_called_as_tools():
    payload, is_error = result(toolbox(), "failure")
    assert is_error and payload["error"] == "invalid_tool_call"


def test_web_results_are_marked_untrusted():
    payload, _ = result(toolbox(), "search_web", query="boot care")
    assert payload["untrusted"] is True


def test_without_healing_a_fault_reaches_the_model_raw_after_one_attempt():
    box = toolbox(policy=RetryPolicy(enabled=False, fault_rate=1.0))
    payload, is_error = result(box, "search_web", query="x")
    assert is_error and "503" in payload["error"]
    assert box.calls[0]["attempts"] == 1


def test_with_healing_exhausted_retries_give_safe_guidance():
    box = toolbox(policy=RetryPolicy(enabled=True, fault_rate=1.0, sleep=lambda _: None))
    payload, is_error = result(box, "search_web", query="x")
    assert is_error and payload["error"] == "temporarily_unavailable"
    assert "503" not in json.dumps(payload)
    assert box.calls[0]["attempts"] == 3


def test_healing_retries_a_transient_failure_until_it_succeeds():
    outcomes = iter([TransientToolError("503"), TransientToolError("503"), "ok"])

    def flaky():
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    assert call_with_recovery("t", flaky, RetryPolicy(enabled=True, sleep=lambda _: None)) == ("ok", 3)


def test_healing_does_not_retry_a_permanent_failure():
    calls = []

    def broken():
        calls.append(1)
        raise PermissionError("bad key")

    with pytest.raises(Exception) as caught:
        call_with_recovery("t", broken, RetryPolicy(enabled=True, sleep=lambda _: None))
    assert caught.value.attempts == 1 and len(calls) == 1


def test_search_tokens_strip_postgrest_syntax():
    assert _search_tokens("rain,jacket).or(id.eq.1)%") == ["rain", "jacket", "or", "id", "eq", "1"]
    assert _search_tokens("***") == []


def test_cached_search_replays_and_persists(tmp_path):
    inner = FakeSearch()
    path = tmp_path / "cache.json"
    assert CachedSearch(inner, path).search("Boot  Care") == CachedSearch(inner, path).search("boot care")
    assert inner.queries == ["Boot  Care"]
