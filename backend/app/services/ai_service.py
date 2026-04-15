"""AI model service for Claude (Anthropic) and Gemini (Google) integration."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any, Dict, List, Optional

import anthropic
from google import genai
from google.genai import types as genai_types

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Retry config for transient API errors (429, 503, etc.)
_MAX_RETRIES = 3
_RETRY_BACKOFF = [2, 5, 10]  # seconds


class AIService:
    """Unified service for interacting with Claude and Gemini models."""

    def __init__(self) -> None:
        self._anthropic_client: Optional[anthropic.AsyncAnthropic] = None
        self._gemini_client: Optional[genai.Client] = None

    @property
    def anthropic(self) -> anthropic.AsyncAnthropic:
        """Lazy-initialize the Anthropic async client."""
        if self._anthropic_client is None:
            self._anthropic_client = anthropic.AsyncAnthropic(
                api_key=settings.anthropic_api_key
            )
        return self._anthropic_client

    @property
    def gemini(self) -> genai.Client:
        """Lazy-initialize the Google GenAI client."""
        if self._gemini_client is None:
            self._gemini_client = genai.Client(api_key=settings.gemini_api_key)
        return self._gemini_client

    # ── Claude Methods ──────────────────────────────────────────────────

    async def claude_generate(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int | None = None,
        temperature: float = 0.3,
    ) -> str:
        """Generate a response from Claude Opus.

        Args:
            system_prompt: System-level instructions.
            user_message: The user's request / context.
            max_tokens: Maximum tokens in the response (defaults to settings).
            temperature: Sampling temperature.

        Returns:
            The assistant's text response.
        """
        if max_tokens is None:
            max_tokens = settings.claude_max_tokens

        try:
            response = await self.anthropic.messages.create(
                model=settings.claude_model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )

            # Extract text from response content blocks
            text_parts: List[str] = []
            for block in response.content:
                if block.type == "text":
                    text_parts.append(block.text)

            result = "\n".join(text_parts)
            logger.info(
                "Claude response: %d chars, usage: %s",
                len(result),
                response.usage,
            )
            return result

        except anthropic.APIError as e:
            logger.error("Claude API error: %s", e)
            raise

    async def claude_code_generate(
        self,
        task_description: str,
        existing_code: str = "",
        error_output: str = "",
        language: str = "python",
    ) -> str:
        """Generate or fix code using Claude.

        Args:
            task_description: What to build or fix.
            existing_code: Current code (for revisions).
            error_output: Test/lint error output (for debugging).
            language: Programming language.

        Returns:
            Generated or revised code.
        """
        system = (
            "You are an expert software engineer. Write clean, well-tested, "
            "production-quality code. Return ONLY the code with no extra commentary. "
            "Use proper error handling, type hints, and follow best practices."
        )

        user_parts = [f"Task: {task_description}", f"Language: {language}"]
        if existing_code:
            user_parts.append(f"Existing code to revise:\n```{language}\n{existing_code}\n```")
        if error_output:
            user_parts.append(f"Error output from tests:\n```\n{error_output}\n```")
            user_parts.append(
                "Fix the code so these errors are resolved. Return the complete fixed code."
            )

        return await self.claude_generate(
            system_prompt=system,
            user_message="\n\n".join(user_parts),
        )

    async def claude_analyze(self, content: str, question: str) -> str:
        """Analyze code or content with Claude.

        Args:
            content: The content to analyze.
            question: What to analyze about it.

        Returns:
            Analysis text.
        """
        system = (
            "You are a senior software architect. Analyze the provided content "
            "and answer the question thoroughly. Be specific and actionable."
        )
        user_msg = f"Content:\n{content}\n\nQuestion: {question}"
        return await self.claude_generate(
            system_prompt=system,
            user_message=user_msg,
        )

    async def claude_vision_analyze(
        self,
        images: List[Dict[str, str]],
        user_message: str,
        system_prompt: str = "",
    ) -> str:
        """Analyze images using Claude's vision capabilities.

        Args:
            images: List of dicts with 'data' (base64) and 'media_type' keys.
            user_message: The user's question/instructions about the images.
            system_prompt: Optional system instructions.

        Returns:
            Claude's analysis of the images.
        """
        if not system_prompt:
            system_prompt = (
                "You are an expert UI/UX designer and software engineer. "
                "Analyze the provided image(s) carefully. If they show UI screenshots, "
                "identify design issues, layout problems, visual bugs, accessibility concerns, "
                "and suggest specific fixes with code changes. If the images show error messages, "
                "stack traces, or diagrams, interpret them accurately. "
                "Be specific about element positions, colors, spacing, and any issues you find."
            )

        # Build multimodal content blocks
        content_blocks: List[Dict[str, Any]] = []

        for i, img in enumerate(images):
            content_blocks.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": img.get("media_type", "image/png"),
                    "data": img["data"],
                },
            })
            if len(images) > 1:
                content_blocks.append({
                    "type": "text",
                    "text": f"[Image {i + 1} of {len(images)}]",
                })

        content_blocks.append({
            "type": "text",
            "text": user_message,
        })

        try:
            response = await self.anthropic.messages.create(
                model=settings.claude_model,
                max_tokens=settings.claude_max_tokens,
                temperature=0.3,
                system=system_prompt,
                messages=[{"role": "user", "content": content_blocks}],
            )

            text_parts: List[str] = []
            for block in response.content:
                if block.type == "text":
                    text_parts.append(block.text)

            result = "\n".join(text_parts)
            logger.info(
                "Claude vision response: %d chars, %d image(s), usage: %s",
                len(result),
                len(images),
                response.usage,
            )
            return result

        except anthropic.APIError as e:
            logger.error("Claude Vision API error: %s", e)
            raise

    # ── Gemini Methods ──────────────────────────────────────────────────

    async def gemini_generate(
        self,
        prompt: str,
        system_instruction: str = "",
        temperature: float = 0.2,
        max_output_tokens: int = 8192,
    ) -> str:
        """Generate a response from Gemini Pro 2.5.

        Args:
            prompt: User prompt.
            system_instruction: System-level instructions.
            temperature: Sampling temperature.
            max_output_tokens: Max output tokens.

        Returns:
            Generated text.
        """
        try:
            config = genai_types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                system_instruction=system_instruction or None,
            )

            last_err: Optional[Exception] = None
            for attempt in range(_MAX_RETRIES):
                try:
                    response = await self.gemini.aio.models.generate_content(
                        model=settings.gemini_model,
                        contents=prompt,
                        config=config,
                    )
                    result = response.text or ""
                    logger.info("Gemini response: %d chars", len(result))
                    return result
                except Exception as e:
                    last_err = e
                    err_str = str(e)
                    # Retry on transient errors (503, 429)
                    if "503" in err_str or "429" in err_str or "UNAVAILABLE" in err_str:
                        wait = _RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)]
                        logger.warning(
                            "Gemini transient error (attempt %d/%d), retrying in %ds: %s",
                            attempt + 1, _MAX_RETRIES, wait, e,
                        )
                        await asyncio.sleep(wait)
                    else:
                        raise

            # All retries exhausted — fall back to Claude
            logger.warning("Gemini unavailable after %d retries, falling back to Claude", _MAX_RETRIES)
            return await self.claude_generate(
                system_prompt=system_instruction or "You are a helpful AI assistant.",
                user_message=prompt,
                max_tokens=min(max_output_tokens * 4, settings.claude_max_tokens),
            )

        except Exception as e:
            logger.error("Gemini API error: %s", e)
            raise

    async def gemini_plan(self, task_description: str, codebase_summary: str = "") -> str:
        """Create an implementation plan using Gemini.

        Args:
            task_description: What needs to be done.
            codebase_summary: Summary of existing codebase.

        Returns:
            Structured plan as text.
        """
        system = (
            "You are a technical project planner. Create detailed, step-by-step "
            "implementation plans. Output as structured markdown with phases, "
            "files to modify, and estimated complexity."
        )
        prompt_parts = [f"Task: {task_description}"]
        if codebase_summary:
            prompt_parts.append(f"Codebase summary:\n{codebase_summary}")
        prompt_parts.append(
            "Create a detailed implementation plan with:\n"
            "1. Analysis of the task\n"
            "2. Files to create or modify\n"
            "3. Step-by-step implementation approach\n"
            "4. Testing strategy\n"
            "5. Potential risks"
        )
        return await self.gemini_generate(
            prompt="\n\n".join(prompt_parts),
            system_instruction=system,
            temperature=0.2,
        )

    async def gemini_document(self, code: str, context: str = "") -> str:
        """Generate documentation for code using Gemini.

        Args:
            code: The code to document.
            context: Additional context.

        Returns:
            Documentation text.
        """
        system = (
            "You are a technical writer. Write clear, concise documentation. "
            "Include usage examples, parameter descriptions, and return values."
        )
        prompt = f"Generate documentation for this code:\n```\n{code}\n```"
        if context:
            prompt += f"\n\nContext: {context}"
        return await self.gemini_generate(
            prompt=prompt,
            system_instruction=system,
            temperature=0.3,
        )

    async def gemini_structured_output(
        self, prompt: str, schema_description: str
    ) -> Dict[str, Any]:
        """Get structured JSON output from Gemini.

        Args:
            prompt: The request.
            schema_description: Description of expected JSON structure.

        Returns:
            Parsed JSON dict.
        """
        system = (
            "You are a structured data generator. Output ONLY valid JSON "
            "matching the requested schema. No extra text."
        )
        full_prompt = (
            f"{prompt}\n\nExpected JSON schema:\n{schema_description}\n\n"
            "Return ONLY valid JSON."
        )
        result = await self.gemini_generate(
            prompt=full_prompt,
            system_instruction=system,
            temperature=0.1,
        )

        # Strip markdown code fences if present
        cleaned = result.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = lines[1:]  # Remove opening fence
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning("Failed to parse Gemini structured output, returning raw")
            return {"raw_output": result}


# Module-level singleton
ai_service = AIService()
