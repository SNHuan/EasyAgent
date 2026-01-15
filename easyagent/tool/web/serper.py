"""Serper Google Search Tool - https://serper.dev"""

import os
from typing import Any

import httpx

from easyagent.tool.manager import register_tool


@register_tool
class SerperSearch:
    """Google Search via Serper API"""

    name = "serper_search"
    type = "function"
    description = "Search the web using Google via Serper API. Returns top search results."
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query",
            },
            "num_results": {
                "type": "integer",
                "description": "Number of results to return (default: 5, max: 10)",
            },
        },
        "required": ["query"],
    }

    _api_key: str | None = None

    def init(self) -> None:
        self._api_key = os.environ.get("SERPER_API_KEY")

    def execute(self, query: str, num_results: int = 5, **kwargs: Any) -> str:
        if not self._api_key:
            return "Error: SERPER_API_KEY environment variable not set"

        num_results = min(max(1, num_results), 10)

        try:
            response = httpx.post(
                "https://google.serper.dev/search",
                headers={
                    "X-API-KEY": self._api_key,
                    "Content-Type": "application/json",
                },
                json={"q": query, "num": num_results},
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            return _format_results(data, num_results)
        except httpx.HTTPStatusError as e:
            return f"Error: HTTP {e.response.status_code} - {e.response.text}"
        except Exception as e:
            return f"Error: {e}"


def _format_results(data: dict[str, Any], limit: int) -> str:
    """Format search results into readable text"""
    lines: list[str] = []

    # Knowledge Graph (if present)
    if kg := data.get("knowledgeGraph"):
        lines.append(f"[Knowledge Graph] {kg.get('title', '')}")
        if desc := kg.get("description"):
            lines.append(f"  {desc}")
        lines.append("")

    # Answer Box (if present)
    if answer := data.get("answerBox"):
        if snippet := answer.get("snippet") or answer.get("answer"):
            lines.append(f"[Answer] {snippet}")
            lines.append("")

    # Organic Results
    organic = data.get("organic", [])[:limit]
    for i, result in enumerate(organic, 1):
        title = result.get("title", "No title")
        link = result.get("link", "")
        snippet = result.get("snippet", "")
        lines.append(f"{i}. {title}")
        lines.append(f"   URL: {link}")
        if snippet:
            lines.append(f"   {snippet}")
        lines.append("")

    return "\n".join(lines).strip() or "No results found"
