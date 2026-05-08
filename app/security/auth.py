class AllowlistAuthService:
    def __init__(self, allowed_chat_ids: set[int], allowed_user_ids: set[int] | None = None) -> None:
        self._allowed_chat_ids = allowed_chat_ids
        self._allowed_user_ids = allowed_user_ids or set()

    @property
    def allowed_chat_ids(self) -> frozenset[int]:
        return frozenset(self._allowed_chat_ids)

    @property
    def allowed_user_ids(self) -> frozenset[int]:
        return frozenset(self._allowed_user_ids)

    def is_allowed(self, chat_id: int, user_id: int | None = None) -> bool:
        if chat_id in self._allowed_chat_ids:
            return True
        if user_id is not None and user_id in self._allowed_user_ids:
            return True
        return False
