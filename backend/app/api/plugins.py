"""REST API endpoints for MCP plugin management."""

from __future__ import annotations

import json
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.database import get_db
from app.models import Plugin
from app.services.plugin_manager import plugin_manager

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Request/Response Schemas ────────────────────────────────────────────


class PluginCreate(BaseModel):
    """Schema for registering a new plugin."""
    name: str
    endpoint_url: str
    description: str = ""


class PluginResponse(BaseModel):
    """Schema for plugin responses."""
    id: int
    name: str
    description: str
    endpoint_url: str
    enabled: bool
    tools: List[dict]
    created_at: str

    model_config = {"from_attributes": True}


class PluginToggle(BaseModel):
    """Schema for enabling/disabling a plugin."""
    enabled: bool


# ── Endpoints ───────────────────────────────────────────────────────────


@router.get("/", response_model=List[PluginResponse])
async def list_plugins(db: AsyncSession = Depends(get_db)) -> list:
    """List all registered plugins.

    Args:
        db: Database session.

    Returns:
        List of plugins with their tools.
    """
    result = await db.execute(select(Plugin).order_by(Plugin.name))
    plugins = result.scalars().all()

    response = []
    for p in plugins:
        tools = json.loads(p.tools_json) if p.tools_json else []
        response.append({
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "endpoint_url": p.endpoint_url,
            "enabled": p.enabled,
            "tools": tools,
            "created_at": p.created_at.isoformat(),
        })

    return response


@router.post("/", response_model=PluginResponse, status_code=201)
async def register_plugin(
    plugin_data: PluginCreate,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Register a new MCP plugin.

    Args:
        plugin_data: Plugin registration data.
        db: Database session.

    Returns:
        The registered plugin.
    """
    # Check for duplicate name
    existing = await db.execute(
        select(Plugin).where(Plugin.name == plugin_data.name)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Plugin name already exists")

    plugin = await plugin_manager.register_plugin(
        name=plugin_data.name,
        endpoint_url=plugin_data.endpoint_url,
        description=plugin_data.description,
    )

    tools = json.loads(plugin.tools_json) if plugin.tools_json else []
    return {
        "id": plugin.id,
        "name": plugin.name,
        "description": plugin.description,
        "endpoint_url": plugin.endpoint_url,
        "enabled": plugin.enabled,
        "tools": tools,
        "created_at": plugin.created_at.isoformat(),
    }


@router.patch("/{plugin_id}", response_model=PluginResponse)
async def toggle_plugin(
    plugin_id: int,
    toggle: PluginToggle,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Enable or disable a plugin.

    Args:
        plugin_id: Plugin ID.
        toggle: New enabled state.
        db: Database session.

    Returns:
        Updated plugin.
    """
    result = await db.execute(select(Plugin).where(Plugin.id == plugin_id))
    plugin = result.scalar_one_or_none()
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")

    plugin.enabled = toggle.enabled
    db.add(plugin)
    await db.commit()
    await db.refresh(plugin)

    # Reload plugins in the manager
    await plugin_manager.load_enabled_plugins()

    tools = json.loads(plugin.tools_json) if plugin.tools_json else []
    logger.info(
        "Plugin '%s' %s",
        plugin.name,
        "enabled" if toggle.enabled else "disabled",
    )

    return {
        "id": plugin.id,
        "name": plugin.name,
        "description": plugin.description,
        "endpoint_url": plugin.endpoint_url,
        "enabled": plugin.enabled,
        "tools": tools,
        "created_at": plugin.created_at.isoformat(),
    }


@router.delete("/{plugin_id}", status_code=204, response_class=Response)
async def delete_plugin(
    plugin_id: int,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete a registered plugin.

    Args:
        plugin_id: Plugin ID.
        db: Database session.
    """
    result = await db.execute(select(Plugin).where(Plugin.id == plugin_id))
    plugin = result.scalar_one_or_none()
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")

    await db.delete(plugin)
    await db.commit()

    # Reload plugins
    await plugin_manager.load_enabled_plugins()
    logger.info("Deleted plugin '%s'", plugin.name)
    return Response(status_code=204)


@router.get("/{plugin_id}/tools")
async def get_plugin_tools(
    plugin_id: int,
    db: AsyncSession = Depends(get_db),
) -> List[dict]:
    """Get the tools available from a specific plugin.

    Args:
        plugin_id: Plugin ID.
        db: Database session.

    Returns:
        List of tool definitions.
    """
    result = await db.execute(select(Plugin).where(Plugin.id == plugin_id))
    plugin = result.scalar_one_or_none()
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")

    return json.loads(plugin.tools_json) if plugin.tools_json else []
