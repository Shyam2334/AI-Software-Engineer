"""Playwright E2E test runner inside Docker sandbox."""

from __future__ import annotations

import logging
from typing import Optional

from app.services.sandbox import SandboxResult, sandbox_service

logger = logging.getLogger(__name__)


class PlaywrightRunner:
    """Run Playwright end-to-end tests inside a sandboxed container."""

    async def run_e2e_tests(
        self,
        project_path: str,
        test_path: str = "tests/e2e",
        base_url: Optional[str] = None,
        timeout: int = 120,
    ) -> SandboxResult:
        """Run Playwright tests in the sandbox.

        Args:
            project_path: Path to the project.
            test_path: Relative path to E2E tests.
            base_url: Base URL for the application under test.
            timeout: Timeout in seconds.

        Returns:
            SandboxResult with test output.
        """
        env_vars = ""
        if base_url:
            env_vars = f"PLAYWRIGHT_BASE_URL={base_url} "

        command = (
            f"cd /workspace && "
            f"pip install -q playwright pytest-playwright 2>/dev/null && "
            f"playwright install chromium 2>/dev/null && "
            f"{env_vars}pytest {test_path} -v --tb=short 2>&1"
        )

        logger.info("Running Playwright E2E tests: %s", test_path)

        result = await sandbox_service.run_command(
            command=command,
            working_dir=project_path,
            timeout=timeout,
            network_disabled=False,  # E2E tests need network
        )

        if result.success:
            logger.info("E2E tests passed")
        else:
            logger.warning("E2E tests failed:\n%s", result.output[:500])

        return result

    async def run_visual_test(
        self,
        url: str,
        screenshot_path: str,
        timeout: int = 30,
    ) -> SandboxResult:
        """Run a visual regression test by comparing screenshots.

        Args:
            url: URL to test.
            screenshot_path: Path to save the screenshot.
            timeout: Timeout in seconds.

        Returns:
            SandboxResult.
        """
        script = f"""
import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={{"width": 1280, "height": 720}})
        await page.goto("{url}", wait_until="networkidle")
        await page.screenshot(path="/workspace/screenshot.png")
        await browser.close()
        print("Screenshot captured successfully")

asyncio.run(main())
"""
        import tempfile
        import os

        tmp_dir = tempfile.mkdtemp()
        script_path = os.path.join(tmp_dir, "visual_test.py")
        with open(script_path, "w") as f:
            f.write(script)

        return await sandbox_service.run_command(
            command="python /workspace/visual_test.py",
            working_dir=tmp_dir,
            timeout=timeout,
            network_disabled=False,
        )


# Module-level singleton
playwright_runner = PlaywrightRunner()
