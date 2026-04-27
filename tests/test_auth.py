from app.security.auth import AllowlistAuthService


def test_allowlist_auth_service():
    service = AllowlistAuthService({1, 2})
    assert service.is_allowed(1)
    assert not service.is_allowed(3)
