"""Docker sandbox service for safe code and test execution."""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

import docker
from docker.errors import ContainerError, ImageNotFound

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

SANDBOX_IMAGE = "aiswe-sandbox:latest"


def _docker_available() -> bool:
    """Check if Docker daemon is reachable and can actually run containers."""
    import platform
    try:
        client = docker.from_env()
        client.ping()
        # On Windows, Docker Desktop may respond to ping but fail on container ops
        # Do a lightweight container test to be sure
        if platform.system() == "Windows":
            client.containers.run(
                "hello-world", remove=True, network_disabled=True,
            )
        return True
    except Exception:
        return False


class SandboxResult:
    """Result of a sandbox execution."""

    def __init__(
        self,
        exit_code: int,
        stdout: str,
        stderr: str,
        timed_out: bool = False,
    ) -> None:
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.timed_out = timed_out

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    @property
    def output(self) -> str:
        return self.stdout + ("\n" + self.stderr if self.stderr else "")


class SandboxService:
    """Executes code and tests inside Docker containers, with local fallback."""

    def __init__(self) -> None:
        self._client: Optional[docker.DockerClient] = None
        self._docker_available: Optional[bool] = None

    @property
    def docker_available(self) -> bool:
        """Check and cache Docker availability."""
        if self._docker_available is None:
            self._docker_available = _docker_available()
            if not self._docker_available:
                logger.warning("Docker is not available — using local execution fallback")
        return self._docker_available

    @property
    def client(self) -> docker.DockerClient:
        """Lazy-initialize the Docker client."""
        if self._client is None:
            self._client = docker.from_env()
        return self._client

    async def ensure_image(self) -> None:
        """Build the sandbox image if it doesn't exist."""
        try:
            self.client.images.get(SANDBOX_IMAGE)
            logger.info("Sandbox image %s found", SANDBOX_IMAGE)
        except ImageNotFound:
            logger.info("Building sandbox image %s ...", SANDBOX_IMAGE)
            sandbox_dir = Path(__file__).resolve().parent.parent.parent.parent / "sandbox"
            if sandbox_dir.exists():
                self.client.images.build(
                    path=str(sandbox_dir),
                    dockerfile="Dockerfile.sandbox",
                    tag=SANDBOX_IMAGE,
                    rm=True,
                )
            else:
                logger.warning(
                    "Sandbox Dockerfile not found at %s, using python:3.11-slim",
                    sandbox_dir,
                )

    async def run_code(
        self,
        code: str,
        language: str = "python",
        timeout: Optional[int] = None,
        network_disabled: bool = True,
    ) -> SandboxResult:
        """Execute code in a sandboxed container.

        Args:
            code: Source code to run.
            language: Programming language.
            timeout: Execution timeout in seconds.
            network_disabled: Disable network access for safety.

        Returns:
            SandboxResult with output and exit code.
        """
        timeout = timeout or settings.sandbox_timeout

        # Local fallback when Docker is unavailable
        if not self.docker_available:
            return await self._run_local_code(code, language, timeout)

        # Write code to a temp file
        suffix = ".py" if language == "python" else ".js"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=suffix, delete=False, dir=tempfile.gettempdir()
        ) as f:
            f.write(code)
            code_path = f.name

        cmd = self._build_run_command(language, f"/workspace/code{suffix}")
        image = SANDBOX_IMAGE if self._image_exists(SANDBOX_IMAGE) else "python:3.11-slim"

        result = await self._run_container(
            image=image,
            command=cmd,
            volumes={code_path: {"bind": f"/workspace/code{suffix}", "mode": "ro"}},
            timeout=timeout,
            network_disabled=network_disabled,
        )

        # If Docker failed (non-timeout), retry with local execution
        if not result.success and not result.timed_out and not self.docker_available:
            logger.info("Retrying code execution locally after Docker failure")
            return await self._run_local_code(code, language, timeout)

        return result

    async def run_tests(
        self,
        project_path: str,
        test_command: str = "pytest -v",
        timeout: Optional[int] = None,
    ) -> SandboxResult:
        """Run tests in a sandboxed container, with local fallback.

        Args:
            project_path: Path to the project directory.
            test_command: Command to run tests.
            timeout: Execution timeout in seconds.

        Returns:
            SandboxResult with test output.
        """
        timeout = timeout or settings.sandbox_timeout

        # On Windows local execution, rewrite bare pytest/pip to python -m variants
        local_test_command = self._fix_command_for_local(test_command)

        # Local fallback when Docker is unavailable
        if not self.docker_available:
            # Install dependencies before running tests locally
            await self._install_local_deps(project_path)
            return await self._run_local_command(local_test_command, project_path, timeout)

        image = SANDBOX_IMAGE if self._image_exists(SANDBOX_IMAGE) else "python:3.11-slim"

        # Install deps then run tests
        cmd = f"cd /workspace && pip install -r requirements.txt 2>/dev/null; {test_command}"

        result = await self._run_container(
            image=image,
            command=f"bash -c '{cmd}'",
            volumes={project_path: {"bind": "/workspace", "mode": "ro"}},
            timeout=timeout,
            network_disabled=False,  # Need network for pip install
        )

        # If Docker failed (non-timeout), retry with local execution
        if not result.success and not result.timed_out and not self.docker_available:
            logger.info("Retrying test execution locally after Docker failure")
            await self._install_local_deps(project_path)
            return await self._run_local_command(local_test_command, project_path, timeout)

        return result

    async def run_command(
        self,
        command: str,
        working_dir: str,
        timeout: Optional[int] = None,
        network_disabled: bool = False,
    ) -> SandboxResult:
        """Run an arbitrary command in a sandboxed container.

        Args:
            command: Shell command to run.
            working_dir: Host directory to mount as /workspace.
            timeout: Execution timeout.
            network_disabled: Whether to disable networking.

        Returns:
            SandboxResult.
        """
        timeout = timeout or settings.sandbox_timeout

        local_command = self._fix_command_for_local(command)

        # Local fallback when Docker is unavailable
        if not self.docker_available:
            return await self._run_local_command(local_command, working_dir, timeout)

        image = SANDBOX_IMAGE if self._image_exists(SANDBOX_IMAGE) else "python:3.11-slim"

        result = await self._run_container(
            image=image,
            command=f"bash -c 'cd /workspace && {command}'",
            volumes={working_dir: {"bind": "/workspace", "mode": "rw"}},
            timeout=timeout,
            network_disabled=network_disabled,
        )

        # If Docker failed (non-timeout), retry with local execution
        if not result.success and not result.timed_out and not self.docker_available:
            logger.info("Retrying command execution locally after Docker failure")
            return await self._run_local_command(local_command, working_dir, timeout)

        return result

    async def _run_container(
        self,
        image: str,
        command: str,
        volumes: dict,
        timeout: int,
        network_disabled: bool = True,
    ) -> SandboxResult:
        """Run a container with safety constraints.

        Args:
            image: Docker image to use.
            command: Command to execute.
            volumes: Volume mounts.
            timeout: Timeout in seconds.
            network_disabled: Disable network access.

        Returns:
            SandboxResult.
        """
        container = None
        try:
            container = self.client.containers.run(
                image=image,
                command=command,
                volumes=volumes,
                mem_limit="512m",
                cpu_period=100000,
                cpu_quota=50000,  # 50% CPU
                network_disabled=network_disabled,
                remove=False,  # We'll remove after getting logs
                detach=True,
                user="nobody",
            )

            # Wait for completion
            result = container.wait(timeout=timeout)
            exit_code = result.get("StatusCode", 1)

            stdout = container.logs(stdout=True, stderr=False).decode("utf-8", errors="replace")
            stderr = container.logs(stdout=False, stderr=True).decode("utf-8", errors="replace")

            return SandboxResult(
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
            )

        except Exception as e:
            error_msg = str(e)
            timed_out = "timed out" in error_msg.lower() or "read timed out" in error_msg.lower()

            if timed_out:
                logger.warning("Container timed out after %ds", timeout)
                if container:
                    try:
                        container.kill()
                    except Exception:
                        pass

            # If Docker fails for non-timeout reasons, mark it unavailable for future calls
            if not timed_out:
                logger.warning(
                    "Docker container failed, disabling Docker for future calls: %s",
                    error_msg,
                )
                self._docker_available = False

            return SandboxResult(
                exit_code=1,
                stdout="",
                stderr=f"Container execution error: {error_msg}",
                timed_out=timed_out,
            )

        finally:
            # Always clean up the container
            if container:
                try:
                    container.remove(force=True)
                except Exception:
                    pass

    def _build_run_command(self, language: str, file_path: str) -> str:
        """Build the execution command for a given language."""
        commands = {
            "python": f"python {file_path}",
            "javascript": f"node {file_path}",
            "typescript": f"npx ts-node {file_path}",
        }
        return commands.get(language, f"python {file_path}")

    def _image_exists(self, image_name: str) -> bool:
        """Check if a Docker image exists locally."""
        try:
            self.client.images.get(image_name)
            return True
        except ImageNotFound:
            return False

    @staticmethod
    def _fix_command_for_local(command: str) -> str:
        """Rewrite commands for local Windows execution.

        Converts bare tool names (pytest, pip, etc.) to ``python -m`` equivalents
        so they work even when the tool isn't on PATH.
        """
        import re
        import platform

        if platform.system() != "Windows":
            return command

        # Map bare commands to python -m equivalents
        replacements = {
            r'\bpytest\b': 'python -m pytest',
            r'\bpip\b': 'python -m pip',
            r'\bflake8\b': 'python -m flake8',
            r'\bmypy\b': 'python -m mypy',
            r'\bblack\b': 'python -m black',
            r'\bisort\b': 'python -m isort',
            r'\bcoverage\b': 'python -m coverage',
        }
        result = command
        for pattern, replacement in replacements.items():
            result = re.sub(pattern, replacement, result)
        return result

    async def _run_local_command(
        self,
        command: str,
        cwd: str,
        timeout: int,
    ) -> SandboxResult:
        """Fallback: run a command locally when Docker is unavailable."""
        logger.info("Running locally (no Docker): %s (cwd=%s)", command, cwd)
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(), timeout=timeout
                )
                output = SandboxResult(
                    exit_code=process.returncode or 0,
                    stdout=stdout_bytes.decode("utf-8", errors="replace"),
                    stderr=stderr_bytes.decode("utf-8", errors="replace"),
                )
                # Auto-detect missing module errors and retry after installing
                if not output.success:
                    missing = self._detect_missing_modules(output.output)
                    if missing:
                        logger.info("Detected missing modules: %s — installing", missing)
                        install_cmd = self._fix_command_for_local(
                            f"pip install {' '.join(missing)}"
                        )
                        install_proc = await asyncio.create_subprocess_shell(
                            install_cmd,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                            cwd=cwd,
                        )
                        await asyncio.wait_for(install_proc.communicate(), timeout=120)
                        # Retry the original command
                        logger.info("Retrying command after installing: %s", missing)
                        process2 = await asyncio.create_subprocess_shell(
                            command,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                            cwd=cwd,
                        )
                        stdout2, stderr2 = await asyncio.wait_for(
                            process2.communicate(), timeout=timeout
                        )
                        return SandboxResult(
                            exit_code=process2.returncode or 0,
                            stdout=stdout2.decode("utf-8", errors="replace"),
                            stderr=stderr2.decode("utf-8", errors="replace"),
                        )
                return output
            except asyncio.TimeoutError:
                process.kill()
                return SandboxResult(
                    exit_code=1, stdout="", stderr="Local execution timed out", timed_out=True,
                )
        except Exception as e:
            return SandboxResult(exit_code=1, stdout="", stderr=f"Local execution error: {e}")

    async def _install_local_deps(self, project_path: str) -> None:
        """Install dependencies from requirements.txt (or package.json) locally before tests."""
        req_file = os.path.join(project_path, "requirements.txt")
        if os.path.exists(req_file):
            install_cmd = self._fix_command_for_local(f"pip install -r requirements.txt")
            logger.info("Installing local deps: %s", install_cmd)
            try:
                proc = await asyncio.create_subprocess_shell(
                    install_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=project_path,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
                if proc.returncode != 0:
                    logger.warning(
                        "Dep install had errors: %s",
                        stderr.decode("utf-8", errors="replace")[:500],
                    )
                else:
                    logger.info("Dependencies installed successfully")
            except Exception as e:
                logger.warning("Failed to install deps: %s", e)

        pkg_file = os.path.join(project_path, "package.json")
        if os.path.exists(pkg_file) and not os.path.exists(
            os.path.join(project_path, "node_modules")
        ):
            logger.info("Running npm install in %s", project_path)
            try:
                proc = await asyncio.create_subprocess_shell(
                    "npm install",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=project_path,
                )
                await asyncio.wait_for(proc.communicate(), timeout=120)
            except Exception as e:
                logger.warning("npm install failed: %s", e)

    @staticmethod
    def _detect_missing_modules(output: str) -> list[str]:
        """Parse test output for ModuleNotFoundError and return missing module names."""
        import re
        modules = re.findall(
            r"ModuleNotFoundError: No module named ['\"]([^'\"]+)['\"]", output
        )
        # Deduplicate while preserving order; take top-level package name
        seen = set()
        result = []
        for mod in modules:
            top_level = mod.split(".")[0]
            if top_level not in seen:
                seen.add(top_level)
                result.append(top_level)
        return result

    async def _run_local_code(
        self,
        code: str,
        language: str,
        timeout: int,
    ) -> SandboxResult:
        """Fallback: run code locally when Docker is unavailable."""
        suffix = ".py" if language == "python" else ".js"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=suffix, delete=False, dir=tempfile.gettempdir()
        ) as f:
            f.write(code)
            code_path = f.name

        cmd = self._build_run_command(language, code_path)
        return await self._run_local_command(cmd, tempfile.gettempdir(), timeout)


# Module-level singleton
sandbox_service = SandboxService()
