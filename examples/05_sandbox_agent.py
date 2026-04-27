"""第 05 层：引入 Sandbox。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from easyagent import LiteLLMModel, SandboxAgent
from easyagent.sandbox import LocalSandbox


async def main() -> None:
    # SandboxAgent 预置了 bash、write_file、read_file 等沙箱工具。
    agent = SandboxAgent(
        model=LiteLLMModel("gpt-4o-mini"),
        sandbox=LocalSandbox(),
        max_iterations=6,
    )

    result = await agent.run("创建 hello.txt，内容为 hello EasyAgent，然后读回文件。")
    print(result.final_output)


if __name__ == "__main__":
    asyncio.run(main())
