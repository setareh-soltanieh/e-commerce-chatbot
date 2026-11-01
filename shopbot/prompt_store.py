import logging
from pathlib import Path

from braintrust import load_prompt

from shopbot.config import PROJECT, PROMPT_SLUG, PROMPT_VERSION

log = logging.getLogger(__name__)

LOCAL_PROMPT_PATH = Path(__file__).parent / "prompts" / "support_agent_v1.md"


def load_system_prompt() -> tuple[str, str]:
    """Return (text, version). Loop's approved prompt edits take effect from here, with no deploy.

    If Braintrust cannot be reached, support keeps running on the local copy.
    """
    try:
        prompt = load_prompt(project=PROJECT, slug=PROMPT_SLUG, version=PROMPT_VERSION)
        return prompt.build()["messages"][0]["content"], str(prompt.version)
    except Exception as exc:
        log.warning("Using the local prompt because Braintrust's could not be loaded: %s", exc)
        return LOCAL_PROMPT_PATH.read_text("utf-8"), "local"
