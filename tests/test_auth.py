from app.security.auth import AllowlistAuthService


def test_allowlist_auth_service():
    service = AllowlistAuthService({1, 2}, {9})
    assert service.allowed_chat_ids == frozenset({1, 2})
    assert service.allowed_user_ids == frozenset({9})
    assert service.is_allowed(1)
    assert service.is_allowed(chat_id=999, user_id=9)
    assert not service.is_allowed(3)
