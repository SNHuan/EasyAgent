"""第 14 层（进阶）：spatial world —— 空间感知 + 移动。

到 13 你已经看完了 Entity-World-Schedule 的全部对话用法。这一层展示
**为什么**架构要解耦成三个正交协议——因为 World 可以换。

``SpatialWorld`` 让 Entity 拥有 2D 位置。Perception 里多了一个
``SpatialSlice``（自己的坐标 + 附近的 Entity ID），``Move`` action
可以改变位置。Speak 仍然有效但受距离限制——只有在 listen_radius 内
的 Entity 才能"听到"。

同样的 Entity、Schedule、Runtime——换一个 World 就得到完全不同的行为。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from easyagent import (
    MaxTicks,
    Perception,
    RoundRobin,
    Runtime,
    Speak,
    Move,
    Composite,
    SpatialWorld,
    Grid2D,
)
from easyagent.core.types import Action, SpatialSlice


# 非 LLM Entity——根据空间位置决定行为

class ExplorerEntity:
    """四处移动，遇到邻居就打招呼。"""

    def __init__(self, entity_id: str, target: tuple[int, int]) -> None:
        self._id = entity_id
        self._target = target
        self._greeted = False

    @property
    def id(self) -> str:
        return self._id

    async def act(self, perception: Perception) -> Action | None:
        spatial = perception.of_type(SpatialSlice)
        if spatial is None:
            return Speak(content=f"{self._id} 看不到空间信息")

        if spatial.nearby and not self._greeted:
            self._greeted = True
            neighbors = ", ".join(spatial.nearby)
            return Composite(actions=(
                Speak(content=f"你好 {neighbors}！我在 {spatial.position}"),
                Move(target=self._target),
            ))

        if spatial.position != self._target:
            return Move(target=self._target)

        return Speak(content=f"{self._id} 到达目标 {self._target}")


async def main() -> None:
    grid = Grid2D()
    grid.place("alice", (0, 0))
    grid.place("bob", (1, 1))
    grid.place("carol", (10, 10))

    world = SpatialWorld(grid=grid, listen_radius=3.0)

    schedule = MaxTicks(
        inner=RoundRobin(ids=["alice", "bob", "carol"]),
        n=6,
    )

    alice = ExplorerEntity("alice", target=(5, 5))
    bob = ExplorerEntity("bob", target=(2, 2))
    carol = ExplorerEntity("carol", target=(5, 5))

    rt = Runtime(
        world=world,
        entities={"alice": alice, "bob": bob, "carol": carol},
        schedule=schedule,
    )

    result = await rt.run("开始探索")

    print("=== 行动记录 ===")
    for eid, action in result.actions:
        if isinstance(action, Speak):
            print(f"[{eid} 说] {action.content}")
        elif isinstance(action, Move):
            print(f"[{eid} 移动到] {action.target}")
        elif isinstance(action, Composite):
            for sub in action.actions:
                if isinstance(sub, Speak):
                    print(f"[{eid} 说] {sub.content}")
                elif isinstance(sub, Move):
                    print(f"[{eid} 移动到] {sub.target}")

    print(f"\n最终位置: {grid.positions}")

    # ── 关键观察 ───────────────────────────────────────────────────────
    # 1. alice 和 bob 初始距离 √2 ≈ 1.4 < listen_radius=3，互相可见；
    #    carol 在 (10,10)，离两人都很远，初始不可见；
    # 2. 同一个 Entity 协议同时处理 Speak 和 Move——不需要改 Entity 接口；
    # 3. Composite action 让一个 Entity 在一个 tick 内同时说话+移动；
    # 4. 这一切只是换了 World 实现，Schedule 和 Runtime 完全不变。


if __name__ == "__main__":
    asyncio.run(main())
