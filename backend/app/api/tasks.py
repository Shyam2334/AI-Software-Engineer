"""REST API endpoints for task CRUD and history."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.agents.orchestrator import run_task
from app.api.websocket import manager
from app.config import get_settings
from app.database import get_db
from app.models import Approval, LogLevel, Task, TaskLog, TaskStatus
from app.services.git_service import git_service

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Request/Response Schemas ────────────────────────────────────────────


class TaskCreate(BaseModel):
    """Schema for creating a new task."""
    title: str
    description: str
    project_path: Optional[str] = None
    repo_name: Optional[str] = None
    repo_url: Optional[str] = None
    document_context: Optional[str] = None


# In-memory store for uploaded document context keyed by upload_id
_uploaded_docs: Dict[str, str] = {}


class TaskResponse(BaseModel):
    """Schema for task responses."""
    id: int
    title: str
    description: str
    status: str
    progress: int
    branch_name: Optional[str]
    pr_url: Optional[str]
    pr_number: Optional[int]
    repo_name: Optional[str]
    repo_url: Optional[str]
    retry_count: int
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime]

    model_config = {"from_attributes": True}


class TaskLogResponse(BaseModel):
    """Schema for task log responses."""
    id: int
    message: str
    level: str
    phase: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class ApprovalResponse(BaseModel):
    """Schema for approval responses."""
    id: int
    approval_type: str
    status: str
    title: str
    description: str
    details_json: Optional[str]
    created_at: datetime
    resolved_at: Optional[datetime]

    model_config = {"from_attributes": True}


# ── Endpoints ───────────────────────────────────────────────────────────


@router.get("/", response_model=List[TaskResponse])
async def list_tasks(
    skip: int = 0,
    limit: int = 50,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
) -> List[Task]:
    """List all tasks with optional status filter.

    Args:
        skip: Number of records to skip.
        limit: Maximum records to return.
        status: Optional status filter.
        db: Database session.

    Returns:
        List of tasks.
    """
    query = select(Task).order_by(Task.created_at.desc()).offset(skip).limit(limit)

    if status:
        try:
            task_status = TaskStatus(status)
            query = query.where(Task.status == task_status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(task_id: int, db: AsyncSession = Depends(get_db)) -> Task:
    """Get a specific task by ID.

    Args:
        task_id: Task ID.
        db: Database session.

    Returns:
        The task.

    Raises:
        HTTPException: If task not found.
    """
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("/", response_model=TaskResponse, status_code=201)
async def create_task(
    task_data: TaskCreate,
    db: AsyncSession = Depends(get_db),
) -> Task:
    """Create a new task and start the orchestrator workflow.

    Args:
        task_data: Task creation data.
        db: Database session.

    Returns:
        The created task.
    """
    settings = get_settings()

    # Resolve project path and repo name
    project_path = task_data.project_path or ""
    repo_name = task_data.repo_name or ""
    repo_url = task_data.repo_url or ""

    # If repo_url is provided, derive repo_name and project_path
    if repo_url and not project_path:
        # Extract repo name from URL (e.g., https://github.com/owner/repo.git -> owner/repo)
        parts = repo_url.rstrip("/").rstrip(".git").split("/")
        if len(parts) >= 2:
            repo_name = repo_name or f"{parts[-2]}/{parts[-1]}"
            repo_slug = parts[-1]
            project_path = os.path.join(settings.projects_dir, repo_slug)

    # Clone repo if URL provided
    if repo_url and project_path:
        try:
            git_service.clone_repo(repo_url, project_path)
        except Exception as e:
            logger.warning("Could not clone repo %s: %s", repo_url, e)

    branch_name = f"ai/task-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"

    task = Task(
        title=task_data.title,
        description=task_data.description,
        status=TaskStatus.PENDING,
        progress=0,
        branch_name=branch_name,
        repo_name=repo_name,
        repo_url=repo_url,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    logger.info("Created task #%d: %s (repo: %s)", task.id, task.title, repo_name)

    # Collect document context (from upload or inline)
    document_context = task_data.document_context or ""

    # Start the orchestrator in the background
    import asyncio

    ws_callback = manager.create_task_callback(task.id)

    asyncio.create_task(
        run_task(
            task_id=task.id,
            task_description=f"{task.title}\n\n{task.description}",
            project_path=project_path,
            repo_name=repo_name,
            branch_name=branch_name,
            websocket_callback=ws_callback,
            document_context=document_context,
        )
    )

    return task


@router.delete("/{task_id}", status_code=204, response_class=Response)
async def cancel_task(task_id: int, db: AsyncSession = Depends(get_db)) -> Response:
    """Cancel a running task.

    Args:
        task_id: Task ID.
        db: Database session.
    """
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
        raise HTTPException(status_code=400, detail="Task is already finished")

    task.status = TaskStatus.CANCELLED
    task.updated_at = datetime.utcnow()
    db.add(task)
    await db.commit()

    # Notify via WebSocket
    await manager.send_to_task(task_id, {
        "type": "status",
        "task_id": task_id,
        "status": "cancelled",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    logger.info("Cancelled task #%d", task_id)
    return Response(status_code=204)


@router.get("/{task_id}/logs", response_model=List[TaskLogResponse])
async def get_task_logs(
    task_id: int,
    level: Optional[str] = None,
    limit: int = 200,
    db: AsyncSession = Depends(get_db),
) -> List[TaskLog]:
    """Get logs for a specific task.

    Args:
        task_id: Task ID.
        level: Optional log level filter.
        limit: Maximum logs to return.
        db: Database session.

    Returns:
        List of log entries.
    """
    query = (
        select(TaskLog)
        .where(TaskLog.task_id == task_id)
        .order_by(TaskLog.created_at.asc())
        .limit(limit)
    )

    if level:
        try:
            log_level = LogLevel(level)
            query = query.where(TaskLog.level == log_level)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid log level: {level}")

    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{task_id}/approvals", response_model=List[ApprovalResponse])
async def get_task_approvals(
    task_id: int,
    db: AsyncSession = Depends(get_db),
) -> List[Approval]:
    """Get all approval requests for a task.

    Args:
        task_id: Task ID.
        db: Database session.

    Returns:
        List of approvals.
    """
    result = await db.execute(
        select(Approval)
        .where(Approval.task_id == task_id)
        .order_by(Approval.created_at.desc())
    )
    return result.scalars().all()


@router.post("/upload-document")
async def upload_document(file: UploadFile = File(...)) -> dict:
    """Upload a document to provide as context for a task.

    Supports .txt, .md, .py, .js, .ts, .json, .csv, .yaml, .yml, .xml, .html, .css files.

    Returns:
        Dict with upload_id and extracted text preview.
    """
    allowed_extensions = {
        ".txt", ".md", ".py", ".js", ".ts", ".jsx", ".tsx", ".json",
        ".csv", ".yaml", ".yml", ".xml", ".html", ".css", ".sql",
        ".sh", ".bat", ".cfg", ".ini", ".toml", ".env", ".log",
    }

    filename = file.filename or "upload.txt"
    ext = os.path.splitext(filename)[1].lower()
    if ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {ext}. Supported: {', '.join(sorted(allowed_extensions))}",
        )

    content_bytes = await file.read()
    if len(content_bytes) > 500_000:  # 500KB limit
        raise HTTPException(status_code=400, detail="File too large. Max 500KB.")

    try:
        text = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = content_bytes.decode("latin-1")
        except Exception:
            raise HTTPException(status_code=400, detail="Could not decode file as text.")

    import uuid
    upload_id = str(uuid.uuid4())[:8]
    _uploaded_docs[upload_id] = f"[Uploaded: {filename}]\n{text}"

    logger.info("Uploaded document: %s (%d chars) -> %s", filename, len(text), upload_id)
    return {
        "upload_id": upload_id,
        "filename": filename,
        "size": len(text),
        "preview": text[:200] + ("..." if len(text) > 200 else ""),
    }


@router.get("/upload-document/{upload_id}")
async def get_uploaded_document(upload_id: str) -> dict:
    """Retrieve uploaded document content by ID."""
    content = _uploaded_docs.get(upload_id)
    if not content:
        raise HTTPException(status_code=404, detail="Upload not found or expired.")
    return {"upload_id": upload_id, "content": content}


@router.post("/{task_id}/approvals/{approval_id}/respond")
async def respond_to_approval(
    task_id: int,
    approval_id: int,
    approved: bool,
    message: str = "",
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Respond to an approval request (REST fallback for WebSocket).

    Args:
        task_id: Task ID.
        approval_id: Approval ID.
        approved: Whether to approve.
        message: Optional response message.
        db: Database session.

    Returns:
        Approval status.
    """
    result = await db.execute(
        select(Approval).where(
            Approval.id == approval_id,
            Approval.task_id == task_id,
        )
    )
    approval = result.scalar_one_or_none()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")

    if approval.status != "pending":
        raise HTTPException(status_code=400, detail="Approval already resolved")

    approval.status = "approved" if approved else "rejected"
    approval.response_message = message
    approval.resolved_at = datetime.utcnow()
    db.add(approval)
    await db.commit()

    # Notify via WebSocket
    await manager.send_to_task(task_id, {
        "type": "approval_resolved",
        "approval_id": approval_id,
        "status": approval.status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    return {"status": approval.status, "approval_id": approval_id}
