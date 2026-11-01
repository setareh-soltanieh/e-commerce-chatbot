"""Publish the baseline prompt to Braintrust so Loop can see and improve it.

    uv run push_prompt.py            # create it if it doesn't exist
    uv run push_prompt.py --reset    # add a new version that restores the baseline, to rerun the demo
"""

import argparse

from braintrust import projects

from shopbot.config import AGENT_MODEL, PROJECT, PROMPT_SLUG
from shopbot.prompt_store import LOCAL_PROMPT_PATH


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    project = projects.create(name=PROJECT)
    project.prompts.create(
        name="Support Agent",
        slug=PROMPT_SLUG,
        description="System prompt for the e-commerce support agent. The agent loads the latest version.",
        messages=[{"role": "system", "content": LOCAL_PROMPT_PATH.read_text("utf-8")}],
        model=AGENT_MODEL,
        if_exists="replace" if args.reset else "ignore",
    )
    project.publish()
    print(f"Prompt '{PROMPT_SLUG}' is published in project '{PROJECT}'.")


if __name__ == "__main__":
    main()
