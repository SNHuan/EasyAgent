"""Tests for easyagent.skill — loader, manager, ReactAgent integration."""

from pathlib import Path

import pytest

from easyagent.model.schema import LLMResponse, ToolCall


# -------- fixtures --------

@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset SkillManager and ToolManager caches between tests."""
    from easyagent.skill import SkillManager
    from easyagent.tool import ToolManager

    SkillManager().reset()
    yield
    SkillManager().reset()
    # Tool registry is populated at import time; clearing would break subsequent tests.
    ToolManager()._ensure_discovered()


def _write_skill(base: Path, name: str, body: str = "Body here.", tools=None) -> Path:
    """Helper: create <base>/<name>/SKILL.md."""
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    front = [f"name: {name}", f"description: summary of {name}"]
    if tools:
        front.append("allowed-tools:")
        front.extend(f"  - {t}" for t in tools)
    front_text = "\n".join(front)
    (d / "SKILL.md").write_text(f"---\n{front_text}\n---\n{body}\n", encoding="utf-8")
    return d


class FakeLLM:
    """Scripted responses for ReactAgent integration tests."""

    def __init__(self, responses: list[LLMResponse]):
        self._responses = list(responses)
        self.calls: list[list[dict]] = []

    async def call(self, *a, **kw):
        raise NotImplementedError

    async def call_with_history(self, messages, **kwargs):
        self.calls.append(messages)
        if not self._responses:
            raise AssertionError("FakeLLM ran out of scripted responses")
        return self._responses.pop(0)


# -------- frontmatter parser --------

def test_parse_frontmatter_ok():
    from easyagent.skill import parse_frontmatter

    text = "---\nname: x\ndescription: y\n---\nBody text"
    meta, body = parse_frontmatter(text)
    assert meta == {"name": "x", "description": "y"}
    assert body.strip() == "Body text"


def test_parse_frontmatter_missing_returns_empty():
    from easyagent.skill import parse_frontmatter

    text = "# No frontmatter here\n\nJust body."
    meta, body = parse_frontmatter(text)
    assert meta == {}
    assert body == text


def test_parse_frontmatter_invalid_yaml_raises():
    from easyagent.skill import SkillValidationError, parse_frontmatter

    text = "---\nname: [unclosed\n---\nbody"
    with pytest.raises(SkillValidationError):
        parse_frontmatter(text)


# -------- loader --------

def test_load_skill_from_dir_lazy_body(tmp_path):
    from easyagent.skill import load_skill_from_dir

    d = _write_skill(tmp_path, "my-skill", body="Full body here.", tools=["bash"])
    skill = load_skill_from_dir(d)

    assert skill.name == "my-skill"
    assert skill.tools == ("bash",)
    assert skill._body is None  # lazy
    assert "Full body here." in skill.body()
    assert skill._body is not None  # cached


def test_load_skill_rejects_missing_name(tmp_path):
    from easyagent.skill import SkillValidationError, load_skill_from_dir

    d = tmp_path / "bad"
    d.mkdir()
    (d / "SKILL.md").write_text("---\ndescription: no name\n---\nbody", encoding="utf-8")
    with pytest.raises(SkillValidationError):
        load_skill_from_dir(d)


def test_load_skill_rejects_invalid_name(tmp_path):
    from easyagent.skill import SkillValidationError, load_skill_from_dir

    d = tmp_path / "bad"
    d.mkdir()
    (d / "SKILL.md").write_text(
        "---\nname: Has Spaces\ndescription: x\n---\n", encoding="utf-8"
    )
    with pytest.raises(SkillValidationError):
        load_skill_from_dir(d)


def test_load_skill_accepts_tools_alias(tmp_path):
    """Both `allowed-tools` and `tools` keys should work."""
    from easyagent.skill import load_skill_from_dir

    d = tmp_path / "alias"
    d.mkdir()
    (d / "SKILL.md").write_text(
        "---\nname: alias\ndescription: x\ntools:\n  - bash\n---\n",
        encoding="utf-8",
    )
    skill = load_skill_from_dir(d)
    assert skill.tools == ("bash",)


# -------- manager --------

def test_manager_discovery_and_idempotent(tmp_path):
    from easyagent.skill import SkillManager

    _write_skill(tmp_path, "alpha")
    _write_skill(tmp_path, "beta")

    mgr = SkillManager()
    mgr.add_search_dir(tmp_path)
    summaries = mgr.list_summaries()
    names = sorted(s["name"] for s in summaries)
    assert names == ["alpha", "beta"]

    # Second call must be a no-op, not re-register
    count_before = len(mgr._skills)
    mgr.discover()
    assert len(mgr._skills) == count_before


def test_manager_unknown_skill_filtered(tmp_path):
    from easyagent.skill import SkillManager

    _write_skill(tmp_path, "alpha")
    mgr = SkillManager()
    mgr.add_search_dir(tmp_path)
    summaries = mgr.list_summaries(["alpha", "nonexistent"])
    assert [s["name"] for s in summaries] == ["alpha"]


def test_manager_skips_invalid_skill_dir(tmp_path, caplog):
    from easyagent.skill import SkillManager

    _write_skill(tmp_path, "good")
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "SKILL.md").write_text("---\ndescription: no name\n---\n", encoding="utf-8")

    mgr = SkillManager()
    mgr.add_search_dir(tmp_path)
    summaries = mgr.list_summaries()
    assert [s["name"] for s in summaries] == ["good"]


# -------- ReactAgent construction --------

def test_react_agent_no_skills_keeps_prompt_unchanged(tmp_path):
    from easyagent import ReactAgent

    agent = ReactAgent(model=FakeLLM([]))
    session = agent.create_session()
    assert "Available Skills" not in agent.build_system_prompt(session)
    tool_names = [schema["function"]["name"] for schema in agent.get_tool_schemas(session)]
    assert "load_skill" not in tool_names


def test_react_agent_injects_skills_section(tmp_path):
    from easyagent import ReactAgent

    _write_skill(tmp_path, "demo", tools=["get_weather"])
    agent = ReactAgent(model=FakeLLM([]), skills=["demo"], skill_dir=tmp_path)
    session = agent.create_session()

    system_prompt = agent.build_system_prompt(session)
    assert "## Available Skills" in system_prompt
    assert "demo" in system_prompt
    tool_names = [schema["function"]["name"] for schema in agent.get_tool_schemas(session)]
    assert "load_skill" in tool_names


def test_react_agent_unknown_skill_does_not_raise(tmp_path, caplog):
    from easyagent import ReactAgent

    agent = ReactAgent(
        model=FakeLLM([]), skills=["nope"], skill_dir=tmp_path
    )
    session = agent.create_session()
    # No skills found → no section, no load_skill tool
    assert "Available Skills" not in agent.build_system_prompt(session)
    tool_names = [schema["function"]["name"] for schema in agent.get_tool_schemas(session)]
    assert "load_skill" in tool_names


# -------- Full loop: load_skill activates declared tools --------

@pytest.mark.asyncio
async def test_load_skill_activates_declared_tools(tmp_path):
    """End-to-end: LLM calls load_skill, then produces a final answer.

    Verifies the skill's declared tool gets appended to session.enabled_tools.
    """
    from easyagent import ReactAgent
    from easyagent.prompt.react import REACT_END_TOKEN
    from easyagent.tool import register_tool

    # A tool the skill will reference (register once; idempotent on re-runs).
    @register_tool
    class DummyEcho:
        name = "dummy_echo"
        type = "function"
        description = "Echo back."
        parameters = {
            "type": "object",
            "properties": {"msg": {"type": "string"}},
            "required": ["msg"],
        }
        def init(self): pass
        def execute(self, msg: str) -> str: return f"echoed: {msg}"

    _write_skill(tmp_path, "demo", body="Use dummy_echo.", tools=["dummy_echo"])

    # Scripted LLM: first turn calls load_skill, second returns final answer.
    first = LLMResponse(
        content="Loading skill.",
        tool_calls=[ToolCall(
            id="call_1", type="function", name="load_skill",
            arguments={"name": "demo"},
        )],
    )
    final = LLMResponse(content=f"All done. {REACT_END_TOKEN}")

    agent = ReactAgent(
        model=FakeLLM([first, final]),
        skills=["demo"],
        skill_dir=tmp_path,
        max_iterations=5,
    )
    session = agent.create_session()
    assert "dummy_echo" not in session.enabled_tools  # not active yet

    result = await agent.run("test", session=session)
    assert "All done." in result
    assert "dummy_echo" in session.enabled_tools  # activated by load_skill


@pytest.mark.asyncio
async def test_load_skill_unknown_tool_graceful(tmp_path):
    """Skill declares a non-existent tool; load_skill must report it, not crash."""
    from easyagent import ReactAgent
    from easyagent.prompt.react import REACT_END_TOKEN

    _write_skill(tmp_path, "demo", tools=["this_tool_does_not_exist"])

    first = LLMResponse(
        content="Loading.",
        tool_calls=[ToolCall(
            id="c1", type="function", name="load_skill",
            arguments={"name": "demo"},
        )],
    )
    final = LLMResponse(content=f"done {REACT_END_TOKEN}")

    agent = ReactAgent(
        model=FakeLLM([first, final]),
        skills=["demo"],
        skill_dir=tmp_path,
    )
    session = agent.create_session()
    result = await agent.run("x", session=session)
    assert "done" in result
    # Check that the tool result (in history) contains the warning text
    tool_msgs = [m for m in session.get_all_messages() if m.role == "tool"]
    assert any("Warning" in m.text() for m in tool_msgs)
