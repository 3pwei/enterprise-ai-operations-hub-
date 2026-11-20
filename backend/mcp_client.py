import json
import os
import sys
from typing import Any

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, TextContent

from backend.config import settings

SERVER = {"production_kpi": "data", "quality_issues": "data", "sales_analysis": "data",
          "inventory": "erp", "order_status": "erp", "approval_rules": "eip", "approval_status": "eip"}


async def call_tool(tool: str, capability: str, params: dict[str, Any]) -> dict[str, Any]:
    if tool not in SERVER:
        raise ValueError("Unknown tool")
    target = SERVER[tool]
    urls = {"data": settings().mcp_data_url, "erp": settings().mcp_erp_url,
            "eip": settings().mcp_eip_url}
    if url := urls[target]:
        # Internal Compose addresses must not be sent through the host's HTTP proxy.
        async with httpx.AsyncClient(timeout=10, trust_env=False) as http_client:
            async with streamable_http_client(url, http_client=http_client) as (read, write, _):
                async with ClientSession(read, write) as client:
                    response = await _request(client, tool, capability, params)
    else:
        # Local development and existing stdio tests can still run without Compose.
        env = {**os.environ, "DATABASE_URL": settings().database_url,
               "MCP_SIGNING_KEY": settings().mcp_signing_key}
        server = StdioServerParameters(command=sys.executable,
            args=["-m", f"backend.mcp_servers.{target}"], env=env)
        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write) as client:
                response = await _request(client, tool, capability, params)
    return _decode(response)


async def _request(client: ClientSession, tool: str, capability: str,
                   params: dict[str, Any]) -> CallToolResult:
    await client.initialize()
    return await client.call_tool(tool, {"capability": capability, **params})


def _decode(response: CallToolResult) -> dict[str, Any]:
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
