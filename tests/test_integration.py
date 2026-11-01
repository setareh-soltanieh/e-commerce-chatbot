"""Exercise the real Anthropic, Braintrust and MCP libraries against local servers."""

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import anthropic
import pytest
import uvicorn
from braintrust import Eval, wrap_anthropic
from mcp.server.mcpserver import MCPServer

from shopbot import prompt_store
from shopbot.agent import REFUSAL_REPLY, SupportAgent
from shopbot.conversation import run_simulated_conversation
from shopbot.healing import RetryPolicy, TransientToolError
from shopbot.scenarios import SCENARIOS_BY_ID
from shopbot.tavily_mcp import TavilyMCPSearch
from shopbot.tools import Toolbox
from tests.fakes import FakeSearch, FakeStore


def _message(content, stop_reason):
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5", "content": content,
            "stop_reason": stop_reason, "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}}


THINKING = {"type": "thinking", "thinking": "", "signature": "sig-123"}
TOOL_USE = {"type": "tool_use", "id": "toolu_1", "name": "get_order", "input": {"order_id": "ORD-1001"}}


@pytest.fixture
def api():
    """A mock Messages API. Set `api.replies`; requests land in `api.requests`."""

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            self.server.requests.append({"path": self.path, "beta": self.headers.get("anthropic-beta"), "body": body})
            payload = json.dumps(self.server.replies.pop(0)).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.replies, server.requests = [], []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server
    server.shutdown()


def _client(server):
    return anthropic.Anthropic(api_key="test", base_url=f"http://127.0.0.1:{server.server_port}", max_retries=0)


def _agent(server, **toolbox_args):
    toolbox = Toolbox("C001", FakeStore(), FakeSearch(), dry_run=True, **toolbox_args)
    return SupportAgent(toolbox, "system prompt", wrap_anthropic(_client(server))), toolbox


def test_haiku_requests_omit_the_server_side_fallback(api):
    from shopbot.llm import create_json

    api.replies.append(_judge_reply())
    create_json(_client(api), model="claude-haiku-5-5", system="s", prompt="p", schema={"type": "object"})
    assert "fallbacks" not in api.requests[0]["body"]
    assert "server-side-fallback" not in (api.requests[0]["beta"] or "")


def test_agent_tool_loop_round_trips_history_through_the_real_sdk(api, monkeypatch):
    monkeypatch.setattr("shopbot.agent.AGENT_MODEL", "claude-opus-5-5")
    api.replies += [
        _message([THINKING, TOOL_USE], "tool_use"),
        _message([THINKING, {"type": "text", "text": "It was delivered."}], "end_turn"),
        _message([{"type": "text", "text": "You're welcome."}], "end_turn"),
    ]
    agent, toolbox = _agent(api)

    assert agent.respond("Where is my order?") == "It was delivered."
    assert agent.respond("Thanks") == "You're welcome."

    first, second, third = (request["body"] for request in api.requests)
    assert api.requests[0]["path"].startswith("/v1/messages")
    assert "server-side-fallback-2026-07-01" in api.requests[0]["beta"]
    assert first["fallbacks"] == "default"
    assert first["output_config"] == {"effort": "medium"}
    assert first["cache_control"] == {"type": "ephemeral"}
    assert first["tools"][0]["strict"] is True

    # Thinking and tool_use blocks are replayed unchanged, followed by one tool_result message.
    assert second["messages"][1]["content"][0]["signature"] == "sig-123"
    assert second["messages"][1]["content"][1]["id"] == "toolu_1"
    result = second["messages"][2]["content"][0]
    assert result["tool_use_id"] == "toolu_1" and result["is_error"] is False
    assert json.loads(result["content"])["id"] == "ORD-1001"
    # The next turn is append-only: every earlier message is still there, in order.
    assert third["messages"][:4] == second["messages"][:3] + [third["messages"][3]]
    assert third["messages"][-1] == {"role": "user", "content": "Thanks"}
    assert toolbox.calls[0]["name"] == "get_order"


def test_refusal_returns_a_safe_reply_and_the_next_turn_still_works(api):
    api.replies += [
        _message([], "refusal"),
        _message([{"type": "text", "text": "Sure."}], "end_turn"),
    ]
    agent, _ = _agent(api)
    assert agent.respond("bad request") == REFUSAL_REPLY
    assert agent.respond("how about this") == "Sure."


