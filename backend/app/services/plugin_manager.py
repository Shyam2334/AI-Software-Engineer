"""MCP (Model Context Protocol) plugin manager."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import httpx
from sqlmodel import select

from app.database import get_session
from app.models import Plugin

logger = logging.getLogger(__name__)


class MCPPlugin:
    """Represents a loaded MCP plugin with its tools."""

    def __init__(self, name: str, endpoint_url: str, tools: List[Dict[str, Any]]) -> None:
        self.name = name
        self.endpoint_url = endpoint_url
        self.tools = tools

    def get_tool_names(self) -> List[str]:
        """Return list of available tool names."""
        return [t.get("name", "") for t in self.tools]


class PluginManager:
    """Discovers, manages, and calls MCP plugins."""

    def __init__(self) -> None:
        self._plugins: Dict[str, MCPPlugin] = {}
        self._http_client: Optional[httpx.AsyncClient] = None

    @property
    def http_client(self) -> httpx.AsyncClient:
        """Lazy-initialize the HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=30.0)
        return self._http_client

    async def discover_tools(self, endpoint_url: str) -> List[Dict[str, Any]]:
        """Discover available tools from an MCP plugin endpoint.

        Args:
            endpoint_url: The plugin's JSON-RPC endpoint URL.

        Returns:
            List of tool definitions.
        """
        try:
            response = await self.http_client.post(
                endpoint_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/list",
                    "params": {},
                },
            )
            response.raise_for_status()
            data = response.json()

            tools = data.get("result", {}).get("tools", [])
            logger.info(
                "Discovered %d tools from %s", len(tools), endpoint_url
            )
            return tools

        except Exception as e:
            logger.error("Tool discovery failed for %s: %s", endpoint_url, e)
            return []

    async def call_tool(
        self,
        endpoint_url: str,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Call a tool on an MCP plugin.

        Args:
            endpoint_url: The plugin's JSON-RPC endpoint URL.
            tool_name: Name of the tool to call.
            arguments: Tool arguments.

        Returns:
            Tool execution result.
        """
        try:
            response = await self.http_client.post(
                endpoint_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": tool_name,
                        "arguments": arguments,
                    },
                },
            )
            response.raise_for_status()
            data = response.json()

            if "error" in data:
                logger.error("Tool call error: %s", data["error"])
                return {"error": data["error"]}

            return data.get("result", {})

        except Exception as e:
            logger.error("Tool call failed (%s.%s): %s", endpoint_url, tool_name, e)
            return {"error": str(e)}

    async def register_plugin(
        self, name: str, endpoint_url: str, description: str = ""
    ) -> Plugin:
        """Register a new MCP plugin and discover its tools.

        Args:
            name: Plugin name.
            endpoint_url: JSON-RPC endpoint.
            description: Plugin description.

        Returns:
            The created Plugin record.
        """
        tools = await self.discover_tools(endpoint_url)

        async with get_session() as session:
            plugin = Plugin(
                name=name,
                endpoint_url=endpoint_url,
                description=description,
                enabled=True,
                tools_json=json.dumps(tools),
            )
            session.add(plugin)
            await session.commit()
            await session.refresh(plugin)

        # Cache in memory
        self._plugins[name] = MCPPlugin(
            name=name,
            endpoint_url=endpoint_url,
            tools=tools,
        )

        logger.info("Registered plugin '%s' with %d tools", name, len(tools))
        return plugin

    async def load_enabled_plugins(self) -> None:
        """Load all enabled plugins from the database."""
        async with get_session() as session:
            result = await session.execute(
                select(Plugin).where(Plugin.enabled == True)  # noqa: E712
            )
            plugins = result.scalars().all()

        for plugin in plugins:
            tools = json.loads(plugin.tools_json) if plugin.tools_json else []
            self._plugins[plugin.name] = MCPPlugin(
                name=plugin.name,
                endpoint_url=plugin.endpoint_url,
                tools=tools,
            )

        logger.info("Loaded %d enabled plugins", len(self._plugins))

    def get_all_tools(self) -> List[Dict[str, Any]]:
        """Get all tools from all loaded plugins.

        Returns:
            Combined list of tool definitions.
        """
        all_tools = []
        for plugin in self._plugins.values():
            for tool in plugin.tools:
                tool_copy = dict(tool)
                tool_copy["plugin_name"] = plugin.name
                tool_copy["plugin_endpoint"] = plugin.endpoint_url
                all_tools.append(tool_copy)
        return all_tools

    async def close(self) -> None:
        """Clean up the HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None


# Module-level singleton
plugin_manager = PluginManager()
