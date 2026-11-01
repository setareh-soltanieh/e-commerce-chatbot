"""Check every external connection before spending money on a simulation.

    uv run doctor.py
"""

import os
import traceback

import anthropic
from braintrust import init_logger

from shopbot.config import AGENT_MODEL, PROJECT
from shopbot.prompt_store import load_system_prompt
from shopbot.seed_data import build_orders
from shopbot.store import SupabaseStore
from shopbot.tavily_mcp import TavilyMCPSearch

REQUIRED = ["ANTHROPIC_API_KEY", "BRAINTRUST_API_KEY", "TAVILY_API_KEY", "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]


def check_anthropic() -> str:
    response = anthropic.Anthropic().messages.create(
        model=AGENT_MODEL, max_tokens=200, messages=[{"role": "user", "content": "Reply with OK."}],
    )
    return f"{response.model} replied"


def check_supabase() -> str:
    store = SupabaseStore()
    order = store.get_order("C001", "ORD-1001")
    if not order or not order.get("products"):
        raise RuntimeError("ORD-1001 not found. Run supabase/schema.sql, then seed.py.")
    other = store.get_order("C002", "ORD-1001")
    if other:
        raise RuntimeError("An order was returned for the wrong customer.")
    return f"demo data found ({len(build_orders())} orders expected)"


def check_tavily() -> str:
    search = TavilyMCPSearch()
    tools = {tool.name: tool for tool in search.list_tools()}
    if "tavily_search" not in tools:
        raise RuntimeError(f"tavily_search is missing. Server offers: {sorted(tools)}")
    return f"{len(search.search('how to clean leather hiking boots'))} characters of search results"


def check_braintrust() -> str:
    logger = init_logger(project=PROJECT)
    with logger.start_span(name="doctor") as span:
        span.log(input="connection check", output="ok")
    logger.flush()
    _, version = load_system_prompt()
    if version == "local":
        return "logging works, but the prompt isn't published yet. Run push_prompt.py."
    return f"logging works, prompt version {version}"


def main() -> None:
    missing = [name for name in REQUIRED if not os.environ.get(name)]
    if missing:
        raise SystemExit(f"Missing from .env: {', '.join(missing)}")

    failed = False
    for name, check in [("Anthropic", check_anthropic), ("Supabase", check_supabase),
                        ("Tavily MCP", check_tavily), ("Braintrust", check_braintrust)]:
        try:
            print(f"PASS  {name}: {check()}")
        except Exception as exc:
            failed = True
            print(f"FAIL  {name}: {type(exc).__name__}: {exc}")
            if os.environ.get("DOCTOR_DEBUG"):
                traceback.print_exc()
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
