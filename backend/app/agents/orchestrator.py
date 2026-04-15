"""LangGraph orchestrator for multi-step AI software engineering workflow.

Nodes: research → analyze → plan → (approve plan) → code → test → revise → document → (approve PR) → create_pr
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, TypedDict

from langgraph.graph import END, StateGraph

from app.agents.prompts import (
    ARCHITECT_SYSTEM_PROMPT,
    DEBUGGER_SYSTEM_PROMPT,
    DOCUMENTER_SYSTEM_PROMPT,
    ENGINEER_SYSTEM_PROMPT,
    PR_DESCRIPTION_PROMPT,
    TASK_ANALYZER_PROMPT,
)
from app.config import get_settings
from app.database import get_session
from app.models import Approval, ApprovalStatus, ApprovalType, LogLevel, Task, TaskLog, TaskStatus
from app.services.ai_service import ai_service
from app.services.git_service import git_service
from app.services.sandbox import sandbox_service
from app.services.terminal import terminal_service
from app.services.web_browser import web_browser_service

logger = logging.getLogger(__name__)
settings = get_settings()


# ── Workflow State ──────────────────────────────────────────────────────


class WorkflowState(TypedDict, total=False):
    """State that flows through the LangGraph workflow."""

    # Task info
    task_id: int
    task_description: str
    project_path: str
    repo_name: str

    # Analysis
    task_analysis: Dict[str, Any]
    research_results: List[Dict[str, Any]]

    # Planning
    implementation_plan: str
    plan_approved: bool

    # Coding
    generated_code: Dict[str, str]  # path -> content
    code_language: str

    # Testing
    test_output: str
    tests_passed: bool
    retry_count: int

    # Documentation
    documentation: str
    pr_description: str

    # PR
    branch_name: str
    pr_url: str
    pr_number: int
    pr_approved: bool

    # Workflow control
    current_phase: str
    error: Optional[str]
    websocket_callback: Optional[Any]


# ── Helper: log + broadcast ────────────────────────────────────────────


async def _log(
    state: WorkflowState,
    message: str,
    level: LogLevel = LogLevel.INFO,
    phase: Optional[str] = None,
    progress: Optional[int] = None,
) -> None:
    """Persist a log entry and send a WebSocket update."""
    task_id = state.get("task_id", 0)
    phase = phase or state.get("current_phase", "")

    # Store in database
    async with get_session() as session:
        log_entry = TaskLog(
            task_id=task_id,
            message=message,
            level=level,
            phase=phase,
        )
        session.add(log_entry)

        # Update task progress if provided
        if progress is not None:
            from sqlmodel import select

            result = await session.execute(select(Task).where(Task.id == task_id))
            task = result.scalar_one_or_none()
            if task:
                task.progress = progress
                task.updated_at = datetime.utcnow()
                session.add(task)

    # Send WebSocket update
    callback = state.get("websocket_callback")
    if callback:
        await callback({
            "type": "log",
            "task_id": task_id,
            "message": message,
            "level": level.value,
            "phase": phase,
            "progress": progress,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })


async def _update_task_status(state: WorkflowState, status: TaskStatus) -> None:
    """Update the task status in the database."""
    task_id = state.get("task_id", 0)
    async with get_session() as session:
        from sqlmodel import select

        result = await session.execute(select(Task).where(Task.id == task_id))
        task = result.scalar_one_or_none()
        if task:
            task.status = status
            task.updated_at = datetime.utcnow()
            if status == TaskStatus.COMPLETED:
                task.completed_at = datetime.utcnow()
            session.add(task)

    # Send status update via WebSocket
    callback = state.get("websocket_callback")
    if callback:
        await callback({
            "type": "status",
            "task_id": task_id,
            "status": status.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })


async def _request_approval(
    state: WorkflowState,
    approval_type: ApprovalType,
    title: str,
    description: str,
    details: Optional[Dict] = None,
) -> bool:
    """Request human approval via WebSocket and wait for response.

    Returns True if approved, False if rejected.
    """
    if not settings.human_in_the_loop:
        return True

    task_id = state.get("task_id", 0)

    # Create approval record
    async with get_session() as session:
        approval = Approval(
            task_id=task_id,
            approval_type=approval_type,
            status=ApprovalStatus.PENDING,
            title=title,
            description=description,
            details_json=json.dumps(details) if details else None,
        )
        session.add(approval)
        await session.commit()
        await session.refresh(approval)
        approval_id = approval.id

    await _update_task_status(state, TaskStatus.AWAITING_APPROVAL)

    # Send approval request via WebSocket
    callback = state.get("websocket_callback")
    if callback:
        await callback({
            "type": "approval_request",
            "task_id": task_id,
            "approval_id": approval_id,
            "approval_type": approval_type.value,
            "title": title,
            "description": description,
            "details": details,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    # Poll for approval response (with timeout)
    import asyncio

    max_wait = 600  # 10 minutes
    poll_interval = 2
    elapsed = 0

    while elapsed < max_wait:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

        async with get_session() as session:
            from sqlmodel import select

            result = await session.execute(
                select(Approval).where(Approval.id == approval_id)
            )
            approval = result.scalar_one_or_none()
            if approval and approval.status != ApprovalStatus.PENDING:
                return approval.status == ApprovalStatus.APPROVED

    # Timed out - treat as rejected
    await _log(state, "Approval request timed out", LogLevel.WARNING, "approval")
    return False


# ── Workflow Nodes ──────────────────────────────────────────────────────


async def research_node(state: WorkflowState) -> WorkflowState:
    """Research phase: search web for relevant information."""
    state["current_phase"] = "research"
    await _update_task_status(state, TaskStatus.RESEARCHING)
    await _log(state, "Starting research phase...", LogLevel.INFO, "research", 5)

    task_desc = state.get("task_description", "")
    research_results: List[Dict[str, Any]] = []

    try:
        # Search for relevant documentation
        search_results = await web_browser_service.search_web(
            f"{task_desc} programming solution",
            max_results=3,
        )

        for result in search_results:
            url = result.get("url", "")
            if url:
                content = await web_browser_service.fetch_page_content(url, max_length=3000)
                research_results.append({
                    "title": result.get("title", ""),
                    "url": url,
                    "content": content[:2000],
                })

        state["research_results"] = research_results
        await _log(
            state,
            f"Found {len(research_results)} relevant resources",
            LogLevel.SUCCESS,
            "research",
            10,
        )
    except Exception as e:
        await _log(state, f"Research error (non-fatal): {e}", LogLevel.WARNING, "research")
        state["research_results"] = []

    return state


async def analyze_node(state: WorkflowState) -> WorkflowState:
    """Analyze the task and determine approach."""
    state["current_phase"] = "analyze"
    await _log(state, "Analyzing task requirements...", LogLevel.INFO, "analyze", 15)

    task_desc = state.get("task_description", "")
    project_path = state.get("project_path", "")

    # Get codebase summary if project exists
    codebase_summary = ""
    if project_path and os.path.exists(project_path):
        summary = git_service.get_repo_summary(project_path)
        codebase_summary = summary.get("tree", "")

    # Use Gemini for structured analysis
    analysis = await ai_service.gemini_structured_output(
        prompt=f"Analyze this software engineering task:\n\n{task_desc}\n\nCodebase:\n{codebase_summary[:2000]}",
        schema_description=TASK_ANALYZER_PROMPT,
    )

    state["task_analysis"] = analysis
    await _log(
        state,
        f"Task type: {analysis.get('task_type', 'unknown')}, "
        f"Complexity: {analysis.get('complexity', 'unknown')}",
        LogLevel.INFO,
        "analyze",
        20,
    )
    return state


async def plan_node(state: WorkflowState) -> WorkflowState:
    """Create a detailed implementation plan."""
    state["current_phase"] = "plan"
    await _update_task_status(state, TaskStatus.PLANNING)
    await _log(state, "Creating implementation plan...", LogLevel.INFO, "plan", 25)

    task_desc = state.get("task_description", "")
    project_path = state.get("project_path", "")

    codebase_summary = ""
    if project_path and os.path.exists(project_path):
        summary = git_service.get_repo_summary(project_path)
        codebase_summary = summary.get("tree", "")

    # Use Gemini for planning
    plan = await ai_service.gemini_plan(task_desc, codebase_summary)
    state["implementation_plan"] = plan

    await _log(state, "Implementation plan created", LogLevel.SUCCESS, "plan", 30)

    # Request approval for the plan
    approved = await _request_approval(
        state,
        ApprovalType.PLAN_REVIEW,
        "Review Implementation Plan",
        "Please review the proposed implementation plan before coding begins.",
        {"plan": plan},
    )

    state["plan_approved"] = approved
    if not approved:
        await _log(state, "Plan rejected by reviewer", LogLevel.WARNING, "plan")
    else:
        await _log(state, "Plan approved, proceeding to code", LogLevel.SUCCESS, "plan", 35)

    return state


async def code_node(state: WorkflowState) -> WorkflowState:
    """Generate code based on the implementation plan."""
    state["current_phase"] = "code"
    await _update_task_status(state, TaskStatus.CODING)
    await _log(state, "Generating code...", LogLevel.INFO, "code", 40)

    task_desc = state.get("task_description", "")
    plan = state.get("implementation_plan", "")
    research = state.get("research_results", [])
    existing_code = state.get("generated_code", {})
    error_output = state.get("test_output", "") if state.get("retry_count", 0) > 0 else ""

    # Build context for Claude
    context_parts = [
        f"Task: {task_desc}",
        f"Implementation Plan:\n{plan}",
    ]

    if research:
        research_text = "\n".join(
            f"- {r.get('title', '')}: {r.get('content', '')[:500]}" for r in research
        )
        context_parts.append(f"Research:\n{research_text}")

    if existing_code and error_output:
        code_text = "\n\n".join(
            f"File: {path}\n```\n{content}\n```" for path, content in existing_code.items()
        )
        context_parts.append(f"Current code (needs fixes):\n{code_text}")
        context_parts.append(f"Error output:\n{error_output}")

    context_parts.append(
        "Generate the complete code for all files. "
        "Format each file as:\n"
        "### FILE: path/to/file.ext\n```\ncode here\n```\n"
    )

    full_context = "\n\n".join(context_parts)

    # Generate with Claude
    result = await ai_service.claude_code_generate(
        task_description=full_context,
        existing_code="" if not error_output else json.dumps(existing_code),
        error_output=error_output,
        language=state.get("code_language", "python"),
    )

    # Parse generated files
    generated = _parse_code_blocks(result)
    state["generated_code"] = generated

    await _log(
        state,
        f"Generated {len(generated)} file(s)",
        LogLevel.SUCCESS,
        "code",
        55,
    )

    # Write files to project directory
    project_path = state.get("project_path", "")
    if project_path:
        for file_path, content in generated.items():
            full_path = os.path.join(project_path, file_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            await _log(state, f"Wrote: {file_path}", LogLevel.INFO, "code")

    return state


async def test_node(state: WorkflowState) -> WorkflowState:
    """Run tests on the generated code."""
    state["current_phase"] = "test"
    await _update_task_status(state, TaskStatus.TESTING)
    await _log(state, "Running tests...", LogLevel.INFO, "test", 60)

    project_path = state.get("project_path", "")

    if not project_path or not os.path.exists(project_path):
        await _log(state, "No project path, skipping tests", LogLevel.WARNING, "test")
        state["tests_passed"] = True
        state["test_output"] = ""
        return state

    # Determine test command (with coverage)
    test_cmd = "pytest -v --tb=short --cov --cov-report=term-missing"
    if os.path.exists(os.path.join(project_path, "package.json")):
        test_cmd = "npm test -- --coverage"

    # Run tests in sandbox
    result = await sandbox_service.run_tests(
        project_path=project_path,
        test_command=test_cmd,
        timeout=settings.sandbox_timeout,
    )

    state["test_output"] = result.output
    state["tests_passed"] = result.success

    # Broadcast test results event
    callback = state.get("websocket_callback")
    if callback:
        await callback({
            "type": "test_results",
            "task_id": state.get("task_id", 0),
            "passed": result.success,
            "output": result.output[:2000],
            "attempt": state.get("retry_count", 0) + 1,
            "max_retries": settings.max_retries,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    if result.success:
        await _log(state, "All tests passed!", LogLevel.SUCCESS, "test", 75)
    else:
        await _log(
            state,
            f"Tests failed (attempt {state.get('retry_count', 0) + 1}/{settings.max_retries})",
            LogLevel.ERROR,
            "test",
            65,
        )

    return state


async def revise_node(state: WorkflowState) -> WorkflowState:
    """Revise code based on test failures."""
    state["current_phase"] = "revise"
    await _update_task_status(state, TaskStatus.REVISING)
    retry_count = state.get("retry_count", 0) + 1
    state["retry_count"] = retry_count

    await _log(
        state,
        f"Revising code (attempt {retry_count}/{settings.max_retries})...",
        LogLevel.WARNING,
        "revise",
        50,
    )

    # The code_node will use the error_output for self-correction
    return state


async def document_node(state: WorkflowState) -> WorkflowState:
    """Generate documentation for the changes."""
    state["current_phase"] = "document"
    await _update_task_status(state, TaskStatus.DOCUMENTING)
    await _log(state, "Generating documentation...", LogLevel.INFO, "document", 80)

    generated_code = state.get("generated_code", {})
    task_desc = state.get("task_description", "")

    if generated_code:
        code_summary = "\n".join(
            f"- {path}" for path in generated_code.keys()
        )

        # Generate docs with Gemini
        doc = await ai_service.gemini_document(
            code=code_summary,
            context=task_desc,
        )
        state["documentation"] = doc

        # Generate PR description
        pr_desc = await ai_service.claude_generate(
            system_prompt=PR_DESCRIPTION_PROMPT,
            user_message=(
                f"Task: {task_desc}\n\n"
                f"Files changed:\n{code_summary}\n\n"
                f"Test output:\n{state.get('test_output', 'N/A')[:500]}"
            ),
        )
        state["pr_description"] = pr_desc
    else:
        state["documentation"] = "No code changes to document."
        state["pr_description"] = "No changes."

    await _log(state, "Documentation generated", LogLevel.SUCCESS, "document", 85)
    return state


async def approve_pr_node(state: WorkflowState) -> WorkflowState:
    """Request approval to create a pull request."""
    state["current_phase"] = "approve_pr"
    await _log(state, "Requesting PR approval...", LogLevel.INFO, "approve_pr", 88)

    approved = await _request_approval(
        state,
        ApprovalType.PR_CREATION,
        "Approve Pull Request Creation",
        "The code has been generated and tests pass. Approve to create the PR.",
        {
            "pr_description": state.get("pr_description", ""),
            "files_changed": list(state.get("generated_code", {}).keys()),
            "test_output": state.get("test_output", "")[:500],
        },
    )

    state["pr_approved"] = approved
    if approved:
        await _log(state, "PR creation approved", LogLevel.SUCCESS, "approve_pr", 90)
    else:
        await _log(state, "PR creation rejected", LogLevel.WARNING, "approve_pr")

    return state


async def create_pr_node(state: WorkflowState) -> WorkflowState:
    """Create a GitHub pull request."""
    state["current_phase"] = "create_pr"
    await _update_task_status(state, TaskStatus.CREATING_PR)
    await _log(state, "Creating pull request...", LogLevel.INFO, "create_pr", 92)

    project_path = state.get("project_path", "")
    repo_name = state.get("repo_name", "")
    branch_name = state.get("branch_name", "")
    task_desc = state.get("task_description", "")

    if not project_path or not repo_name:
        await _log(state, "No repo configured, skipping PR creation", LogLevel.WARNING, "create_pr")
        state["pr_url"] = ""
        return state

    try:
        # Commit all changes
        commit_sha = git_service.commit_changes(
            repo_path=project_path,
            message=f"feat: {task_desc[:72]}",
        )

        # Broadcast commit event
        callback = state.get("websocket_callback")
        if callback:
            await callback({
                "type": "git_event",
                "task_id": state.get("task_id", 0),
                "event": "code_committed",
                "commit_sha": commit_sha[:8] if commit_sha else "",
                "commit_message": f"feat: {task_desc[:72]}",
                "files_changed": list(state.get("generated_code", {}).keys()),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        # Push branch
        git_service.push_branch(project_path, branch_name)

        # Broadcast push event
        if callback:
            await callback({
                "type": "git_event",
                "task_id": state.get("task_id", 0),
                "event": "branch_pushed",
                "branch_name": branch_name,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        # Create PR
        pr_result = git_service.create_pull_request(
            repo_name=repo_name,
            title=f"[AI] {task_desc[:100]}",
            body=state.get("pr_description", "Automated PR"),
            head_branch=branch_name,
        )

        state["pr_url"] = pr_result["pr_url"]
        state["pr_number"] = pr_result["pr_number"]

        # Broadcast PR creation event
        if callback:
            await callback({
                "type": "git_event",
                "task_id": state.get("task_id", 0),
                "event": "pr_created",
                "pr_url": pr_result["pr_url"],
                "pr_number": pr_result["pr_number"],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        # Update task in database
        async with get_session() as session:
            from sqlmodel import select

            result = await session.execute(
                select(Task).where(Task.id == state.get("task_id", 0))
            )
            task = result.scalar_one_or_none()
            if task:
                task.pr_url = pr_result["pr_url"]
                task.pr_number = pr_result["pr_number"]
                session.add(task)

        await _log(
            state,
            f"PR created: {pr_result['pr_url']}",
            LogLevel.SUCCESS,
            "create_pr",
            95,
        )

    except Exception as e:
        await _log(state, f"PR creation failed: {e}", LogLevel.ERROR, "create_pr")
        state["error"] = str(e)

    return state


async def complete_node(state: WorkflowState) -> WorkflowState:
    """Mark the task as completed."""
    state["current_phase"] = "complete"
    await _update_task_status(state, TaskStatus.COMPLETED)
    await _log(state, "Task completed successfully!", LogLevel.SUCCESS, "complete", 100)

    # Send completion event
    callback = state.get("websocket_callback")
    if callback:
        await callback({
            "type": "completed",
            "task_id": state.get("task_id", 0),
            "pr_url": state.get("pr_url", ""),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    return state


async def fail_node(state: WorkflowState) -> WorkflowState:
    """Mark the task as failed."""
    state["current_phase"] = "failed"
    error = state.get("error", "Unknown error")
    await _update_task_status(state, TaskStatus.FAILED)
    await _log(state, f"Task failed: {error}", LogLevel.ERROR, "failed", 0)

    # Update error in database
    async with get_session() as session:
        from sqlmodel import select

        result = await session.execute(
            select(Task).where(Task.id == state.get("task_id", 0))
        )
        task = result.scalar_one_or_none()
        if task:
            task.error_message = error
            session.add(task)

    callback = state.get("websocket_callback")
    if callback:
        await callback({
            "type": "failed",
            "task_id": state.get("task_id", 0),
            "error": error,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    return state


# ── Routing Functions ───────────────────────────────────────────────────


def route_after_plan(state: WorkflowState) -> Literal["code", "fail"]:
    """Route based on plan approval."""
    if state.get("plan_approved", True):
        return "code"
    return "fail"


def route_after_test(state: WorkflowState) -> Literal["document", "revise", "fail"]:
    """Route based on test results and retry count."""
    if state.get("tests_passed", False):
        return "document"
    if state.get("retry_count", 0) < settings.max_retries:
        return "revise"
    return "fail"


def route_after_approve_pr(state: WorkflowState) -> Literal["create_pr", "complete"]:
    """Route based on PR approval."""
    if state.get("pr_approved", True):
        return "create_pr"
    return "complete"


# ── Code Block Parser ──────────────────────────────────────────────────


def _parse_code_blocks(text: str) -> Dict[str, str]:
    """Parse FILE: markers and code blocks from AI output.

    Expected format:
    ### FILE: path/to/file.ext
    ```
    code content
    ```

    Returns:
        Dict mapping file paths to their content.
    """
    import re

    files: Dict[str, str] = {}

    # Match patterns like "### FILE: path" or "FILE: path" followed by a code block
    pattern = re.compile(
        r"(?:###?\s*)?FILE:\s*(.+?)\s*\n```[\w]*\n(.*?)```",
        re.DOTALL,
    )

    for match in pattern.finditer(text):
        file_path = match.group(1).strip()
        content = match.group(2).strip()
        files[file_path] = content

    # If no FILE: markers found, try to extract a single code block
    if not files:
        single_block = re.search(r"```[\w]*\n(.*?)```", text, re.DOTALL)
        if single_block:
            files["main.py"] = single_block.group(1).strip()

    return files


# ── Build the Graph ────────────────────────────────────────────────────


def build_workflow() -> StateGraph:
    """Build and compile the LangGraph workflow.

    Returns:
        Compiled StateGraph ready for execution.
    """
    workflow = StateGraph(WorkflowState)

    # Add nodes
    workflow.add_node("research", research_node)
    workflow.add_node("analyze", analyze_node)
    workflow.add_node("plan", plan_node)
    workflow.add_node("code", code_node)
    workflow.add_node("test", test_node)
    workflow.add_node("revise", revise_node)
    workflow.add_node("document", document_node)
    workflow.add_node("approve_pr", approve_pr_node)
    workflow.add_node("create_pr", create_pr_node)
    workflow.add_node("complete", complete_node)
    workflow.add_node("fail", fail_node)

    # Set entry point
    workflow.set_entry_point("research")

    # Add edges
    workflow.add_edge("research", "analyze")
    workflow.add_edge("analyze", "plan")
    workflow.add_conditional_edges("plan", route_after_plan, {"code": "code", "fail": "fail"})
    workflow.add_edge("code", "test")
    workflow.add_conditional_edges(
        "test",
        route_after_test,
        {"document": "document", "revise": "revise", "fail": "fail"},
    )
    workflow.add_edge("revise", "code")  # Loop back for self-correction
    workflow.add_edge("document", "approve_pr")
    workflow.add_conditional_edges(
        "approve_pr",
        route_after_approve_pr,
        {"create_pr": "create_pr", "complete": "complete"},
    )
    workflow.add_edge("create_pr", "complete")
    workflow.add_edge("complete", END)
    workflow.add_edge("fail", END)

    return workflow.compile()


# Module-level compiled workflow
orchestrator = build_workflow()


async def run_task(
    task_id: int,
    task_description: str,
    project_path: str = "",
    repo_name: str = "",
    branch_name: str = "",
    websocket_callback: Optional[Any] = None,
) -> WorkflowState:
    """Execute the full orchestrator workflow for a task.

    Args:
        task_id: Database task ID.
        task_description: Natural language task.
        project_path: Local path to the project.
        repo_name: GitHub repo name (owner/repo).
        branch_name: Git branch for changes.
        websocket_callback: Async callback for WebSocket updates.

    Returns:
        Final workflow state.
    """
    initial_state: WorkflowState = {
        "task_id": task_id,
        "task_description": task_description,
        "project_path": project_path,
        "repo_name": repo_name,
        "branch_name": branch_name or f"ai/task-{task_id}",
        "retry_count": 0,
        "websocket_callback": websocket_callback,
    }

    # Set up project directory if needed
    if project_path and not os.path.exists(project_path):
        os.makedirs(project_path, exist_ok=True)

    # Create branch if repo exists
    if project_path and os.path.exists(os.path.join(project_path, ".git")):
        try:
            branch = initial_state["branch_name"]
            git_service.create_branch(
                project_path,
                branch,
            )
            # Broadcast branch creation event
            if websocket_callback:
                await websocket_callback({
                    "type": "git_event",
                    "task_id": task_id,
                    "event": "branch_created",
                    "branch_name": branch,
                    "repo_name": repo_name,
                    "project_path": project_path,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
        except Exception as e:
            logger.warning("Could not create branch: %s", e)

    try:
        final_state = await orchestrator.ainvoke(initial_state)
        return final_state
    except Exception as e:
        logger.error("Workflow execution failed: %s", e, exc_info=True)
        initial_state["error"] = str(e)
        try:
            await fail_node(initial_state)
        except Exception as fail_err:
            logger.error("Failed to update task status to FAILED: %s", fail_err)
            # Last-resort: directly update the DB
            try:
                async with get_session() as session:
                    from sqlmodel import select
                    result = await session.execute(
                        select(Task).where(Task.id == task_id)
                    )
                    task = result.scalar_one_or_none()
                    if task:
                        task.status = TaskStatus.FAILED
                        task.error_message = str(e)
                        task.updated_at = datetime.utcnow()
                        session.add(task)
            except Exception:
                logger.exception("Last-resort DB update also failed")
        return initial_state
