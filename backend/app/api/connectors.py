"""REST API endpoints for MCP connectors (GitHub, Jira) and GitHub repos."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List, Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Persistent config file ──────────────────────────────────────────────

_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "mcp_connectors.json"


def _load_config() -> dict:
    if _CONFIG_PATH.exists():
        return json.loads(_CONFIG_PATH.read_text())
    return {"github": {"connected": False}, "jira": {"connected": False}}


def _save_config(cfg: dict) -> None:
    _CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


# ── Schemas ─────────────────────────────────────────────────────────────


class GitHubConnect(BaseModel):
    token: str
    owner: str = ""


class JiraConnect(BaseModel):
    base_url: str
    email: str
    api_token: str
    project_key: str = ""


class ConnectorStatus(BaseModel):
    provider: str
    connected: bool
    details: dict = {}


class RepoInfo(BaseModel):
    full_name: str
    html_url: str
    description: Optional[str]
    private: bool
    default_branch: str
    updated_at: str


# ── GitHub Connector ────────────────────────────────────────────────────


@router.get("/status", response_model=List[ConnectorStatus])
async def list_connectors() -> list:
    """Return connection status for all MCP connectors."""
    cfg = _load_config()
    settings = get_settings()

    gh = cfg.get("github", {})
    jira = cfg.get("jira", {})

    github_connected = gh.get("connected", False) or bool(settings.github_token)
    github_owner = gh.get("owner", "") or settings.github_owner

    return [
        ConnectorStatus(
            provider="github",
            connected=github_connected,
            details={
                "owner": github_owner,
                "setup_instructions": [
                    "Create a Personal Access Token (PAT) at https://github.com/settings/tokens",
                    "For Fine-grained tokens: select your repos, grant 'Contents: Read & Write' and 'Pull Requests: Read & Write'",
                    "For Classic tokens: select 'repo' scope",
                    "Enter the token and your GitHub username/org below",
                ],
                "required_fields": ["token", "owner"],
            },
        ),
        ConnectorStatus(
            provider="jira",
            connected=jira.get("connected", False),
            details={
                "base_url": jira.get("base_url", ""),
                "email": jira.get("email", ""),
                "project_key": jira.get("project_key", ""),
                "setup_instructions": [
                    "Go to https://id.atlassian.com/manage-profile/security/api-tokens",
                    "Click 'Create API token' and give it a label",
                    "Your Base URL is your Jira domain (e.g., https://yourteam.atlassian.net)",
                    "Use your Atlassian account email",
                    "Optionally set a default project key (e.g., PROJ)",
                ],
                "required_fields": ["base_url", "email", "api_token"],
            },
        ),
    ]


@router.post("/github/connect", response_model=ConnectorStatus)
async def connect_github(body: GitHubConnect) -> ConnectorStatus:
    """Save and verify GitHub PAT connection."""
    # Verify token by calling GitHub API
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {body.token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=10,
        )
        if resp.status_code != 200:
            raise HTTPException(400, f"GitHub auth failed: {resp.text}")
        user = resp.json()

    owner = body.owner or user.get("login", "")
    cfg = _load_config()
    cfg["github"] = {"connected": True, "owner": owner, "token": body.token}
    _save_config(cfg)

    # Also update in-memory settings (non-persistent env override)
    settings = get_settings()
    settings.github_token = body.token
    settings.github_owner = owner

    return ConnectorStatus(
        provider="github",
        connected=True,
        details={"owner": owner, "login": user.get("login", "")},
    )


@router.post("/github/disconnect")
async def disconnect_github() -> dict:
    cfg = _load_config()
    cfg["github"] = {"connected": False}
    _save_config(cfg)
    return {"ok": True}


@router.get("/github/repos", response_model=List[RepoInfo])
async def list_github_repos(per_page: int = 50, page: int = 1) -> list:
    """Fetch the authenticated user's repos from GitHub."""
    cfg = _load_config()
    settings = get_settings()

    token = cfg.get("github", {}).get("token", "") or settings.github_token
    if not token:
        raise HTTPException(400, "GitHub not connected. Add your PAT first.")

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.github.com/user/repos",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            params={
                "sort": "updated",
                "direction": "desc",
                "per_page": min(per_page, 100),
                "page": page,
                "affiliation": "owner,collaborator,organization_member",
            },
            timeout=15,
        )
        if resp.status_code != 200:
            raise HTTPException(400, f"Failed to fetch repos: {resp.text}")
        repos = resp.json()

    return [
        RepoInfo(
            full_name=r["full_name"],
            html_url=r["html_url"],
            description=r.get("description"),
            private=r.get("private", False),
            default_branch=r.get("default_branch", "main"),
            updated_at=r.get("updated_at", ""),
        )
        for r in repos
    ]


# ── Jira Connector ─────────────────────────────────────────────────────


@router.post("/jira/connect", response_model=ConnectorStatus)
async def connect_jira(body: JiraConnect) -> ConnectorStatus:
    """Save and verify Jira API token connection."""
    base = body.base_url.rstrip("/")

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{base}/rest/api/3/myself",
            auth=(body.email, body.api_token),
            headers={"Accept": "application/json"},
            timeout=10,
        )
        if resp.status_code != 200:
            raise HTTPException(400, f"Jira auth failed: {resp.text}")
        user = resp.json()

    cfg = _load_config()
    cfg["jira"] = {
        "connected": True,
        "base_url": base,
        "email": body.email,
        "api_token": body.api_token,
        "project_key": body.project_key,
        "display_name": user.get("displayName", ""),
    }
    _save_config(cfg)

    return ConnectorStatus(
        provider="jira",
        connected=True,
        details={
            "base_url": base,
            "display_name": user.get("displayName", ""),
            "project_key": body.project_key,
        },
    )


@router.post("/jira/disconnect")
async def disconnect_jira() -> dict:
    cfg = _load_config()
    cfg["jira"] = {"connected": False}
    _save_config(cfg)
    return {"ok": True}
