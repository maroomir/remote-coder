from app.models import UiLanguage
from app.telegram.i18n import translate_text


def test_translate_text_leaves_isolated_common_korean_tokens():
    text = "예시로 메시지와 모드 토큰을 사용자 지시에 넣습니다"
    assert translate_text(text, UiLanguage.ENGLISH) == text


def test_translate_text_still_replaces_distinct_bot_phrases():
    raw = "작업 접수 완료\n브랜치 확인"
    out = translate_text(raw, UiLanguage.ENGLISH)
    assert "Job accepted" in out
    assert "Branch" in out
