import asyncio
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from easyagent import LiteLLMModel, ReactAgent
from easyagent.capability import SandboxCapability, SkillCapability, ToolCapability
from easyagent.context import SlidingWindowContext
from easyagent.loop import ReActLoop
from easyagent.memory import InMemoryMemory
from easyagent.sandbox import LocalSandbox
from easyagent.tool import register_tool


@register_tool
class GetProjectName:
    name = "get_project_name"
    type = "function"
    description = "Return the current project name."
    parameters = {
        "type": "object",
        "properties": {},
    }

    def init(self) -> None:
        pass

    def execute(self, **kwargs) -> str:
        return "EasyAgent"


def build_demo_skill(skill_root: Path) -> None:
    demo_dir = skill_root / "demo-workflow"
    demo_dir.mkdir(parents=True, exist_ok=True)
    (demo_dir / "SKILL.md").write_text(
        """---
name: demo-workflow
description: Use sandbox tools and the custom project tool to inspect the environment.
allowed-tools:
  - get_project_name
  - bash
  - write_file
  - read_file
---

# Demo Workflow

When this skill is loaded:

1. Call `get_project_name` to learn the current project name.
2. Use `bash` to inspect the sandbox environment if needed.
3. Use `write_file` to create a short note file.
4. Use `read_file` to verify the file contents.
5. Summarize clearly what you discovered.
""",
        encoding="utf-8",
    )


async def main() -> None:
    model_name = os.getenv("EA_EXAMPLE_MODEL", "gpt-4o-mini")
    prompt = os.getenv(
        "EA_EXAMPLE_PROMPT",
        (
            "Load the demo-workflow skill, find the project name, "
            "create note.txt containing that name, read it back, "
            "and tell me the final result."
        ),
    )

    model = LiteLLMModel(model=model_name)

    with tempfile.TemporaryDirectory(prefix="easyagent_skill_") as tmpdir:
        skill_root = Path(tmpdir)
        build_demo_skill(skill_root)

        agent = ReactAgent(
            model=model,
            system_prompt="You are a practical assistant. Use tools when needed and keep the final answer concise.",
            memory=InMemoryMemory(),
            context=SlidingWindowContext(max_messages=16),
            max_iterations=8,
            tools=["get_project_name"],
            skills=["demo-workflow"],
            skill_dir=str(skill_root),
            sandbox=LocalSandbox(),
        )

        result = await agent.run(prompt)


if __name__ == "__main__":
    asyncio.run(main())
