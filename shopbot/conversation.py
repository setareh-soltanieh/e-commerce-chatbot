from typing import Any

from braintrust import SpanTypeAttribute, start_span

from shopbot.agent import SupportAgent
from shopbot.healing import RetryPolicy
from shopbot.prompt_store import load_system_prompt
from shopbot.scenarios import Scenario
from shopbot.scorers import score_conversation
from shopbot.simulator import SimulatedCustomer
from shopbot.tools import Toolbox

MAX_TURNS = 6


def run_simulated_conversation(
    scenario: Scenario,
    mood: str,
    store: Any,
    search: Any,
    policy: RetryPolicy,
    *,
    score_in_log: bool = False,
    client: Any = None,
    simulator_client: Any = None,
) -> dict:
    """Run one customer chat as one trace, with a child span for each turn. Nothing is written to the database."""
    with start_span(name="conversation", type=SpanTypeAttribute.TASK) as span:
        system_prompt, prompt_version = load_system_prompt()
        toolbox = Toolbox(scenario.customer_id, store, search, policy, dry_run=True)
        agent = SupportAgent(toolbox, system_prompt, client)
        customer = SimulatedCustomer(scenario, mood, simulator_client)

        transcript: list[dict] = []
        outcome = "turn_limit"
        for turn in range(1, MAX_TURNS + 1):
            step = customer.next_message(transcript)
            if step["message"]:
                transcript.append({"role": "customer", "content": step["message"]})
            if step["status"] != "continue":
                outcome = step["status"]
                break
            with start_span(name=f"turn_{turn}", type=SpanTypeAttribute.TASK, input=step["message"]) as turn_span:
                reply = agent.respond(step["message"])
                turn_span.log(output=reply, metadata={"turn_number": turn, "customer_mood": step["mood"]})
            transcript.append({"role": "agent", "content": reply})

        output = {
            "transcript": transcript,
            "actions": toolbox.actions,
            "tool_calls": toolbox.calls,
            "outcome": outcome,
            "final_mood": customer.mood,
            "resolved_when": scenario.resolved_when,
        }
        metadata = {
            "scenario_id": scenario.id,
            "split": scenario.split,
            "category": scenario.category,
            "customer_id": scenario.customer_id,
            "starting_mood": mood,
            "final_mood": customer.mood,
            "customer_outcome": outcome,
            "total_turns": sum(turn["role"] == "customer" for turn in transcript),
            "prompt_version": prompt_version,
            "healing": policy.enabled,
            "fault_rate": policy.fault_rate,
        }
        span.log(
            input=[turn["content"] for turn in transcript if turn["role"] == "customer"],
            output=transcript,
            metadata=metadata,
        )
        if score_in_log:
            scores, details = score_conversation(output, scenario.expected)
            span.log(scores=scores, metadata={"score_details": details})
        return output
