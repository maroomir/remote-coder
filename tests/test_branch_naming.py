from app.git.branch_naming import TimestampSlugStrategy


def test_branch_naming_strategy_format():
    strategy = TimestampSlugStrategy()
    name = strategy.make_branch_name("Fix login validation!!")
    assert name.startswith("remote-fix-login-validation-")
