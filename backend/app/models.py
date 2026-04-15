"""SQLModel database models for the AI Software Engineer."""

import enum
from datetime import datetime
from typing import List, Optional

from sqlmodel import Column, Enum, Field, Relationship, SQLModel, Text


class TaskStatus(str, enum.Enum):
    """Task lifecycle states."""
    PENDING = "pending"
    PLANNING = "planning"
    RESEARCHING = "researching"
    CODING = "coding"
    TESTING = "testing"
    REVISING = "revising"
    DOCUMENTING = "documenting"
    AWAITING_APPROVAL = "awaiting_approval"
    CREATING_PR = "creating_pr"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class LogLevel(str, enum.Enum):
    """Log severity levels."""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    SUCCESS = "success"


class ApprovalStatus(str, enum.Enum):
    """Approval request states."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ApprovalType(str, enum.Enum):
    """Types of actions requiring approval."""
    PLAN_REVIEW = "plan_review"
    PR_CREATION = "pr_creation"
    DESTRUCTIVE_COMMAND = "destructive_command"
    RISKY_OPERATION = "risky_operation"


class Project(SQLModel, table=True):
    """Represents a code project / repository."""

    __tablename__ = "projects"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, max_length=255)
    repo_url: str = Field(default="", max_length=500)
    local_path: str = Field(default="", max_length=500)
    default_branch: str = Field(default="main", max_length=100)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    tasks: List["Task"] = Relationship(back_populates="project")


class Task(SQLModel, table=True):
    """A unit of work (bug fix, feature, documentation, etc.)."""

    __tablename__ = "tasks"

    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(max_length=500)
    description: str = Field(sa_column=Column(Text, default=""))
    status: TaskStatus = Field(
        sa_column=Column(Enum(TaskStatus), default=TaskStatus.PENDING)
    )
    progress: int = Field(default=0, ge=0, le=100)
    branch_name: Optional[str] = Field(default=None, max_length=255)
    pr_url: Optional[str] = Field(default=None, max_length=500)
    pr_number: Optional[int] = Field(default=None)
    repo_name: Optional[str] = Field(default=None, max_length=500)
    repo_url: Optional[str] = Field(default=None, max_length=500)
    retry_count: int = Field(default=0)
    checkpoint_id: Optional[str] = Field(default=None, max_length=255)
    error_message: Optional[str] = Field(default=None, sa_column=Column(Text))

    # Foreign keys
    project_id: Optional[int] = Field(default=None, foreign_key="projects.id")

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = Field(default=None)

    # Relationships
    project: Optional[Project] = Relationship(back_populates="tasks")
    logs: List["TaskLog"] = Relationship(back_populates="task")
    approvals: List["Approval"] = Relationship(back_populates="task")


class TaskLog(SQLModel, table=True):
    """Log entry associated with a task execution."""

    __tablename__ = "task_logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    message: str = Field(sa_column=Column(Text))
    level: LogLevel = Field(
        sa_column=Column(Enum(LogLevel), default=LogLevel.INFO)
    )
    phase: Optional[str] = Field(default=None, max_length=100)
    metadata_json: Optional[str] = Field(default=None, sa_column=Column(Text))
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Foreign keys
    task_id: int = Field(foreign_key="tasks.id", index=True)

    # Relationships
    task: Optional[Task] = Relationship(back_populates="logs")


class Approval(SQLModel, table=True):
    """Human-in-the-loop approval request."""

    __tablename__ = "approvals"

    id: Optional[int] = Field(default=None, primary_key=True)
    approval_type: ApprovalType = Field(
        sa_column=Column(Enum(ApprovalType))
    )
    status: ApprovalStatus = Field(
        sa_column=Column(Enum(ApprovalStatus), default=ApprovalStatus.PENDING)
    )
    title: str = Field(max_length=500)
    description: str = Field(sa_column=Column(Text, default=""))
    details_json: Optional[str] = Field(default=None, sa_column=Column(Text))
    response_message: Optional[str] = Field(default=None, sa_column=Column(Text))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    resolved_at: Optional[datetime] = Field(default=None)

    # Foreign keys
    task_id: int = Field(foreign_key="tasks.id", index=True)

    # Relationships
    task: Optional[Task] = Relationship(back_populates="approvals")


class Plugin(SQLModel, table=True):
    """MCP plugin registration."""

    __tablename__ = "plugins"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True, max_length=255)
    description: str = Field(sa_column=Column(Text, default=""))
    endpoint_url: str = Field(max_length=500)
    enabled: bool = Field(default=True)
    tools_json: Optional[str] = Field(default=None, sa_column=Column(Text))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
