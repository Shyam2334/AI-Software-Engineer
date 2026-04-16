"""Tool definitions for the agent orchestrator and plugin ecosystem."""

from __future__ import annotations

from typing import Any, Dict, List


def get_built_in_tools() -> List[Dict[str, Any]]:
    """Return definitions for all built-in tools available to agents.

    These tool definitions follow the MCP tool schema and are used by
    the orchestrator to decide which capabilities to invoke.

    Returns:
        List of tool definition dicts.
    """
    return [
        {
            "name": "search_web",
            "description": "Search the web for documentation, APIs, or solutions",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum results to return",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
        {
            "name": "fetch_page",
            "description": "Fetch and extract text content from a web page",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL to fetch",
                    },
                },
                "required": ["url"],
            },
        },
        {
            "name": "run_terminal",
            "description": "Execute a terminal command in the project directory",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to run",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds",
                        "default": 60,
                    },
                },
                "required": ["command"],
            },
        },
        {
            "name": "run_tests",
            "description": "Run project tests in a sandboxed container",
            "parameters": {
                "type": "object",
                "properties": {
                    "test_command": {
                        "type": "string",
                        "description": "Test command (e.g., 'pytest -v')",
                        "default": "pytest -v",
                    },
                },
                "required": [],
            },
        },
        {
            "name": "run_code",
            "description": "Run a code snippet in a sandboxed container",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Code to execute",
                    },
                    "language": {
                        "type": "string",
                        "description": "Programming language",
                        "default": "python",
                    },
                },
                "required": ["code"],
            },
        },
        {
            "name": "git_commit",
            "description": "Stage and commit changes to the repository",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "Commit message",
                    },
                },
                "required": ["message"],
            },
        },
        {
            "name": "create_pr",
            "description": "Create a GitHub pull request",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "PR title",
                    },
                    "body": {
                        "type": "string",
                        "description": "PR description (markdown)",
                    },
                },
                "required": ["title", "body"],
            },
        },
        {
            "name": "read_file",
            "description": "Read the contents of a file in the project",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative file path",
                    },
                },
                "required": ["path"],
            },
        },
        {
            "name": "write_file",
            "description": "Write or overwrite a file in the project",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative file path",
                    },
                    "content": {
                        "type": "string",
                        "description": "File content",
                    },
                },
                "required": ["path", "content"],
            },
        },
        {
            "name": "list_files",
            "description": "List files in a project directory",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative directory path",
                        "default": ".",
                    },
                },
                "required": [],
            },
        },
    ]


def format_tools_for_prompt(tools: List[Dict[str, Any]]) -> str:
    """Format tool definitions as a prompt-friendly string.

    Args:
        tools: List of tool definitions.

    Returns:
        Formatted string describing available tools.
    """
    lines = ["Available tools:\n"]
    for tool in tools:
        name = tool.get("name", "unknown")
        desc = tool.get("description", "")
        params = tool.get("parameters", {}).get("properties", {})
        required = tool.get("parameters", {}).get("required", [])

        lines.append(f"- **{name}**: {desc}")
        if params:
            param_strs = []
            for pname, pinfo in params.items():
                req = " (required)" if pname in required else ""
                param_strs.append(f"  - {pname}: {pinfo.get('description', '')}{req}")
            lines.extend(param_strs)
        lines.append("")

    return "\n".join(lines)
