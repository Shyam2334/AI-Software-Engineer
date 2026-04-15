"""Safe terminal execution service with dangerous command detection."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Patterns for dangerous commands that require human approval
DANGEROUS_PATTERNS: list[re.Pattern] = [
    re.compile(r"\brm\s+-rf\b", re.IGNORECASE),
    re.compile(r"\brm\s+-r\b", re.IGNORECASE),
    re.compile(r"\bsudo\b", re.IGNORECASE),
    re.compile(r"\bchmod\s+777\b", re.IGNORECASE),
    re.compile(r"\bmkfs\b", re.IGNORECASE),
    re.compile(r"\bdd\s+if=", re.IGNORECASE),
    re.compile(r"\b(shutdown|reboot|init\s+[0-6])\b", re.IGNORECASE),
    re.compile(r"\bkill\s+-9\b", re.IGNORECASE),
    re.compile(r"\bdrop\s+(database|table)\b", re.IGNORECASE),
    re.compile(r"\btruncate\b", re.IGNORECASE),
    re.compile(r"\bgit\s+push\s+--force\b", re.IGNORECASE),
    re.compile(r"\bgit\s+reset\s+--hard\b", re.IGNORECASE),
    re.compile(r"\bcurl\b.*\|\s*(bash|sh)\b", re.IGNORECASE),
    re.compile(r"\bwget\b.*\|\s*(bash|sh)\b", re.IGNORECASE),
    re.compile(r"\bformat\b", re.IGNORECASE),
    re.compile(r"\b>\s*/dev/", re.IGNORECASE),
]

# Commands that are always blocked
BLOCKED_COMMANDS: list[str] = [
    "rm -rf /",
    "rm -rf /*",
    ":(){ :|:& };:",
    "mkfs.",
]


class TerminalResult:
    """Result of a terminal command execution."""

    def __init__(
        self,
        exit_code: int,
        stdout: str,
        stderr: str,
        command: str,
        timed_out: bool = False,
    ) -> None:
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.command = command
        self.timed_out = timed_out

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    @property
    def output(self) -> str:
        return self.stdout + ("\n" + self.stderr if self.stderr else "")


class TerminalService:
    """Execute terminal commands with safety guards."""

    def is_dangerous(self, command: str) -> bool:
        """Check if a command matches any dangerous patterns.

        Args:
            command: Shell command to check.

        Returns:
            True if the command is considered dangerous.
        """
        for pattern in DANGEROUS_PATTERNS:
            if pattern.search(command):
                return True
        return False

    def is_blocked(self, command: str) -> bool:
        """Check if a command is in the blocked list.

        Args:
            command: Shell command to check.

        Returns:
            True if the command is blocked.
        """
        normalized = command.strip().lower()
        for blocked in BLOCKED_COMMANDS:
            if blocked in normalized:
                return True
        return False

    async def execute(
        self,
        command: str,
        cwd: Optional[str] = None,
        timeout: int = 60,
        env: Optional[dict] = None,
    ) -> TerminalResult:
        """Execute a terminal command safely.

        Args:
            command: Shell command to run.
            cwd: Working directory.
            timeout: Timeout in seconds.
            env: Additional environment variables.

        Returns:
            TerminalResult with output.

        Raises:
            PermissionError: If the command is blocked.
        """
        if self.is_blocked(command):
            logger.error("Blocked dangerous command: %s", command)
            raise PermissionError(f"Command is blocked for safety: {command}")

        logger.info("Executing: %s (cwd=%s, timeout=%d)", command, cwd, timeout)

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(), timeout=timeout
                )
                stdout = stdout_bytes.decode("utf-8", errors="replace")
                stderr = stderr_bytes.decode("utf-8", errors="replace")

                return TerminalResult(
                    exit_code=process.returncode or 0,
                    stdout=stdout,
                    stderr=stderr,
                    command=command,
                )

            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                logger.warning("Command timed out after %ds: %s", timeout, command)
                return TerminalResult(
                    exit_code=1,
                    stdout="",
                    stderr=f"Command timed out after {timeout} seconds",
                    command=command,
                    timed_out=True,
                )

        except Exception as e:
            logger.error("Command execution error: %s", e)
            return TerminalResult(
                exit_code=1,
                stdout="",
                stderr=str(e),
                command=command,
            )


# Module-level singleton
terminal_service = TerminalService()
