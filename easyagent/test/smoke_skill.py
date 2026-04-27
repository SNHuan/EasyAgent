"""Manual smoke test: end-to-end Skills flow with a real LLM.

Run: python -m easyagent.test.smoke_skill
Requires easyagent/config/config.yaml with gemini-3-flash-preview configured.
"""

import asyncio
import shutil
import sys
from pathlib import Path

from easyagent import SkillAgent
from easyagent.config.base import ModelConfig
from easyagent.model.litellm_model import LiteLLMModel
from easyagent.skill import SkillManager
from easyagent.tool import register_tool


DEFAULT_MODEL = "gemini-3-flash-preview"


@register_tool
class GetWeatherSmoke:
    name = "get_weather_smoke"
    type = "function"
    description = "Get the weather for a city (smoke test stub)."
    parameters = {
        "type": "object",
        "properties": {"city": {"type": "string", "description": "City name"}},
        "required": ["city"],
    }

    def init(self) -> None:
        pass

    def execute(self, city: str) -> str:
        return f"The weather in {city} is sunny, 25C."


async def main() -> None:
    skill_dir = Path(__file__).parent / "_smoke_skills"
    if skill_dir.exists():
        shutil.rmtree(skill_dir)
    target = skill_dir / "weather-smoke"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text(
        "---\n"
        "name: weather-smoke\n"
        "description: Answer weather questions by calling get_weather_smoke.\n"
        "allowed-tools:\n"
        "  - get_weather_smoke\n"
        "---\n\n"
        "# Weather Smoke\n"
        "When the user asks about weather, call get_weather_smoke with the city, "
        "then reply with a one-sentence summary.\n",
        encoding="utf-8",
    )

    config = ModelConfig.load()
    model_name = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MODEL
    print(f"Using model: {model_name}")
    model = LiteLLMModel(**config.get_model(model_name))

    skill_manager = SkillManager(include_default_dirs=False)

    agent = SkillAgent(
        model=model,
        tools=[GetWeatherSmoke()],
        skills=["weather-smoke"],
        skill_root=skill_dir,
        skill_manager=skill_manager,
        max_iterations=6,
    )

    print("=" * 60)
    print("system_prompt excerpt:")
    session = agent.create_session()
    lines = agent.build_system_prompt(session).splitlines()
    # Print the "Available Skills" section only, to keep output tight
    try:
        idx = lines.index("## Available Skills")
        print("\n".join(lines[idx : idx + 6]))
    except ValueError:
        print("(Available Skills section not found — bug!)")
    print("=" * 60)
    print("tools before run:", session.enabled_tools)

    result = await agent.run("北京天气怎么样?", session=session)

    print("=" * 60)
    print("tools after run:", session.enabled_tools)
    print("result:", result.final_output)
    assert "get_weather_smoke" in session.enabled_tools, (
        "get_weather_smoke should have been activated by load_skill"
    )
    print("\nSMOKE OK")


if __name__ == "__main__":
    asyncio.run(main())
