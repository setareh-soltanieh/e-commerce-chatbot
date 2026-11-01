import json
from functools import lru_cache
from typing import Any

import anthropic
from braintrust import wrap_anthropic

FALLBACK_BETA = "server-side-fallback-2026-07-01"


@lru_cache
def traced_client():
    """For the agent: every call appears as an LLM span in Braintrust."""
    return wrap_anthropic(anthropic.Anthropic())


@lru_cache
def plain_client():
    """For the simulator and judges, so their calls stay out of the agent's traces."""
    return anthropic.Anthropic()


def create_message(client: Any, *, model: str, **params: Any):
    # A safety decline reruns on Anthropic's recommended model instead of ending the turn.
    # Haiku has no server-side fallback.
    if "haiku" not in model:
        params |= {"betas": [FALLBACK_BETA], "fallbacks": "default"}
    return client.beta.messages.create(model=model, **params)


def create_json(client: Any, *, model: str, system: str, prompt: str, schema: dict) -> dict | None:
    """Return a schema-valid object, or None if the model declined."""
    response = create_message(
        client,
        model=model,
        max_tokens=4000,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
    )
    if response.stop_reason == "refusal":
        return None
    return json.loads(next(block.text for block in response.content if block.type == "text"))
