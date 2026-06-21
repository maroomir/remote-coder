from app.ai.base import instruction_for_runner_mode
from app.jobs.mode_registry import ModeRegistry, ModeSpec
from app.jobs.schemas import JobMode


def _registry() -> ModeRegistry:
    return ModeRegistry()


def test_seeds_exactly_five_builtins():
    registry = _registry()
    assert sorted(registry.names()) == sorted(mode.value for mode in JobMode)
    for name in registry.names():
        spec = registry.lookup(name)
        assert spec is not None
        assert spec.builtin is True


def test_lookup_returns_spec_for_each_builtin():
    registry = _registry()
    for mode in JobMode:
        spec = registry.lookup(mode.value)
        assert isinstance(spec, ModeSpec)
        assert spec.name == mode.value


def test_lookup_unknown_returns_none():
    assert _registry().lookup("frobnicate") is None


def test_resolve_trigger_slash_and_aliases():
    registry = _registry()
    assert registry.resolve_trigger("plan") == JobMode.PLAN.value
    assert registry.resolve_trigger("/PLAN") == JobMode.PLAN.value
    assert registry.resolve_trigger("계획") == JobMode.PLAN.value
    assert registry.resolve_trigger("질문") == JobMode.ASK.value
    assert registry.resolve_trigger("조사") == JobMode.RESEARCH.value
    assert registry.resolve_trigger("research") == JobMode.RESEARCH.value
    assert registry.resolve_trigger("ask") == JobMode.ASK.value
    assert registry.resolve_trigger("fix") == JobMode.AGENT_FIX.value
    assert registry.resolve_trigger("수정") == JobMode.AGENT_FIX.value


def test_resolve_trigger_unknown_and_agent_have_no_trigger():
    registry = _registry()
    assert registry.resolve_trigger("agent") is None
    assert registry.resolve_trigger("nope") is None


def test_is_read_only_flags():
    registry = _registry()
    assert registry.is_read_only(JobMode.PLAN.value) is True
    assert registry.is_read_only(JobMode.ASK.value) is True
    assert registry.is_read_only(JobMode.RESEARCH.value) is True
    assert registry.is_read_only(JobMode.AGENT.value) is False
    assert registry.is_read_only(JobMode.AGENT_FIX.value) is False
    assert registry.is_read_only("frobnicate") is False


def test_read_only_spec_flags():
    registry = _registry()
    assert registry.lookup(JobMode.PLAN.value).read_only is True
    assert registry.lookup(JobMode.ASK.value).read_only is True
    assert registry.lookup(JobMode.RESEARCH.value).read_only is True
    assert registry.lookup(JobMode.AGENT.value).read_only is False
    assert registry.lookup(JobMode.AGENT_FIX.value).read_only is False


def test_prompt_prefix_byte_identity_with_base():
    registry = _registry()
    sample = "do the thing"
    for mode in (JobMode.PLAN, JobMode.ASK, JobMode.RESEARCH):
        spec = registry.lookup(mode.value)
        assert spec.prompt + sample == instruction_for_runner_mode(sample, mode)
    for mode in (JobMode.AGENT, JobMode.AGENT_FIX):
        spec = registry.lookup(mode.value)
        assert spec.prompt == ""
        assert spec.prompt + sample == instruction_for_runner_mode(sample, mode)
