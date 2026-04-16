"""WebSocket connection manager and endpoint for real-time streaming."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlmodel import select

from app.database import get_session
from app.models import Approval, ApprovalStatus

logger = logging.getLogger(__name__)
router = APIRouter()


class ConnectionManager:
    """Manages WebSocket connections with heartbeat support."""

    def __init__(self) -> None:
        self._connections: Dict[int, Set[WebSocket]] = {}  # task_id -> set of websockets
        self._global_connections: Set[WebSocket] = set()
        self._heartbeat_interval: int = 30  # seconds

    async def connect(
        self, websocket: WebSocket, task_id: int | None = None
    ) -> None:
        """Accept and register a WebSocket connection.

        Args:
            websocket: The WebSocket to register.
            task_id: Optional task ID for task-specific updates.
        """
        await websocket.accept()
        self._global_connections.add(websocket)

        if task_id is not None:
            if task_id not in self._connections:
                self._connections[task_id] = set()
            self._connections[task_id].add(websocket)

        logger.info(
            "WebSocket connected (task=%s, total=%d)",
            task_id,
            len(self._global_connections),
        )

    def disconnect(self, websocket: WebSocket, task_id: int | None = None) -> None:
        """Remove a WebSocket connection.

        Args:
            websocket: The WebSocket to remove.
            task_id: Optional task ID.
        """
        self._global_connections.discard(websocket)
        if task_id is not None and task_id in self._connections:
            self._connections[task_id].discard(websocket)
            if not self._connections[task_id]:
                del self._connections[task_id]

        logger.info(
            "WebSocket disconnected (task=%s, remaining=%d)",
            task_id,
            len(self._global_connections),
        )

    async def send_to_task(self, task_id: int, message: Dict[str, Any]) -> None:
        """Send a message to all connections listening to a specific task.

        Args:
            task_id: The task ID.
            message: JSON-serializable message.
        """
        dead: list[WebSocket] = []
        connections = self._connections.get(task_id, set()) | self._global_connections

        for ws in connections:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)

        for ws in dead:
            self.disconnect(ws, task_id)

    async def broadcast(self, message: Dict[str, Any]) -> None:
        """Broadcast a message to all connected clients.

        Args:
            message: JSON-serializable message.
        """
        dead: list[WebSocket] = []
        for ws in self._global_connections.copy():
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)

        for ws in dead:
            self._global_connections.discard(ws)

    def create_task_callback(self, task_id: int):
        """Create an async callback function for the orchestrator to send updates.

        Args:
            task_id: The task ID.

        Returns:
            Async callback function.
        """

        async def callback(message: Dict[str, Any]) -> None:
            await self.send_to_task(task_id, message)

        return callback


# Module-level singleton
manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_global(websocket: WebSocket) -> None:
    """Global WebSocket endpoint for all task updates."""
    await manager.connect(websocket)

    try:
        while True:
            try:
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=manager._heartbeat_interval,
                )

                # Handle incoming messages
                try:
                    message = json.loads(data)
                    await _handle_client_message(websocket, message)
                except json.JSONDecodeError:
                    await websocket.send_json({"error": "Invalid JSON"})

            except asyncio.TimeoutError:
                # Send heartbeat ping
                try:
                    await websocket.send_json({
                        "type": "heartbeat",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                except Exception:
                    break

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error("WebSocket error: %s", e)
        manager.disconnect(websocket)


@router.websocket("/ws/{task_id}")
async def websocket_task(websocket: WebSocket, task_id: int) -> None:
    """Task-specific WebSocket endpoint for targeted updates."""
    await manager.connect(websocket, task_id)

    try:
        while True:
            try:
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=manager._heartbeat_interval,
                )

                try:
                    message = json.loads(data)
                    await _handle_client_message(websocket, message)
                except json.JSONDecodeError:
                    await websocket.send_json({"error": "Invalid JSON"})

            except asyncio.TimeoutError:
                try:
                    await websocket.send_json({
                        "type": "heartbeat",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                except Exception:
                    break

    except WebSocketDisconnect:
        manager.disconnect(websocket, task_id)
    except Exception as e:
        logger.error("WebSocket error (task %d): %s", task_id, e)
        manager.disconnect(websocket, task_id)


async def _handle_client_message(
    websocket: WebSocket, message: Dict[str, Any]
) -> None:
    """Process an incoming WebSocket message from a client.

    Supports:
    - approval_response: Handle approval approve/reject
    - ping: Respond with pong

    Args:
        websocket: Source WebSocket.
        message: Parsed message dict.
    """
    msg_type = message.get("type", "")

    if msg_type == "ping":
        await websocket.send_json({
            "type": "pong",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    elif msg_type == "approval_response":
        approval_id = message.get("approval_id")
        approved = message.get("approved", False)
        response_msg = message.get("message", "")

        if approval_id is None:
            await websocket.send_json({"error": "approval_id required"})
            return

        async with get_session() as session:
            result = await session.execute(
                select(Approval).where(Approval.id == approval_id)
            )
            approval = result.scalar_one_or_none()

            if approval and approval.status == ApprovalStatus.PENDING:
                approval.status = (
                    ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
                )
                approval.response_message = response_msg
                approval.resolved_at = datetime.utcnow()
                session.add(approval)

                await websocket.send_json({
                    "type": "approval_confirmed",
                    "approval_id": approval_id,
                    "status": approval.status.value,
                })
                logger.info(
                    "Approval %d %s",
                    approval_id,
                    "approved" if approved else "rejected",
                )
            else:
                await websocket.send_json({
                    "error": f"Approval {approval_id} not found or already resolved"
                })

    else:
        await websocket.send_json({"error": f"Unknown message type: {msg_type}"})
