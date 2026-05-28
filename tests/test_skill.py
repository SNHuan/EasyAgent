"""Tests for easyagent.skill — loader, manager, SkillAgent integration."""

from pathlib import Path

import pytest

from easyagent.model.schema import LLMResponse, ToolCall


# -------- fixtures --------

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


def _write_skill_file(skill_dir: Path, relative_path: str, content: str) -> None:
    target = skill_dir / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


class FakeLLM:
    """Scripted responses for agent integration tests."""

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


def test_skill_package_lists_and_reads_files(tmp_path):
    from easyagent.skill import load_skill_from_dir

    d = _write_skill(tmp_path, "my-skill", body="Body here.")
    _write_skill_file(d, "references/guide.md", "Guide text.")
    _write_skill_file(d, "scripts/helper.py", "print('ok')")

    skill = load_skill_from_dir(d)

    assert skill.list_files() == ["references/guide.md", "scripts/helper.py"]
    assert skill.read_file("references/guide.md") == "Guide text."


def test_skill_package_rejects_path_escape(tmp_path):
    from easyagent.skill import load_skill_from_dir

    d = _write_skill(tmp_path, "my-skill")
    skill = load_skill_from_dir(d)

    with pytest.raises(ValueError):
        skill.resolve_file("../outside.txt")


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


def test_load_skill_rejects_name_that_does_not_match_directory(tmp_path):
    from easyagent.skill import SkillValidationError, load_skill_from_dir

    d = tmp_path / "skill-dir"
    d.mkdir()
    (d / "SKILL.md").write_text(
        "---\nname: other-name\ndescription: x\n---\n",
        encoding="utf-8",
    )
    with pytest.raises(SkillValidationError, match="must match parent directory"):
        load_skill_from_dir(d)


def test_load_skill_rejects_too_long_name(tmp_path):
    from easyagent.skill import SkillValidationError, load_skill_from_dir

    name = "a" * 65
    d = tmp_path / name
    d.mkdir()
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: x\n---\n",
        encoding="utf-8",
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


def test_manager_uses_easyagent_skills_default_dir(tmp_path, monkeypatch):
    from easyagent.skill import SkillManager

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("EA_SKILLS_DIR", raising=False)
    _write_skill(tmp_path / ".easyagent" / "skills", "alpha")

    mgr = SkillManager()
    summaries = mgr.list_summaries()

    assert [s["name"] for s in summaries] == ["alpha"]


def test_manager_uses_env_skill_dirs(tmp_path, monkeypatch):
    from easyagent.skill import SkillManager

    default_root = tmp_path / ".easyagent" / "skills"
    claude_root = tmp_path / ".claude" / "skills"
    codex_root = tmp_path / ".codex" / "skills"
    _write_skill(default_root, "default-skill")
    _write_skill(claude_root, "claude-skill")
    _write_skill(codex_root, "codex-skill")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EA_SKILLS_DIR", f"{claude_root}{__import__('os').pathsep}{codex_root}")

    mgr = SkillManager()
    summaries = mgr.list_summaries()

    assert sorted(s["name"] for s in summaries) == ["claude-skill", "codex-skill"]


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


# -------- ReactAgent / SkillAgent construction --------

def test_tool_agent_no_skills_keeps_prompt_unchanged():
    from easyagent import ReactAgent

    agent = ReactAgent(model=FakeLLM([]))
    session = agent.create_session()
    assert "Available Skills" not in agent.build_system_prompt(session)
    tool_names = [schema["function"]["name"] for schema in agent.get_tool_schemas(session)]
    assert "load_skill" not in tool_names


def test_skill_agent_injects_skills_section(tmp_path):
    from easyagent import SkillAgent
    from easyagent.skill import SkillManager

    _write_skill(tmp_path, "demo", tools=["get_weather"])
    skill_manager = SkillManager(include_default_dirs=False)

    agent = SkillAgent(
        model=FakeLLM([]),
        skills=["demo"],
        skill_root=tmp_path,
        skill_manager=skill_manager,
    )
    session = agent.create_session()

    system_prompt = agent.build_system_prompt(session)
    assert "## Available Skills" in system_prompt
    assert "demo" in system_prompt
    tool_names = [schema["function"]["name"] for schema in agent.get_tool_schemas(session)]
    assert "load_skill" in tool_names


def test_skill_agent_unknown_skill_does_not_raise(tmp_path, caplog):
    from easyagent import SkillAgent
    from easyagent.skill import SkillManager

    skill_manager = SkillManager(include_default_dirs=False)
    agent = SkillAgent(
        model=FakeLLM([]),
        skills=["nope"],
        skill_root=tmp_path,
        skill_manager=skill_manager,
    )
    session = agent.create_session()
    # No skills found → no section, but load_skill tool is still registered
    assert "Available Skills" not in agent.build_system_prompt(session)
    tool_names = [schema["function"]["name"] for schema in agent.get_tool_schemas(session)]
    assert "load_skill" in tool_names


# -------- Full loop: load_skill activates declared tools --------

