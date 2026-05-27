"""Minimal FastMCP literature server used by MCP config examples."""

from __future__ import annotations

from fastmcp import FastMCP


mcp = FastMCP("literature")


@mcp.tool(tags={"literature", "demo"})
def search_literature(topic: str, top_k: int = 3) -> list[dict]:
    """Return demo literature records for a topic."""
    return [
        {
            "title": f"Demo paper {index + 1} about {topic}",
            "abstract": "This is a local example result from a FastMCP tool.",
        }
        for index in range(top_k)
    ]


if __name__ == "__main__":
    mcp.run()
