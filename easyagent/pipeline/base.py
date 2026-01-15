from __future__ import annotations

import asyncio
import uuid
from abc import ABC, abstractmethod

from pydantic import BaseModel, Field

def _generate_node_id() -> str:
    return uuid.uuid4().hex[:8]


class NodeContext(BaseModel):
    """Base context for node execution. Subclasses define specific fields."""

    model_config = {"arbitrary_types_allowed": True, "extra": "allow"}


class BaseNode(BaseModel, ABC):
    """Abstract base class for DAG nodes."""

    node_id: str = Field(default_factory=_generate_node_id)
    successors: list["BaseNode"] = Field(default_factory=list)
    predecessors: list["BaseNode"] = Field(default_factory=list)

    model_config = {"arbitrary_types_allowed": True}

    def add(self, nodes: BaseNode | list[BaseNode]) -> BaseNode | list[BaseNode]:
        """Add successor node(s)."""
        node_list = [nodes] if isinstance(nodes, BaseNode) else nodes
        for node in node_list:
            if node not in self.successors:
                self.successors.append(node)
            if self not in node.predecessors:
                node.predecessors.append(self)
        return nodes

    def __rshift__(self, other: BaseNode | list[BaseNode]) -> BaseNode | list[BaseNode]:
        """Syntactic sugar for a >> b."""
        return self.add(other)

    @abstractmethod
    async def execute(self, ctx: NodeContext) -> None:
        """Execute node logic. Read inputs from ctx and write outputs to ctx."""


class BasePipeline(BaseModel):
    """DAG Pipeline. Executes nodes in parallel by level, sharing NodeContext."""

    root: BaseNode = Field(...)

    model_config = {"arbitrary_types_allowed": True}

    def _collect_nodes(self) -> list[BaseNode]:
        """Collect all nodes from root via DFS."""
        visited: set[str] = set()
        nodes: list[BaseNode] = []

        def dfs(node: BaseNode) -> None:
            if node.node_id in visited:
                return
            visited.add(node.node_id)
            nodes.append(node)
            for s in node.successors:
                dfs(s)

        dfs(self.root)
        return nodes

    async def run(self, ctx: NodeContext | None = None) -> NodeContext:
        """Execute nodes in parallel by level. All nodes share ctx."""
        if ctx is None:
            ctx = NodeContext()

        nodes = self._collect_nodes()
        node_map = {n.node_id: n for n in nodes}
        in_degree = {n.node_id: len(n.predecessors) for n in nodes}
        executed: set[str] = set()

        while len(executed) < len(nodes):
            ready = [nid for nid, deg in in_degree.items() if deg == 0 and nid not in executed]
            if not ready:
                raise ValueError("Cycle detected in DAG")

            await asyncio.gather(*[node_map[nid].execute(ctx) for nid in ready])

            for node_id in ready:
                executed.add(node_id)
                for s in node_map[node_id].successors:
                    in_degree[s.node_id] -= 1

        return ctx

    def visualize(self) -> str:
        """Return Mermaid-format DAG string."""
        lines = ["graph TD"]
        for node in self._collect_nodes():
            if not node.predecessors:
                lines.append(f"    {node.node_id}")
            for p in node.predecessors:
                lines.append(f"    {p.node_id} --> {node.node_id}")
        return "\n".join(lines)