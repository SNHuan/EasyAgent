"""第 04 层：引入 Skill。

SkillAgent = ReactAgent + 按需加载的 SKILL.md 包。

声明 ``skills=[...]`` 之后，agent 拿到的是这些 skill 的「短描述」+
``load_skill`` 等几个辅助工具。模型决定要用某个 skill 时调
``load_skill("name")``：skill 的完整正文进入 memory，``allowed-tools``
里声明的工具被激活。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from easyagent import LiteLLMModel, SkillAgent


class ProjectName:
    """返回当前项目名。"""

    name = "project_name"
    type = "function"
    description = "返回当前项目名。"
    parameters = {"type": "object", "properties": {}}

    def init(self) -> None:
        pass

    def execute(self) -> str:
        return "EasyAgent"


async def main() -> None:
    agent = SkillAgent(
        model=LiteLLMModel("gpt-4o-mini"),
        tools=[ProjectName],
        skills=["project-intro"],
        skill_root=Path(__file__).resolve().parent / "skills",
        max_iterations=5,
    )
    result = await agent.run("加载 project-intro skill，并按其中说明执行。")
    print(result.final_output)


if __name__ == "__main__":
    asyncio.run(main())
