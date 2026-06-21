import pytest

from app.jobs.schemas import (
    JobMode,
    JobRequest,
    is_read_only_job_mode,
    job_mode_name,
)
from app.models import ModelName


def _request(mode):
    return JobRequest(
        project="p",
        model=ModelName.CLAUDE,
        instruction="x",
        mode=mode,
        chat_id=7,
    )


def test_enum_mode_is_preserved():
    request = _request(JobMode.PLAN)

    assert request.mode is JobMode.PLAN


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("agent", JobMode.AGENT),
        ("plan", JobMode.PLAN),
        ("ask", JobMode.ASK),
        ("research", JobMode.RESEARCH),
        ("agent_fix", JobMode.AGENT_FIX),
    ],
)
def test_builtin_string_mode_normalizes_to_enum(name, expected):
    request = _request(name)

    assert request.mode is expected


def test_addon_string_mode_is_kept_as_str():
    request = _request("review")

    assert request.mode == "review"
    assert type(request.mode) is str
    assert not isinstance(request.mode, JobMode)


def test_addon_mode_survives_json_roundtrip():
    payload = _request("review").model_dump_json()

    restored = JobRequest.model_validate_json(payload)

    assert restored.mode == "review"
    assert type(restored.mode) is str


def test_builtin_mode_survives_json_roundtrip():
    payload = _request(JobMode.AGENT_FIX).model_dump_json()

    restored = JobRequest.model_validate_json(payload)

    assert restored.mode is JobMode.AGENT_FIX


def test_default_mode_is_agent():
    request = JobRequest(
        project="p",
        model=ModelName.CLAUDE,
        instruction="x",
        chat_id=7,
    )

    assert request.mode is JobMode.AGENT


def test_job_mode_name_collapses_enum_and_str():
    assert job_mode_name(JobMode.PLAN) == "plan"
    assert job_mode_name("review") == "review"


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (JobMode.PLAN, True),
        (JobMode.ASK, True),
        (JobMode.RESEARCH, True),
        ("plan", True),
        ("ask", True),
        ("research", True),
        (JobMode.AGENT, False),
        (JobMode.AGENT_FIX, False),
        ("agent", False),
        ("agent_fix", False),
        ("review", False),
    ],
)
def test_is_read_only_job_mode_handles_enum_str_and_addon(mode, expected):
    assert is_read_only_job_mode(mode) is expected
