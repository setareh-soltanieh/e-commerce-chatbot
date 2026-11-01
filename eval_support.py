"""Run the locked scorers against the current prompt and code.

    uv run eval_support.py --split train
    uv run eval_support.py --split holdout --trials 3
    uv run eval_support.py --dataset "Failed returns"     # a dataset Loop built from logs
"""

import argparse

from braintrust import Eval, init_dataset

from shopbot.config import PROJECT, fault_rate_default, runtime_healing_default
from shopbot.conversation import run_simulated_conversation
from shopbot.healing import RetryPolicy
from shopbot.prompt_store import load_system_prompt
from shopbot.scenarios import MOODS, SCENARIOS_BY_ID, Scenario, by_split
from shopbot.scorers import SCORERS
from shopbot.store import SupabaseStore
from shopbot.tavily_mcp import CachedSearch, TavilyMCPSearch


def _case(scenario: Scenario, mood: str) -> dict:
    return {
        "input": {"scenario_id": scenario.id, "mood": mood},
        "expected": scenario.expected,
        "metadata": {"split": scenario.split, "category": scenario.category},
    }


def cases_from_dataset(rows) -> tuple[list[dict], int]:
    """Replay dataset rows by scenario. Rows logged by simulate.py carry the IDs needed."""
    cases, skipped = [], 0
    for row in rows:
        metadata = row.get("metadata") or {}
        scenario = SCENARIOS_BY_ID.get(metadata.get("scenario_id"))
        if scenario is None:
            skipped += 1
            continue
        mood = metadata.get("starting_mood")
        cases.append(_case(scenario, mood if mood in MOODS else scenario.mood))
    return cases, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["train", "holdout"], default="train")
    parser.add_argument("--dataset", help="Name of a Braintrust dataset to use instead of --split")
    parser.add_argument("--trials", type=int, default=1, help="Runs per case, to separate real changes from noise")
    parser.add_argument("--healing", action=argparse.BooleanOptionalAction, default=runtime_healing_default())
    parser.add_argument("--fault-rate", type=float, default=fault_rate_default())
    args = parser.parse_args()

    if args.dataset:
        cases, skipped = cases_from_dataset(init_dataset(project=PROJECT, name=args.dataset))
        if skipped:
            print(f"Skipped {skipped} rows with no known metadata.scenario_id.")
        if not cases:
            raise SystemExit(f"Dataset {args.dataset!r} has no rows that can be replayed.")
    else:
        cases = [_case(scenario, scenario.mood) for scenario in by_split(args.split)]

    store = SupabaseStore()
    search = CachedSearch(TavilyMCPSearch())
    policy = RetryPolicy(enabled=args.healing, fault_rate=args.fault_rate)
    _, prompt_version = load_system_prompt()
    data_name = args.dataset or args.split

    def task(input):
        return run_simulated_conversation(SCENARIOS_BY_ID[input["scenario_id"]], input["mood"], store, search, policy)

    Eval(
        PROJECT,
        data=cases,
        task=task,
        scores=SCORERS,
        experiment_name=f"{data_name}-prompt-{prompt_version}-healing-{'on' if args.healing else 'off'}",
        trial_count=args.trials,
        max_concurrency=4,
        metadata={"data": data_name, "prompt_version": prompt_version, "healing": args.healing,
                  "fault_rate": args.fault_rate},
    )


if __name__ == "__main__":
    main()
