"""Celery worker for background task processing."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from celery import Celery

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# ── Celery Application ──────────────────────────────────────────────────

celery_app = Celery(
    "ai_software_engineer",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    result_expires=86400,  # 24 hours
)


def _get_or_create_event_loop() -> asyncio.AbstractEventLoop:
    """Get the running loop or create a new one for sync context."""
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop


# ── Celery Tasks ────────────────────────────────────────────────────────


@celery_app.task(bind=True, name="run_agent_task", max_retries=0)
def run_agent_task(
    self,
    task_id: int,
    task_description: str,
    project_path: str = "",
    repo_name: str = "",
    branch_name: str = "",
) -> dict:
    """Run the AI orchestrator workflow as a Celery background task.

    Args:
        task_id: Database task ID.
        task_description: Natural language task description.
        project_path: Local project directory path.
        repo_name: GitHub repository name.
        branch_name: Git branch name for changes.

    Returns:
        Dict with task result summary.
    """
    from app.agents.orchestrator import run_task

    logger.info("Celery worker starting task #%d: %s", task_id, task_description[:80])

    loop = _get_or_create_event_loop()
    try:
        final_state = loop.run_until_complete(
            run_task(
                task_id=task_id,
                task_description=task_description,
                project_path=project_path,
                repo_name=repo_name,
                branch_name=branch_name,
                websocket_callback=None,  # No WebSocket in Celery context
            )
        )

        return {
            "task_id": task_id,
            "status": final_state.get("current_phase", "unknown"),
            "pr_url": final_state.get("pr_url", ""),
            "error": final_state.get("error"),
        }

    except Exception as e:
        logger.error("Celery task #%d failed: %s", task_id, e)
        return {
            "task_id": task_id,
            "status": "failed",
            "error": str(e),
        }


@celery_app.task(name="cleanup_old_containers")
def cleanup_old_containers() -> dict:
    """Periodic task to clean up stale Docker containers.

    Returns:
        Dict with cleanup summary.
    """
    import docker

    try:
        client = docker.from_env()
        containers = client.containers.list(
            all=True,
            filters={"status": "exited", "label": "aiswe-sandbox"},
        )

        removed = 0
        for container in containers:
            try:
                container.remove(force=True)
                removed += 1
            except Exception:
                pass

        logger.info("Cleaned up %d stale containers", removed)
        return {"removed": removed}

    except Exception as e:
        logger.error("Container cleanup failed: %s", e)
        return {"error": str(e)}


# ── Celery Beat Schedule (periodic tasks) ───────────────────────────────

celery_app.conf.beat_schedule = {
    "cleanup-containers-hourly": {
        "task": "cleanup_old_containers",
        "schedule": 3600.0,  # Every hour
    },
}
