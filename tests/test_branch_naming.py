from app.git.branch_naming import TimestampSlugStrategy


def test_branch_naming_strategy_format():
    strategy = TimestampSlugStrategy()
    name = strategy.make_branch_name("Fix login validation!!")
    assert name.startswith("remote-fix-login-validation-")


def test_branch_naming_strategy_uses_ascii_fallback_for_non_ascii_instruction():
    strategy = TimestampSlugStrategy()
    name = strategy.make_branch_name("로그인 검증 수정")
    assert name.startswith("remote-task-")
