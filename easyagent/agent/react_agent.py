from easyagent.agent.agent import Agent
from easyagent.capability import SandboxCapability, SkillCapability, ToolCapability
from easyagent.context.base import BaseContext
from easyagent.loop.react import ReActLoop
from easyagent.memory.base import BaseMemory
from easyagent.model.base import BaseLLM
from easyagent.sandbox.base import BaseSandbox


class ReactAgent(Agent):
    def __init__(
        self,
        model: BaseLLM,
        *,
        system_prompt: str = "",
        max_iterations: int = 10,
        memory: BaseMemory | None = None,
        context: BaseContext | None = None,
        tools: list[str] | None = None,
        skills: list[str] | None = None,
        skill_dir: str | None = None,
        sandbox: BaseSandbox | None = None,
    ):
        capabilities = []
        if sandbox is not None:
            capabilities.append(SandboxCapability(sandbox))
        capabilities.append(ToolCapability(tools=tools or []))
        if skills:
            capabilities.append(SkillCapability(skills=skills, skill_dir=skill_dir))

        super().__init__(
            model=model,
            loop=ReActLoop(max_iterations=max_iterations),
            memory=memory,
            context=context,
            system_prompt=system_prompt,
            capabilities=capabilities,
        )
