"""Chat with the agent in a terminal. Unlike simulations, returns here are written to Supabase.

    uv run chat.py --customer C001
"""

import argparse
import uuid

from braintrust import SpanTypeAttribute, init_logger, start_span

from shopbot.agent import SupportAgent
from shopbot.config import PROJECT, fault_rate_default, runtime_healing_default
from shopbot.healing import RetryPolicy
from shopbot.prompt_store import load_system_prompt
from shopbot.store import SupabaseStore
from shopbot.tavily_mcp import TavilyMCPSearch
from shopbot.tools import Toolbox


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--customer", required=True, help="Stands in for a real login, for example C001")
    args = parser.parse_args()

    logger = init_logger(project=PROJECT)
    store = SupabaseStore()
    if not store.get_customer(args.customer):
        raise SystemExit(f"No customer {args.customer}. Run seed.py, or pass an existing customer ID.")

    policy = RetryPolicy(enabled=runtime_healing_default(), fault_rate=fault_rate_default())
    toolbox = Toolbox(args.customer, store, TavilyMCPSearch(), policy)
    system_prompt, prompt_version = load_system_prompt()
    agent = SupportAgent(toolbox, system_prompt)

    print(f"Juniper & Pine support, prompt version {prompt_version}. Type 'quit' to exit.\n")
    transcript = []
    with start_span(name="conversation", type=SpanTypeAttribute.TASK) as span:
        turn = 0
        try:
            while (text := input("You: ").strip()).lower() != "quit":
                if not text:
                    continue
                turn += 1
                with start_span(name=f"turn_{turn}", type=SpanTypeAttribute.TASK, input=text) as turn_span:
                    reply = agent.respond(text)
                    turn_span.log(output=reply, metadata={"turn_number": turn})
                transcript += [{"role": "customer", "content": text}, {"role": "agent", "content": reply}]
                print(f"\nAgent: {reply}\n")
        except (EOFError, KeyboardInterrupt):
            pass
        span.log(
            input=[entry["content"] for entry in transcript if entry["role"] == "customer"],
            output=transcript,
            metadata={"session_id": str(uuid.uuid4()), "customer_id": args.customer, "total_turns": turn,
                      "prompt_version": prompt_version, "healing": policy.enabled},
        )
    logger.flush()


if __name__ == "__main__":
    main()