def _simulator_reply(message, status="continue", mood="angry"):
    text = json.dumps({"message": message, "mood": mood, "status": status})
    return _message([{"type": "text", "text": text}], "end_turn")


def _judge_reply(verdict="yes"):
    text = json.dumps({"rationale": "because", "verdict": verdict})
    return _message([{"type": "text", "text": text}], "end_turn")


def test_full_simulated_conversation_and_eval_offline(api, monkeypatch):
    monkeypatch.setattr(prompt_store, "load_prompt", lambda **_: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr("shopbot.scorers.plain_client", lambda: _client(api))
    scenario = SCENARIOS_BY_ID["return_recent"]
    store = FakeStore()
    create_return = {"type": "tool_use", "id": "toolu_2", "name": "create_return",
                     "input": {"order_id": "ORD-1001", "reason": "Don't want it"}}
    # Requests are sequential here: customer, agent + tool, agent, customer closes, then two judges.
    api.replies += [
        _simulator_reply("I want to return my boots. ORD-1001."),
        _message([create_return], "tool_use"),
        _message([{"type": "text", "text": "Your return is approved."}], "end_turn"),
        _simulator_reply("Thanks.", status="satisfied", mood="calm"),
        _judge_reply("yes"),
        _judge_reply("partly"),
    ]

    def task(input):
        return run_simulated_conversation(
            scenario, input["mood"], store, FakeSearch(), RetryPolicy(),
            client=wrap_anthropic(_client(api)), simulator_client=_client(api),
        )

    from shopbot.scorers import SCORERS

    result = Eval(
        "offline-test",
        data=[{"input": {"mood": "angry"}, "expected": scenario.expected}],
        task=task,
        scores=SCORERS,
        no_send_logs=True,
    )
    row = result.results[0]
    assert row.error is None
    assert row.output["outcome"] == "satisfied"
    assert row.output["final_mood"] == "calm"
    assert [turn["role"] for turn in row.output["transcript"]] == ["customer", "agent", "customer"]
    assert row.scores["correct_return_decision"] == 1
    assert row.scores["issue_resolved"] == 1
    assert row.scores["tone_fits_mood"] == 0.5
    assert store.returns == []  # a simulation never writes


def test_prompt_store_reads_text_and_version_from_a_braintrust_prompt(monkeypatch):
    from braintrust import Prompt
    from braintrust.prompt import PromptChatBlock, PromptData, PromptMessage

    data = PromptData(prompt=PromptChatBlock(messages=[PromptMessage(role="system", content="Be kind.")]),
                      options={"model": "claude-opus-5-5"})
    prompt = Prompt.from_prompt_data("Support Agent", data)
    monkeypatch.setattr(prompt_store, "load_prompt", lambda **_: prompt)
    text, _ = prompt_store.load_system_prompt()
    assert text == "Be kind."


def test_prompt_store_falls_back_to_the_local_file(monkeypatch):
    monkeypatch.setattr(prompt_store, "load_prompt", lambda **_: (_ for _ in ()).throw(RuntimeError("down")))
    text, version = prompt_store.load_system_prompt()
    assert version == "local" and "Juniper & Pine" in text


@pytest.fixture
def mcp_url():
    server = MCPServer("fake-tavily")

    @server.tool()
    def tavily_search(query: str, max_results: int = 5) -> str:
        if query == "fail":
            raise ValueError("search backend error")
        return f"{max_results} results for {query}"

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    uv = uvicorn.Server(uvicorn.Config(server.streamable_http_app(), host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=uv.run, daemon=True)
    thread.start()
    for _ in range(100):
        if uv.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/mcp"
    uv.should_exit = True
    thread.join(timeout=5)


def test_search_works_over_a_real_mcp_connection(mcp_url):
    search = TavilyMCPSearch(mcp_url)
    assert "tavily_search" in {tool.name for tool in search.list_tools()}
    assert search.search("boot care") == "5 results for boot care"


def test_mcp_tool_error_is_transient(mcp_url):
    with pytest.raises(TransientToolError):
        TavilyMCPSearch(mcp_url).search("fail")


def test_connection_failure_is_transient_and_hides_the_url():
    secret_url = "http://127.0.0.1:9/mcp?tavilyApiKey=SECRET"
    with pytest.raises(TransientToolError) as caught:
        TavilyMCPSearch(secret_url).search("x")
    assert "SECRET" not in str(caught.value)
