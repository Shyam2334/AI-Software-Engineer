"""LangGraph orchestrator for multi-step AI software engineering workflow.

Nodes: research → analyze → plan → (approve plan) → code → test → revise → document → (approve PR) → create_pr
"""

from __future__ import annotations

import json
import logging
import os
import re
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

    # Uploaded document context
    document_context: Optional[str]


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
    await _log(state, "Starting research phase — searching the web for documentation, tutorials, and best practices relevant to your task...", LogLevel.INFO, "research", 5)

    task_desc = state.get("task_description", "")
    research_results: List[Dict[str, Any]] = []

    # Include uploaded document context as a research source
    doc_context = state.get("document_context", "")
    if doc_context:
        await _log(state, f"Including uploaded document ({len(doc_context)} chars) as reference context", LogLevel.INFO, "research")
        research_results.append({
            "title": "Uploaded Document Context",
            "url": "user-upload",
            "content": doc_context[:5000],
        })

    try:
        # Clean up the task description for a better search query
        search_query = re.sub(r"\[(?:FEATURE|BUG|REFACTOR|TEST|DOCS)\]\s*", "", task_desc)
        # Take just the first line/sentence if multi-line
        search_query = search_query.strip().split("\n")[0][:200]

        await _log(state, f"Search query: \"{search_query[:100]}\"", LogLevel.INFO, "research")

        # Search for relevant documentation
        search_results = await web_browser_service.search_web(
            f"{search_query} programming solution",
            max_results=3,
        )

        if search_results:
            await _log(state, f"Found {len(search_results)} result(s) — fetching and reading page content...", LogLevel.INFO, "research")
            for i, result in enumerate(search_results, 1):
                title = result.get("title", "")
                url = result.get("url", "")
                await _log(state, f"Reading ({i}/{len(search_results)}): {title}", LogLevel.INFO, "research")
                if url:
                    content = await web_browser_service.fetch_page_content(url, max_length=3000)
                    research_results.append({
                        "title": title,
                        "url": url,
                        "content": content[:2000],
                    })
        else:
            await _log(state, "No search results found, proceeding with built-in knowledge", LogLevel.WARNING, "research")

        state["research_results"] = research_results
        await _log(
            state,
            f"Gathered {len(research_results)} resource(s) — ready for analysis",
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
    await _log(state, "Starting analysis — examining task requirements and scanning your project structure...", LogLevel.INFO, "analyze", 15)

    task_desc = state.get("task_description", "")
    project_path = state.get("project_path", "")

    # Get codebase summary if project exists
    codebase_summary = ""
    if project_path and os.path.exists(project_path):
        await _log(state, "Scanning project files and directory structure...", LogLevel.INFO, "analyze")
        summary = git_service.get_repo_summary(project_path)
        codebase_summary = summary.get("tree", "")
        file_count = codebase_summary.count("\n") if codebase_summary else 0
        await _log(state, f"Found {file_count} files in project", LogLevel.INFO, "analyze")

    # Use Gemini for structured analysis
    await _log(state, "Calling Gemini AI to classify task type, estimate complexity, and determine the best approach (this may take a few seconds)...", LogLevel.INFO, "analyze")
    analysis = await ai_service.gemini_structured_output(
        prompt=f"Analyze this software engineering task:\n\n{task_desc}\n\nCodebase:\n{codebase_summary[:2000]}",
        schema_description=TASK_ANALYZER_PROMPT,
    )

    state["task_analysis"] = analysis
    await _log(
        state,
        f"Analysis complete — Type: {analysis.get('task_type', 'unknown')}, "
        f"Complexity: {analysis.get('complexity', 'unknown')}",
        LogLevel.SUCCESS,
        "analyze",
        20,
    )
    return state


async def plan_node(state: WorkflowState) -> WorkflowState:
    """Create a detailed implementation plan."""
    state["current_phase"] = "plan"
    await _update_task_status(state, TaskStatus.PLANNING)
    await _log(state, "Creating a detailed step-by-step implementation plan...", LogLevel.INFO, "plan", 25)

    task_desc = state.get("task_description", "")
    project_path = state.get("project_path", "")

    codebase_summary = ""
    if project_path and os.path.exists(project_path):
        summary = git_service.get_repo_summary(project_path)
        codebase_summary = summary.get("tree", "")

    # Use Gemini for planning
    await _log(state, "Generating a detailed plan including file structure, dependencies, and test strategy — Gemini is thinking...", LogLevel.INFO, "plan")
    plan = await ai_service.gemini_plan(task_desc, codebase_summary)
    state["implementation_plan"] = plan

    await _log(state, "Implementation plan ready — awaiting your approval", LogLevel.SUCCESS, "plan", 30)

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

    retry_count = state.get("retry_count", 0)
    if retry_count > 0:
        await _log(state, f"Regenerating code based on error analysis (revision {retry_count}) — fixing the issues found in the previous attempt...", LogLevel.INFO, "code", 40)
    else:
        await _log(state, "Starting code generation — Claude will write production-quality source code and tests. This is the longest step and may take 30-90 seconds depending on complexity...", LogLevel.INFO, "code", 40)

    task_desc = state.get("task_description", "")
    plan = state.get("implementation_plan", "")
    research = state.get("research_results", [])
    existing_code = state.get("generated_code", {})
    error_output = state.get("test_output", "") if state.get("retry_count", 0) > 0 else ""
    project_path = state.get("project_path", "")

    await _log(state, "Building context: combining task, plan, research, and codebase into a single prompt...", LogLevel.INFO, "code", 42)

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

    # Include uploaded document context directly
    doc_context = state.get("document_context", "")
    if doc_context:
        context_parts.append(
            f"UPLOADED REFERENCE DOCUMENT (use this as context for your implementation):\n\n{doc_context[:5000]}"
        )

    # Read existing source and test files so AI knows the current codebase
    if project_path and os.path.exists(project_path):
        await _log(state, "Reading existing project files so AI preserves class names, imports, and signatures...", LogLevel.INFO, "code", 44)
        existing_files = _read_project_files(project_path)
        if existing_files:
            await _log(state, f"Loaded {len(existing_files)} existing file(s) as context ({sum(len(c) for c in existing_files.values()) // 1024}KB)", LogLevel.INFO, "code")
            existing_text = "\n\n".join(
                f"### EXISTING FILE: {path}\n```\n{content}\n```"
                for path, content in existing_files.items()
            )
            context_parts.append(
                f"EXISTING CODEBASE (you MUST preserve all existing imports, class names, "
                f"function signatures, and exports that tests depend on):\n\n{existing_text}"
            )

    if existing_code and error_output:
        code_text = "\n\n".join(
            f"File: {path}\n```\n{content}\n```" for path, content in existing_code.items()
        )
        context_parts.append(f"Current code (needs fixes):\n{code_text}")
        context_parts.append(f"Error output:\n{error_output}")

        # Include structured error analysis from revise_node
        error_analysis = state.get("error_analysis", "")
        if error_analysis:
            context_parts.append(f"ERROR ANALYSIS (follow these directives precisely):\n{error_analysis}")

        error_classes = state.get("error_classification", [])
        if error_classes:
            fix_hints = []
            if "attribute_error" in error_classes:
                fix_hints.append(
                    "FIX PRIORITY: AttributeError — Your class is MISSING attributes or methods "
                    "that tests expect. Read the error_analysis carefully and ADD every missing "
                    "attribute/method to the class. Check test code to see how they are used."
                )
            if "import_mismatch" in error_classes:
                fix_hints.append(
                    "FIX PRIORITY: Import mismatches detected. Existing test files expect specific "
                    "class/function names. Read the test imports carefully and ensure your code "
                    "exports EXACTLY those names."
                )
            if "name_error" in error_classes:
                fix_hints.append(
                    "FIX PRIORITY: NameError — Some names are not defined. Ensure all classes, "
                    "functions, and variables referenced in tests are properly defined and imported."
                )
            if "type_error" in error_classes:
                fix_hints.append(
                    "FIX PRIORITY: TypeError — Function signatures don't match how tests call them. "
                    "Check test code to see the expected arguments and return types."
                )
            if "syntax_error" in error_classes:
                fix_hints.append(
                    "FIX PRIORITY: Syntax errors detected. Ensure all files have valid syntax."
                )
            if "test_assertion_failure" in error_classes:
                fix_hints.append(
                    "FIX PRIORITY: Test assertions are failing. Review the test expectations "
                    "and ensure your implementation produces the correct output/behavior."
                )
            if "missing_dependencies" in error_classes:
                fix_hints.append(
                    "NOTE: Missing dependencies have been auto-installed. Focus on code fixes."
                )
            if fix_hints:
                context_parts.append("FIX INSTRUCTIONS:\n" + "\n".join(f"- {h}" for h in fix_hints))

    context_parts.append(
        "Generate the complete code for all files. "
        "IMPORTANT: Preserve existing class names, function names, and module-level exports "
        "that are imported by tests. Do NOT rename classes or remove exports.\n"
        "Format each file as:\n"
        "### FILE: path/to/file.ext\n```\ncode here\n```\n"
    )

    full_context = "\n\n".join(context_parts)
    context_size_kb = len(full_context) // 1024
    await _log(state, f"Prompt assembled ({context_size_kb}KB) — sending to Claude for code generation. Larger prompts take longer...", LogLevel.INFO, "code", 46)

    # Generate with Claude
    result = await ai_service.claude_code_generate(
        task_description=full_context,
        existing_code="" if not error_output else json.dumps(existing_code),
        error_output=error_output,
        language=state.get("code_language", "python"),
    )

    await _log(state, "Claude responded — parsing generated code into individual files...", LogLevel.INFO, "code", 50)

    # Parse generated files
    generated = _parse_code_blocks(result)
    state["generated_code"] = generated

    file_list = ", ".join(generated.keys()) if len(generated) <= 5 else f"{', '.join(list(generated.keys())[:5])} +{len(generated)-5} more"
    total_lines = sum(content.count('\n') + 1 for content in generated.values())
    await _log(
        state,
        f"Generated {len(generated)} file(s), {total_lines} lines total: {file_list}",
        LogLevel.SUCCESS,
        "code",
        55,
    )

    # Write files to project directory
    project_path = state.get("project_path", "")
    if project_path:
        await _log(state, f"Writing {len(generated)} file(s) to project directory...", LogLevel.INFO, "code", 56)
        for file_path, content in generated.items():
            full_path = os.path.join(project_path, file_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            await _log(state, f"Wrote: {file_path} ({len(content)} chars)", LogLevel.INFO, "code")
        await _log(state, "All files written — ready for testing", LogLevel.SUCCESS, "code", 58)

    return state


async def test_node(state: WorkflowState) -> WorkflowState:
    """Run tests on the generated code."""
    state["current_phase"] = "test"
    await _update_task_status(state, TaskStatus.TESTING)
    await _log(state, "Starting test phase — running the test suite to verify code compiles, passes all assertions, and behaves correctly...", LogLevel.INFO, "test", 60)

    project_path = state.get("project_path", "")

    if not project_path or not os.path.exists(project_path):
        await _log(state, "No project path configured — skipping tests", LogLevel.WARNING, "test")
        state["tests_passed"] = True
        state["test_output"] = ""
        return state

    # Determine test command (with coverage)
    test_cmd = "pytest -v --tb=short --cov --cov-report=term-missing"
    if os.path.exists(os.path.join(project_path, "package.json")):
        test_cmd = "npm test -- --coverage"

    await _log(state, f"Executing: {test_cmd}", LogLevel.INFO, "test")
    await _log(state, "Waiting for test runner to finish (timeout: {timeout}s)...".format(timeout=settings.sandbox_timeout), LogLevel.INFO, "test", 62)

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

    retry_count = state.get("retry_count", 0)
    total_attempts = settings.max_retries + 1
    if result.success:
        await _log(state, "All tests passed! Code is verified and ready for review.", LogLevel.SUCCESS, "test", 75)
    else:
        error_summary = _summarize_test_error(result.output)
        await _log(
            state,
            f"Tests failed (attempt {retry_count + 1}/{total_attempts}): {error_summary}",
            LogLevel.ERROR,
            "test",
            65,
        )

    return state


async def revise_node(state: WorkflowState) -> WorkflowState:
    """Revise code based on test failures — analyze errors and auto-fix when possible."""
    state["current_phase"] = "revise"
    await _update_task_status(state, TaskStatus.REVISING)
    retry_count = state.get("retry_count", 0) + 1
    state["retry_count"] = retry_count

    test_output = state.get("test_output", "")
    project_path = state.get("project_path", "")

    await _log(
        state,
        f"Analyzing test failures (retry {retry_count}/{settings.max_retries}) — reading error output to determine root cause...",
        LogLevel.WARNING,
        "revise",
        50,
    )

    # ── Auto-fix: missing dependencies ──────────────────────────────
    missing_modules = re.findall(
        r"ModuleNotFoundError: No module named ['\"]([^'\"]+)['\"]", test_output
    )
    if missing_modules and project_path:
        unique_mods = list(dict.fromkeys(m.split(".")[0] for m in missing_modules))
        await _log(
            state,
            f"Auto-fixing: installing missing modules {unique_mods}",
            LogLevel.INFO,
            "revise",
        )
        install_cmd = sandbox_service._fix_command_for_local(
            f"pip install {' '.join(unique_mods)}"
        )
        import asyncio as _aio
        proc = await _aio.create_subprocess_shell(
            install_cmd,
            stdout=_aio.subprocess.PIPE,
            stderr=_aio.subprocess.PIPE,
            cwd=project_path,
        )
        await _aio.wait_for(proc.communicate(), timeout=120)

    # ── Auto-fix: missing imports / name mismatches ─────────────────
    import_errors = re.findall(
        r"ImportError: cannot import name ['\"]([^'\"]+)['\"] from ['\"]([^'\"]+)['\"]",
        test_output,
    )

    # ── Detect AttributeError (missing attributes/methods on objects) ──
    attr_errors = re.findall(
        r"AttributeError: '([^']+)' object has no attribute '([^']+)'",
        test_output,
    )

    # ── Detect NameError (undefined variables/classes) ──────────────
    name_errors = re.findall(
        r"NameError: name '([^']+)' is not defined",
        test_output,
    )

    # ── Detect TypeError (wrong signatures/args) ───────────────────
    type_errors = re.findall(
        r"TypeError: (.+?)\n",
        test_output,
    )

    # Build structured error analysis for code_node
    analysis_parts = []

    if import_errors:
        names = [f"{name} from {mod}" for name, mod in import_errors]
        await _log(
            state,
            f"Detected import mismatches: {names}",
            LogLevel.WARNING,
            "revise",
        )
        analysis_parts.append(
            "IMPORT ERRORS — The following imports are used by existing tests and MUST exist:\n"
            + "\n".join(
                f"  - `from {mod} import {name}` — ensure `{name}` is defined/exported in `{mod.replace('.', '/')}.py`"
                for name, mod in import_errors
            )
        )

    if attr_errors:
        await _log(
            state,
            f"Detected missing attributes: {[(cls, attr) for cls, attr in attr_errors]}",
            LogLevel.WARNING,
            "revise",
        )
        analysis_parts.append(
            "ATTRIBUTE ERRORS — Tests expect these attributes/methods to exist:\n"
            + "\n".join(
                f"  - Class `{cls}` MUST have attribute/method `{attr}`. Add it to the class definition."
                for cls, attr in attr_errors
            )
        )

    if name_errors:
        await _log(
            state,
            f"Detected undefined names: {name_errors}",
            LogLevel.WARNING,
            "revise",
        )
        analysis_parts.append(
            "NAME ERRORS — These names must be defined:\n"
            + "\n".join(f"  - `{name}` is not defined — ensure it is imported or declared" for name in name_errors)
        )

    if type_errors:
        await _log(
            state,
            f"Detected type errors: {type_errors[:3]}",
            LogLevel.WARNING,
            "revise",
        )
        analysis_parts.append(
            "TYPE ERRORS — Fix these signature/argument mismatches:\n"
            + "\n".join(f"  - {err}" for err in type_errors[:5])
        )

    if analysis_parts:
        state["error_analysis"] = "CRITICAL FIX REQUIREMENTS:\n\n" + "\n\n".join(analysis_parts)

    # ── Auto-fix: syntax errors ─────────────────────────────────────
    syntax_errors = re.findall(
        r"SyntaxError: (.+?)\n", test_output
    )
    if syntax_errors:
        await _log(
            state,
            f"Detected syntax errors: {syntax_errors[:3]}",
            LogLevel.WARNING,
            "revise",
        )

    # ── Classify overall error type for better AI prompting ─────────
    error_classification = []
    if missing_modules:
        error_classification.append("missing_dependencies")
    if import_errors:
        error_classification.append("import_mismatch")
    if attr_errors:
        error_classification.append("attribute_error")
    if name_errors:
        error_classification.append("name_error")
    if type_errors:
        error_classification.append("type_error")
    if syntax_errors:
        error_classification.append("syntax_error")
    if "AssertionError" in test_output or "FAILED" in test_output:
        error_classification.append("test_assertion_failure")
    if not error_classification:
        error_classification.append("unknown")

    state["error_classification"] = error_classification
    await _log(
        state,
        f"Error diagnosis complete — found {len(error_classification)} issue type(s): {', '.join(error_classification)}",
        LogLevel.INFO,
        "revise",
    )
    await _log(
        state,
        "Sending error analysis back to code generation for a targeted fix...",
        LogLevel.INFO,
        "revise",
        52,
    )

    return state


async def document_node(state: WorkflowState) -> WorkflowState:
    """Generate documentation for the changes."""
    state["current_phase"] = "document"
    await _update_task_status(state, TaskStatus.DOCUMENTING)
    await _log(state, "Starting documentation phase — generating inline docs, README updates, and a detailed PR description...", LogLevel.INFO, "document", 80)

    generated_code = state.get("generated_code", {})
    task_desc = state.get("task_description", "")

    if generated_code:
        code_summary = "\n".join(
            f"- {path}" for path in generated_code.keys()
        )

        # Generate docs with Gemini
        await _log(state, "Calling Gemini to generate documentation for the changed files...", LogLevel.INFO, "document", 82)
        doc = await ai_service.gemini_document(
            code=code_summary,
            context=task_desc,
        )
        state["documentation"] = doc

        # Generate PR description
        await _log(state, "Calling Claude to write a detailed pull request description...", LogLevel.INFO, "document", 84)
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

    await _log(state, "Documentation and PR description ready", LogLevel.SUCCESS, "document", 85)
    return state


async def approve_pr_node(state: WorkflowState) -> WorkflowState:
    """Request approval to create a pull request."""
    state["current_phase"] = "approve_pr"
    await _log(state, "Code is ready — requesting your approval to create the pull request...", LogLevel.INFO, "approve_pr", 88)

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
    await _log(state, "Starting PR creation — committing changes, pushing branch to GitHub, and opening a pull request...", LogLevel.INFO, "create_pr", 92)

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
        await _log(state, "Staging and committing all generated files...", LogLevel.INFO, "create_pr")
        commit_sha = git_service.commit_changes(
            repo_path=project_path,
            message=f"feat: {task_desc[:72]}",
        )
        await _log(state, f"Committed: {commit_sha[:8]}", LogLevel.INFO, "create_pr")

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
        await _log(state, f"Pushing branch '{branch_name}' to remote...", LogLevel.INFO, "create_pr", 93)
        git_service.push_branch(project_path, branch_name)
        await _log(state, "Branch pushed successfully", LogLevel.SUCCESS, "create_pr")

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
        await _log(state, "Creating pull request on GitHub via API...", LogLevel.INFO, "create_pr", 94)
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
    # Build a meaningful error message from available context
    error = state.get("error", "")
    if not error:
        test_output = state.get("test_output", "")
        if test_output:
            # Extract the most useful part of test output
            error = _summarize_test_error(test_output)
        else:
            error = "Unknown error"
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


# ── Helper Functions ────────────────────────────────────────────────────


def _summarize_test_error(test_output: str, max_len: int = 500) -> str:
    """Extract a concise error summary from raw test output."""
    if not test_output:
        return "No test output captured"

    lines = test_output.strip().splitlines()

    # Look for pytest's short test summary
    summary_lines = []
    in_summary = False
    for line in lines:
        if "short test summary" in line.lower() or "FAILED" in line:
            in_summary = True
        if in_summary:
            summary_lines.append(line)

    # Look for key error patterns
    error_patterns = [
        r"(ModuleNotFoundError: .+)",
        r"(ImportError: .+)",
        r"(SyntaxError: .+)",
        r"(AttributeError: .+)",
        r"(NameError: .+)",
        r"(TypeError: .+)",
        r"(AssertionError.*)",
        r"(FileNotFoundError: .+)",
    ]
    errors_found = []
    for pattern in error_patterns:
        matches = re.findall(pattern, test_output)
        errors_found.extend(matches[:2])

    if errors_found:
        result = "; ".join(dict.fromkeys(errors_found))  # deduplicate, preserve order
    elif summary_lines:
        result = "\n".join(summary_lines[-5:])
    else:
        # Last 5 non-empty lines as fallback
        result = "\n".join(line for line in lines[-10:] if line.strip())

    return result[:max_len]


def _read_project_files(project_path: str, max_total_chars: int = 50000) -> Dict[str, str]:
    """Read source and test files from a project for context.

    Prioritizes test files (so the AI knows expected imports/signatures),
    then source files. Caps total chars to avoid prompt overflow.
    """
    EXTENSIONS = {".py", ".js", ".ts", ".jsx", ".tsx"}
    SKIP_DIRS = {".git", "node_modules", "__pycache__", "venv", ".venv", ".tox", "dist", "build"}

    files: Dict[str, str] = {}
    total_chars = 0

    # Collect file paths, tests first
    test_paths: list[str] = []
    src_paths: list[str] = []

    for root, dirs, filenames in os.walk(project_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        rel_root = os.path.relpath(root, project_path)

        for fname in sorted(filenames):
            _, ext = os.path.splitext(fname)
            if ext not in EXTENSIONS:
                continue
            rel_path = os.path.join(rel_root, fname).replace("\\", "/")
            if rel_path.startswith("./"):
                rel_path = rel_path[2:]
            full_path = os.path.join(root, fname)

            if "test" in rel_path.lower():
                test_paths.append((rel_path, full_path))
            else:
                src_paths.append((rel_path, full_path))

    # Read tests first, then source
    for rel_path, full_path in test_paths + src_paths:
        if total_chars >= max_total_chars:
            break
        try:
            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            # Cap individual file at 5000 chars
            if len(content) > 5000:
                content = content[:5000] + "\n# ... (truncated)"
            files[rel_path] = content
            total_chars += len(content)
        except Exception:
            continue

    return files


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
    document_context: str = "",
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
        "document_context": document_context,
    }

    # Set up project directory if needed
    if project_path and not os.path.exists(project_path):
        os.makedirs(project_path, exist_ok=True)

    # Create branch if repo exists
    if project_path and os.path.exists(os.path.join(project_path, ".git")):
        try:
            branch = initial_state["branch_name"]
            logger.info("Pulling latest from default branch and creating branch %s...", branch)
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
                await websocket_callback({
                    "type": "log",
                    "task_id": task_id,
                    "message": f"Pulled latest code from default branch and created working branch: {branch}",
                    "level": "info",
                    "phase": "setup",
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
