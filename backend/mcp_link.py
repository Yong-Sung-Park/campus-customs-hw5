"""One MCP connection to mcp_server/server.py, shared by the agents and the API routes.

Agents get filtered views of this toolset (see team.TOOL_ACCESS). Routes call
tools through `call_tool`, so even the human approve button changes cash via
the MCP server, never by touching SQLite directly.
"""

import json
import os
import sys
from pathlib import Path
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from pydantic_ai.mcp import MCPToolset

REPO_DIR = Path(__file__).resolve().parent.parent
SERVER_SCRIPT = REPO_DIR / "mcp_server" / "server.py"


def make_toolset() -> MCPToolset:
    transport = StdioTransport(
        command=sys.executable,  # the backend's own .venv python, which has fastmcp installed
        args=[str(SERVER_SCRIPT)],
        # CAMPUS_CUSTOMS_DB lets a smoke test point the server at a scratch copy.
        env={"PYTHONUTF8": "1", **({"CAMPUS_CUSTOMS_DB": os.environ["CAMPUS_CUSTOMS_DB"]} if os.environ.get("CAMPUS_CUSTOMS_DB") else {})},
        cwd=str(REPO_DIR),
        keep_alive=True,
    )
    return MCPToolset(Client(transport), id="campus-customs", max_retries=1)


TOOLSET = make_toolset()


def _decode(result: Any) -> Any:
    """direct_call_tool may hand back a dict, a JSON string, or content blocks."""
    if isinstance(result, (dict, list)):
        return result
    if isinstance(result, str):
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return {"text": result}
    text = getattr(result, "text", None)
    if text is not None:
        return _decode(text)
    return result


async def call_tool(name: str, args: dict | None = None) -> Any:
    return _decode(await TOOLSET.direct_call_tool(name, args or {}))
