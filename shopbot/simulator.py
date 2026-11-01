from typing import Any

from shopbot.config import SIMULATOR_MODEL
from shopbot.llm import create_json, plain_client
from shopbot.scenarios import MOODS, Scenario

SCHEMA = {
    "type": "object",
    "properties": {
        "message": {"type": "string"},
        "mood": {"type": "string", "enum": list(MOODS)},
        "status": {"type": "string", "enum": ["continue", "satisfied", "gave_up"]},
    },
    "required": ["message", "mood", "status"],
    "additionalProperties": False,
}

SYSTEM = """You are role-playing a customer in a test of a store's support chatbot. Write only the customer's next chat message.

Stay in character. Do not help the chatbot by volunteering facts it did not ask for, and never invent an order number, purchase or detail beyond what you know.

Your mood can change: a good reply can calm you down, and a repeated question or unhelpful answer can make you more upset. Report your current mood.

Set status to "satisfied" when your goal is met or you accept the final answer, and "gave_up" if you stop trying. Otherwise set it to "continue". The message for those two statuses is your closing line."""


class SimulatedCustomer:
    def __init__(self, scenario: Scenario, mood: str, client: Any = None):
        self.scenario = scenario
        self.mood = mood
        self.client = client or plain_client()

    def next_message(self, transcript: list[dict]) -> dict:
        history = "\n".join(f"{turn['role'].upper()}: {turn['content']}" for turn in transcript) or "(You are starting the chat.)"
        result = create_json(
            self.client,
            model=SIMULATOR_MODEL,
            system=SYSTEM,
            prompt=(
                f"<goal>{self.scenario.goal}</goal>\n"
                f"<what_you_know>{self.scenario.known_facts}</what_you_know>\n"
                f"<current_mood>{self.mood}: {MOODS[self.mood]}</current_mood>\n"
                f"<chat_so_far>\n{history}\n</chat_so_far>"
            ),
            schema=SCHEMA,
        )
        if result is None:
            return {"message": "", "mood": self.mood, "status": "gave_up"}
        self.mood = result["mood"]
        return result
