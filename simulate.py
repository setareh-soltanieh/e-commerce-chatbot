"""Generate scored production-style logs from simulated customers.

    uv run simulate.py --conversations 5        # try this first
    uv run simulate.py --conversations 200      # Topics needs about 100 or more
"""

import argparse
import random

from braintrust import TracedThreadPoolExecutor, init_logger

from shopbot.config import PROJECT, fault_rate_default, runtime_healing_default
from shopbot.conversation import run_simulated_conversation
from shopbot.healing import RetryPolicy
from shopbot.scenarios import MOODS, by_split
from shopbot.store import SupabaseStore
from shopbot.tavily_mcp import TavilyMCPSearch


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--conversations", type=int, default=5)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--healing", action=argparse.BooleanOptionalAction, default=runtime_healing_default())
    parser.add_argument("--fault-rate", type=float, default=fault_rate_default())
    args = parser.parse_args()

    logger = init_logger(project=PROJECT)
    store = SupabaseStore()
    search = TavilyMCPSearch()
    policy = RetryPolicy(enabled=args.healing, fault_rate=args.fault_rate)

    # Holdout scenarios stay out of the logs so the loop cannot fit a fix to them.
    rng = random.Random(args.seed)
    runs = [(rng.choice(by_split("train")), rng.choice(list(MOODS))) for _ in range(args.conversations)]

    def run(item):
        scenario, mood = item
        output = run_simulated_conversation(scenario, mood, store, search, policy, score_in_log=True)
        return scenario.id, mood, output["outcome"]

    failed = 0
    with TracedThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run, item) for item in runs]
        for number, future in enumerate(futures, start=1):
            try:
                scenario_id, mood, outcome = future.result()
                print(f"[{number}/{len(runs)}] {scenario_id} ({mood}): {outcome}")
            except Exception as exc:
                failed += 1
                print(f"[{number}/{len(runs)}] FAILED: {type(exc).__name__}: {exc}")

    logger.flush()
    print(f"\nFinished {len(runs) - failed} of {len(runs)} conversations.")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
