from typing import Any

from shopbot.config import AGENT_MODEL
from shopbot.llm import create_message, traced_client
from shopbot.tools import TOOLS, Toolbox

MAX_MODEL_CALLS_PER_TURN = 10
REFUSAL_REPLY = "I'm not able to help with that here. I can connect you with a member of our support team."
FALLBACK_REPLY = "Sorry, I couldn't finish that. Could you say that another way, or would you like a human agent?"


class SupportAgent:
    def __init__(self, toolbox: Toolbox, system_prompt: str, client: Any = None):
        self.toolbox = toolbox
        self.system_prompt = system_prompt
        self.client = client or traced_client()
        self.messages: list[dict] = []

    def respond(self, customer_message: str) -> str:
        self.messages.append({"role": "user", "content": customer_message})

        for _ in range(MAX_MODEL_CALLS_PER_TURN):
            response = create_message(
                self.client,
                model=AGENT_MODEL,
                max_tokens=16000,
                system=self.system_prompt,
                tools=TOOLS,
                messages=self.messages,
                output_config={"effort": "medium"},
                cache_control={"type": "ephemeral"},
            )
            if response.stop_reason == "refusal":
                return REFUSAL_REPLY

            # Keep the content unchanged: thinking blocks must be sent back exactly as received.
            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "pause_turn":
                continue
            if response.stop_reason != "tool_use":
                return _text_of(response) or FALLBACK_REPLY

            self.messages.append({"role": "user", "content": self._run_tools(response)})

        return FALLBACK_REPLY

    def _run_tools(self, response: Any) -> list[dict]:
        results = []
        for block in response.content:
            if block.type == "tool_use":
                content, is_error = self.toolbox.run(block.name, block.input)
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": content,
                    "is_error": is_error,
                })
        return results


def _text_of(response: Any) -> str:
    return "\n".join(block.text for block in response.content if block.type == "text").strip()