@pytest.mark.asyncio
async def test_load_skill_activates_declared_tools(tmp_path):
    """End-to-end: LLM calls load_skill, then produces a final answer.

    Verifies the skill's declared tool gets appended to session.enabled_tools.
    """
    from easyagent import SkillAgent
    from easyagent.skill import SkillManager

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
        def execute(self, msg: str, **kwargs) -> str: return f"echoed: {msg}"

    skill_manager = SkillManager(include_default_dirs=False)

    _write_skill(tmp_path, "demo", body="Use dummy_echo.", tools=["dummy_echo"])

    first = LLMResponse(
        content="Loading skill.",
        tool_calls=[ToolCall(
            id="call_1", type="function", name="load_skill",
            arguments={"name": "demo"},
        )],
    )
    final = LLMResponse(content="All done.")

    agent = SkillAgent(
        model=FakeLLM([first, final]),
        skills=["demo"],
        skill_root=tmp_path,
        skill_manager=skill_manager,
        max_iterations=5,
    )
    # Register tool but don't enable it — load_skill will activate it
    agent.add_tool(DummyEcho(), enabled=False)

    session = agent.create_session()
    assert "dummy_echo" not in session.enabled_tools  # not active yet

    result = await agent.run("test", session=session)
    assert "All done." in (result.final_output or "")
    assert "dummy_echo" in session.enabled_tools  # activated by load_skill


@pytest.mark.asyncio
async def test_load_skill_unknown_tool_graceful(tmp_path):
    """Skill declares a non-existent tool; load_skill must not crash."""
    from easyagent import SkillAgent
    from easyagent.skill import SkillManager

    _write_skill(tmp_path, "demo", tools=["this_tool_does_not_exist"])
    skill_manager = SkillManager(include_default_dirs=False)

    first = LLMResponse(
        content="Loading.",
        tool_calls=[ToolCall(
            id="c1", type="function", name="load_skill",
            arguments={"name": "demo"},
        )],
    )
    final = LLMResponse(content="done")

    agent = SkillAgent(
        model=FakeLLM([first, final]),
        skills=["demo"],
        skill_root=tmp_path,
        skill_manager=skill_manager,
    )
    session = agent.create_session()
    result = await agent.run("x", session=session)
    assert "done" in (result.final_output or "")
    assert "this_tool_does_not_exist" not in session.enabled_tools
    tool_msgs = [m for m in session.get_all_messages() if m.role == "tool"]
    assert any("Declared tools not registered: this_tool_does_not_exist" in m.text() for m in tool_msgs)


@pytest.mark.asyncio
async def test_load_skill_reports_packaged_files(tmp_path):
    from easyagent import SkillAgent
    from easyagent.skill import SkillManager

    skill_dir = _write_skill(tmp_path, "demo", body="Read references/guide.md.")
    _write_skill_file(skill_dir, "references/guide.md", "Guide text.")

    first = LLMResponse(
        content="Loading.",
        tool_calls=[ToolCall(
            id="c1", type="function", name="load_skill",
            arguments={"name": "demo"},
        )],
    )
    final = LLMResponse(content="done")

    agent = SkillAgent(
        model=FakeLLM([first, final]),
        skills=["demo"],
        skill_root=tmp_path,
        skill_manager=SkillManager(include_default_dirs=False),
    )
    session = agent.create_session()
    await agent.run("x", session=session)
    tool_msgs = [m for m in session.get_all_messages() if m.role == "tool"]
    assert any("references/guide.md" in m.text() for m in tool_msgs)


@pytest.mark.asyncio
async def test_skill_file_tools_require_loaded_skill(tmp_path):
    from easyagent import SkillAgent
    from easyagent.skill import SkillManager

    _write_skill(tmp_path, "demo")

    agent = SkillAgent(
        model=FakeLLM([]),
        skills=["demo"],
        skill_root=tmp_path,
        skill_manager=SkillManager(include_default_dirs=False),
    )
    session = agent.create_session()

    result = await agent.execute_tool_call(
        session,
        "list_skill_files",
        {"name": "demo"},
    )

    assert "Call load_skill first" in result


@pytest.mark.asyncio
async def test_skill_file_tools_read_and_run_scripts(tmp_path):
    from easyagent import SkillAgent
    from easyagent.skill import SkillManager

    skill_dir = _write_skill(tmp_path, "demo")
    _write_skill_file(skill_dir, "references/guide.md", "Guide text.")
    _write_skill_file(skill_dir, "scripts/echo.py", "import sys\nprint(sys.argv[1])\n")

    agent = SkillAgent(
        model=FakeLLM([]),
        skills=["demo"],
        skill_root=tmp_path,
        skill_manager=SkillManager(include_default_dirs=False),
    )
    session = agent.create_session()
    session.loaded_skills.append("demo")

    listed = await agent.execute_tool_call(session, "list_skill_files", {"name": "demo"})
    content = await agent.execute_tool_call(
        session,
        "read_skill_file",
        {"name": "demo", "path": "references/guide.md"},
    )
    script_result = await agent.execute_tool_call(
        session,
        "run_skill_script",
        {"name": "demo", "script": "echo.py", "args": ["hello"]},
    )

    assert "references/guide.md" in listed
    assert content == "Guide text."
    assert '"exit_code": 0' in script_result
    assert "hello" in script_result
