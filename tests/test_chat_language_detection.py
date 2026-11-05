# -*- coding: utf-8 -*-
from handlers.chat_handler import _resolve_conversation_lang


def test_english_question_overrides_korean_ui_language():
    assert _resolve_conversation_lang("What is GFC?", [], "ko") == "en"


def test_acronym_only_input_uses_client_language():
    assert _resolve_conversation_lang("GFC", [], "ko") == "ko"


def test_vietnamese_question_is_detected_even_with_an_acronym():
    assert _resolve_conversation_lang("gfc là gì?", [], "ko") == "vi"


def test_korean_question_overrides_vietnamese_ui_language():
    assert _resolve_conversation_lang("GFC가 뭐야?", [], "vi") == "ko"
