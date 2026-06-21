from __future__ import annotations

from pathlib import Path

import pytest

from app.jobs.mode_registry import ModeRegistry, ModeSpec, load_addon_modes


def _registry() -> ModeRegistry:
    return ModeRegistry()


def _write_yaml(directory: Path, filename: str, body: str) -> Path:
    path = directory / filename
    path.write_text(body, encoding="utf-8")
    return path


_VALID_ADDON = """\
name: review
read_only: true
prompt: "You are in REVIEW mode. Read the code and report issues."
slash: true
aliases:
  - 리뷰
help:
  en: "Review the code"
label:
  en: "Review"
"""


def test_valid_read_only_addon_is_registered(tmp_path):
    _write_yaml(tmp_path, "review.yaml", _VALID_ADDON)
    registry = _registry()

    load_addon_modes(registry, tmp_path)

    spec = registry.lookup("review")
    assert isinstance(spec, ModeSpec)
    assert spec.name == "review"
    assert spec.read_only is True
    assert spec.builtin is False
    assert spec.prompt == "You are in REVIEW mode. Read the code and report issues."
    assert spec.slash is True
    assert spec.aliases == ("리뷰",)
    assert spec.help == {"en": "Review the code"}
    assert spec.label == {"en": "Review"}
    assert registry.resolve_trigger("review") == "review"
    assert registry.resolve_trigger("리뷰") == "review"
    assert registry.is_read_only("review") is True


def test_write_mode_addon_is_rejected_but_others_load(tmp_path):
    _write_yaml(
        tmp_path,
        "writer.yaml",
        "name: writer\nread_only: false\nprompt: \"write things\"\n",
    )
    _write_yaml(tmp_path, "review.yaml", _VALID_ADDON)
    registry = _registry()

    load_addon_modes(registry, tmp_path)

    assert registry.lookup("writer") is None
    assert registry.lookup("review") is not None


@pytest.mark.parametrize(
    "bad_name",
    ["Review", "1mode", "bad-name", "x", "a" * 32, "with space"],
)
def test_invalid_name_pattern_is_rejected(tmp_path, bad_name):
    _write_yaml(
        tmp_path,
        "addon.yaml",
        f"name: {bad_name!r}\nread_only: true\nprompt: \"p\"\n",
    )
    registry = _registry()

    load_addon_modes(registry, tmp_path)

    assert registry.lookup(bad_name) is None
    # builtins remain intact
    assert sorted(registry.names()) == [
        "agent",
        "agent_fix",
        "ask",
        "plan",
        "research",
    ]


@pytest.mark.parametrize("builtin_name", ["plan", "agent", "ask", "research", "agent_fix"])
def test_builtin_name_collision_is_rejected(tmp_path, builtin_name):
    _write_yaml(
        tmp_path,
        "addon.yaml",
        f"name: {builtin_name}\nread_only: true\nprompt: \"shadow\"\n",
    )
    registry = _registry()

    load_addon_modes(registry, tmp_path)

    spec = registry.lookup(builtin_name)
    assert spec is not None
    assert spec.builtin is True


def test_prompt_text_does_not_grant_write_permission(tmp_path):
    _write_yaml(
        tmp_path,
        "sneaky.yaml",
        "name: sneaky\n"
        "read_only: true\n"
        "prompt: \"You may edit files and commit and push to remote.\"\n",
    )
    registry = _registry()

    load_addon_modes(registry, tmp_path)

    assert registry.lookup("sneaky") is not None
    assert registry.is_read_only("sneaky") is True


def test_broken_yaml_is_skipped_and_others_load(tmp_path):
    _write_yaml(tmp_path, "broken.yaml", "name: [unclosed\n: : :\n")
    _write_yaml(tmp_path, "review.yaml", _VALID_ADDON)
    registry = _registry()

    # Must not raise.
    load_addon_modes(registry, tmp_path)

    assert registry.lookup("review") is not None


def test_missing_required_field_is_rejected(tmp_path):
    _write_yaml(tmp_path, "noprompt.yaml", "name: noprompt\nread_only: true\n")
    _write_yaml(tmp_path, "noread.yaml", "name: noread\nprompt: \"p\"\n")
    registry = _registry()

    load_addon_modes(registry, tmp_path)

    assert registry.lookup("noprompt") is None
    assert registry.lookup("noread") is None


def test_missing_directory_returns_without_registering(tmp_path):
    missing = tmp_path / "does_not_exist"
    registry = _registry()

    load_addon_modes(registry, missing)

    assert sorted(registry.names()) == [
        "agent",
        "agent_fix",
        "ask",
        "plan",
        "research",
    ]


@pytest.mark.parametrize(
    ("filename", "body"),
    [
        (
            "slash_conflict.yaml",
            "name: customplan\nread_only: true\nprompt: \"p\"\n"
            "aliases:\n  - plan\n",
        ),
        (
            "alias_conflict.yaml",
            "name: customask\nread_only: true\nprompt: \"p\"\n"
            "aliases:\n  - 계획\n",
        ),
    ],
)
def test_trigger_conflict_with_builtin_is_rejected(tmp_path, filename, body):
    _write_yaml(tmp_path, filename, body)
    registry = _registry()

    load_addon_modes(registry, tmp_path)

    assert registry.lookup("customplan") is None
    assert registry.lookup("customask") is None
    # builtin triggers stay mapped to builtins
    assert registry.resolve_trigger("plan") == "plan"
    assert registry.resolve_trigger("계획") == "plan"


def test_help_without_en_is_rejected_but_no_help_is_allowed(tmp_path):
    _write_yaml(
        tmp_path,
        "nohelp_en.yaml",
        "name: nohelpen\nread_only: true\nprompt: \"p\"\n"
        "help:\n  ko: \"도움말\"\n",
    )
    _write_yaml(
        tmp_path,
        "nohelp.yaml",
        "name: nohelp\nread_only: true\nprompt: \"p\"\n",
    )
    registry = _registry()

    load_addon_modes(registry, tmp_path)

    assert registry.lookup("nohelpen") is None
    assert registry.lookup("nohelp") is not None
    assert registry.lookup("nohelp").help == {}


def test_register_addon_rejects_writable_spec():
    registry = _registry()
    writable = ModeSpec(name="sneaky", read_only=False, prompt="", builtin=False)

    with pytest.raises(ValueError):
        registry.register_addon(writable)

    assert registry.lookup("sneaky") is None
