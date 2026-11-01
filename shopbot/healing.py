"""Fault injection and runtime recovery for tool calls."""

import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


class TransientToolError(Exception):
    """A failure that may succeed if the call is retried."""


class ToolUnavailable(Exception):
    """Retries ran out, or the failure cannot be fixed by retrying."""

    def __init__(self, tool: str, attempts: int, cause: Exception):
        super().__init__(str(cause))
        self.tool = tool
        self.attempts = attempts


@dataclass
class RetryPolicy:
    enabled: bool = False
    fault_rate: float = 0.0
    max_attempts: int = 3
    base_delay: float = 0.5
    sleep: Callable[[float], None] = time.sleep


def is_transient(exc: Exception) -> bool:
    if isinstance(exc, (TransientToolError, TimeoutError, ConnectionError)):
        return True
    # The HTTP clients under Supabase and MCP name their network failures this way.
    if any(marker in type(exc).__name__ for marker in ("Timeout", "Connect", "RemoteProtocol", "ReadError")):
        return True
    code = str(getattr(exc, "code", "") or "")
    return code.isdigit() and code.startswith("5")


def _maybe_inject_fault(tool: str, rate: float) -> None:
    if rate > 0 and random.random() < rate:
        raise TransientToolError(f"503 Service Unavailable: upstream connect error while calling {tool}")


def call_with_recovery(tool: str, fn: Callable[[], Any], policy: RetryPolicy) -> tuple[Any, int]:
    """Return (result, attempts). Raise ToolUnavailable once the call has failed for good."""
    max_attempts = policy.max_attempts if policy.enabled else 1
    for attempt in range(1, max_attempts + 1):
        try:
            _maybe_inject_fault(tool, policy.fault_rate)
            return fn(), attempt
        except Exception as exc:
            if attempt == max_attempts or not is_transient(exc):
                raise ToolUnavailable(tool, attempt, exc) from exc
            policy.sleep(policy.base_delay * 2 ** (attempt - 1))
    raise AssertionError("unreachable")
