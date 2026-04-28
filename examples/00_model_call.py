"""第 00 层：直接调用模型。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from easyagent import LiteLLMModel


async def main() -> None:
    # 这里只使用 Model 层，还没有 Agent、Memory、Loop 或 Tool。
    model = LiteLLMModel("gpt-4o-mini")

    response = await model.call(
        "用一句话解释什么是 Agent SDK。",
        system_prompt="回答要简洁。",
    )
    print(response.content)


if __name__ == "__main__":
    asyncio.run(main())
