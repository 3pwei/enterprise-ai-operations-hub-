import json
import os
import sys
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent

from backend.config import settings

SERVER = {"production_kpi": "data", "quality_issues": "data", "sales_analysis": "data",
          "inventory": "erp", "order_status": "erp", "approval_rules": "eip", "approval_status": "eip"}


async def call_tool(tool: str, capability: str, params: dict[str, Any]) -> dict[str, Any]:
    if tool not in SERVER:
        raise ValueError("Unknown tool")
    env = {**os.environ, "DATABASE_URL": settings().database_url,
           "MCP_SIGNING_KEY": settings().mcp_signing_key}
    server = StdioServerParameters(command=sys.executable,
        args=["-m", f"backend.mcp_servers.{SERVER[tool]}"], env=env)
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()
            response = await client.call_tool(tool, {"capability": capability, **params})
            if response.isError:
                raise ValueError("MCP tool failed or access denied")
            # FastMCP returns structured content for dict results; accept text as a compatibility fallback.
            if response.structuredContent:
                payload = response.structuredContent
                return payload.get("result", payload)
            content = next((item for item in response.content if isinstance(item, TextContent)), None)
            if content is None:
                raise ValueError("MCP tool returned no text")
            return json.loads(content.text)
