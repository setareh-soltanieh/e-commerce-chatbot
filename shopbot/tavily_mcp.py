import asyncio
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from shopbot.config import TAVILY_MCP_URL
from shopbot.healing import TransientToolError

SEARCH_TIMEOUT_SECONDS = 30

# asyncio.run needs a thread with no running event loop, and Eval may call us from one.
_mcp_thread = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tavily-mcp")


def _server_url() -> str:
    return f"{TAVILY_MCP_URL}?tavilyApiKey={os.environ['TAVILY_API_KEY']}"


async def _with_session(url: str, action):
    async with streamable_http_client(url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await action(session)


def _run(url: str, action):
    future = _mcp_thread.submit(asyncio.run, _with_session(url, action))
    return future.result(timeout=SEARCH_TIMEOUT_SECONDS)


def _search_error(exc: BaseException) -> Exception:
    # Never pass the original exception along: its text can contain the URL and API key.
    return TransientToolError(f"Tavily search failed: {type(exc).__name__}")


class TavilyMCPSearch:
    """Calls Tavily's `tavily_search` tool over MCP."""

    def __init__(self, url: str | None = None):
        self._url = url

    def search(self, query: str) -> str:
        async def action(session: ClientSession):
            return await session.call_tool("tavily_search", {"query": query, "max_results": 5})

        try:
            result = _run(self._url or _server_url(), action)
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            raise _search_error(exc) from None
        if result.is_error:
            raise TransientToolError("Tavily search returned an error")
        return "\n".join(block.text for block in result.content if block.type == "text")

    def list_tools(self) -> list:
        async def action(session: ClientSession):
            return (await session.list_tools()).tools

        return _run(self._url or _server_url(), action)


class CachedSearch:
    """Replays saved results so evals compare the agent and not a changing web."""

    def __init__(self, inner, path: str | Path = ".cache/tavily.json"):
        self._inner = inner
        self._path = Path(path)
        self._lock = threading.Lock()
        self._cache = json.loads(self._path.read_text("utf-8")) if self._path.exists() else {}

    def search(self, query: str) -> str:
        key = " ".join(query.lower().split())
        with self._lock:
            if key in self._cache:
                return self._cache[key]
        result = self._inner.search(query)
        with self._lock:
            self._cache[key] = result
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._cache, indent=1), "utf-8")
        return result
