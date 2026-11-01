import os

from dotenv import load_dotenv

load_dotenv()

PROJECT = os.getenv("BRAINTRUST_PROJECT") or "E-commerce Support Agent"
PROMPT_SLUG = "support-agent"
PROMPT_VERSION = os.getenv("PROMPT_VERSION") or None

AGENT_MODEL = os.getenv("AGENT_MODEL") or "claude-sonnet-5-5"
SIMULATOR_MODEL = os.getenv("SIMULATOR_MODEL") or "claude-haiku-5-5"
JUDGE_MODEL = os.getenv("JUDGE_MODEL") or "claude-sonnet-5-5"

TAVILY_MCP_URL = os.getenv("TAVILY_MCP_URL") or "https://mcp.tavily.com/mcp/"

RETURN_WINDOW_DAYS = 30


def runtime_healing_default() -> bool:
    return (os.getenv("RUNTIME_HEALING") or "false").strip().lower() == "true"


def fault_rate_default() -> float:
    return float(os.getenv("FAULT_RATE") or 0)
