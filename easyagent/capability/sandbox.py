from __future__ import annotations

from typing import Any

from easyagent.capability.base import BaseCapability
from easyagent.sandbox.base import BaseSandbox


class SandboxCapability(BaseCapability):
    def __init__(self, sandbox: BaseSandbox):
        self._sandbox = sandbox

    async def on_enter(self, agent: Any, session: Any) -> None:
        await self._sandbox.start()
        session.resources["sandbox"] = self._sandbox

    async def on_exit(self, agent: Any, session: Any) -> None:
        try:
            await self._sandbox.stop()
        finally:
            session.resources.pop("sandbox", None)
