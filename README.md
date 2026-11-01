# Self-improving e-commerce support agent

A multi-turn support chatbot for Juniper & Pine, a fictional outdoor-gear store. It handles returns, order questions and product discovery. Braintrust traces and scores every conversation, and Loop finds failures and proposes fixes, which a person approves.

Based on Braintrust's [Finding Production Issues](https://docs.braintrust.dev/cookbook/recipes/FindingProductionIssues) recipe, with simulated customer moods, ground-truth scorers, a holdout set and runtime recovery added.

## How it works

| Part | File | Notes |
|------|------|-------|
| Agent loop | `shopbot/agent.py` | Claude with tools; loads its system prompt from Braintrust at the start of each chat |
| Tools | `shopbot/tools.py` | Every tool is bound to one customer; the model never supplies a customer ID |
| Data | `shopbot/store.py`, `supabase/schema.sql` | Customers, products, orders, returns, tickets, policies |
| Web search | `shopbot/tavily_mcp.py` | Tavily over MCP |
| Runtime recovery | `shopbot/healing.py` | Retries, safe error messages and fault injection |
| Simulated customers | `shopbot/simulator.py`, `shopbot/scenarios.py` | Five moods that can shift during a chat; train and holdout scenarios |
| Scorers | `shopbot/scorers.py` | Locked. Six check ground truth or tool results, two are LLM judges |

Simulations and evals never write to the database: returns are recorded in memory. Only `chat.py` writes returns and tickets.

## Setup

1. In the Supabase SQL editor, run `supabase/schema.sql`.
2. Copy `.env.example` to `.env` and fill in the keys.
3. Run:

```
uv sync
uv run seed.py
uv run push_prompt.py
uv run doctor.py
uv run pytest
```

`doctor.py` checks all four services. Re-run `seed.py` at least every 3 weeks, because the demo dates are relative to when it last ran.

To let Loop open pull requests, put this folder in a GitHub repository and connect it to the Braintrust project.

## Running the demo

### 1. Baseline

```
uv run simulate.py --conversations 5
uv run eval_support.py --split train
uv run eval_support.py --split holdout
```

Check the five conversations in Braintrust and note the cost per conversation. Then generate enough logs for Topics, which needs about 100 or more traces:

```
uv run simulate.py --conversations 200
```

### 2. Find the failures with Loop

Open Loop on the project's Logs page and ask:

> Using the scores on recent logs and the Topics clusters, what are the most common ways this agent fails customers? Rank them by how often they happen, and quote example conversations. Separate problems in the system prompt from problems that look like bugs in tool results.

### 3. Fix the prompt

> Create a dataset called "Failed conversations" from logs where correct_return_decision, right_source or tone_fits_mood is below 1. Keep each row's metadata. Then propose an edit to the support-agent prompt that fixes the causes you found. Do not change any scorers.

Review and approve the edit. The agent uses the new version on its next conversation, with no deploy.

### 4. Fix the code

> The tool spans show check_return_eligibility giving results that conflict with the store's return policy. Find the root cause in the connected repository and open a pull request with a fix and tests. Do not change shopbot/scorers.py or shopbot/scenarios.py.

Review and merge the pull request.

### 5. Prove it

```
uv run eval_support.py --dataset "Failed conversations"
uv run eval_support.py --split train --trials 3
uv run eval_support.py --split holdout --trials 3
```

Compare the experiments in Braintrust. The holdout run is the headline number, because those scenarios were never in the logs Loop learned from.

### 6. Show runtime recovery

```
uv run eval_support.py --split train --no-healing --fault-rate 0.3
uv run eval_support.py --split train --healing --fault-rate 0.3
```

Compare `tool_reliability` and `no_raw_errors` between the two runs. Tool spans record `attempts` for each call.

### 7. Run it continuously (optional)

Set up a Braintrust automation that runs Loop on a schedule to check new logs. Keep approvals on for anything that changes the prompt.

## Rules that keep the results honest

- **Keep Loop away from the tests.** `shopbot/scorers.py` and `shopbot/scenarios.py` define what correct means. Reject any pull request that changes them to raise a score.
- **Judge on the holdout set.** `simulate.py` only runs train scenarios.
- **Expect noise.** Use `--trials 3` before trusting a small change. Evals replay cached Tavily results from `.cache/tavily.json` to reduce variation.

## Other commands

```
uv run chat.py --customer C001        # chat yourself; this writes to Supabase
uv run push_prompt.py --reset         # restore the baseline prompt as a new version
```

`--customer` stands in for a real login. A production deployment must take the customer ID from an authenticated session.
