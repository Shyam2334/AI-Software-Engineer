"""Web browser service using httpx for web research."""

from __future__ import annotations

import logging
import re
from html import unescape
from typing import List, Optional
from urllib.parse import quote_plus

import httpx

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}


def _strip_html(html: str) -> str:
    """Remove HTML tags and decode entities."""
    text = re.sub(r"<[^>]+>", " ", html)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


class WebBrowserService:
    """HTTP-based web research service (no Playwright dependency)."""

    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers=_HEADERS,
                follow_redirects=True,
                timeout=httpx.Timeout(15.0),
            )
        return self._client

    async def search_web(self, query: str, max_results: int = 5) -> List[dict]:
        """Search the web using DuckDuckGo.

        Args:
            query: Search query.
            max_results: Maximum number of results.

        Returns:
            List of dicts with title, url, and snippet.
        """
        results: List[dict] = []
        try:
            from ddgs import DDGS

            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=max_results):
                    results.append({
                        "title": r.get("title", ""),
                        "url": r.get("href", ""),
                        "snippet": r.get("body", ""),
                    })

            logger.info("Web search for '%s': %d results", query[:80], len(results))

        except Exception as e:
            logger.warning("Web search error: %s", e)

        return results

    async def fetch_page_content(self, url: str, max_length: int = 10000) -> str:
        """Fetch and extract text content from a web page.

        Args:
            url: URL to fetch.
            max_length: Maximum characters to return.

        Returns:
            Extracted text content.
        """
        try:
            resp = await self.client.get(url)
            resp.raise_for_status()
            html = resp.text

            # Try to extract <main>, <article>, or <body> content
            for tag in ["main", "article"]:
                match = re.search(
                    rf"<{tag}[^>]*>(.*?)</{tag}>", html, re.DOTALL | re.IGNORECASE
                )
                if match:
                    content = _strip_html(match.group(1))
                    if len(content) > 100:
                        return content[:max_length]

            # Fallback to body
            body_match = re.search(
                r"<body[^>]*>(.*?)</body>", html, re.DOTALL | re.IGNORECASE
            )
            if body_match:
                content = _strip_html(body_match.group(1))
                return content[:max_length]

            return _strip_html(html)[:max_length]

        except Exception as e:
            logger.warning("Page fetch error for %s: %s", url, e)
            return f"Error fetching page: {e}"

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None


# Module-level singleton
web_browser_service = WebBrowserService()
