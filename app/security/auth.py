class AllowlistAuthService:
    def __init__(self, allowed_chat_ids: set[int]) -> None:
        self._allowed_chat_ids = allowed_chat_ids

    def is_allowed(self, chat_id: int, user_id: int | None = None) -> bool:
        _ = user_id
        return chat_id in self._allowed_chat_ids
