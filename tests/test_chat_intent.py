# -*- coding: utf-8 -*-
import unittest

from services.chat_intent import classify_chat_intent


class TestChatIntentActionGuard(unittest.TestCase):
    def test_acronym_is_never_a_business_action(self):
        for message in ("gfc", "gfc là gì?", "What is GFC?", "GFC가 뭐야?"):
            with self.subTest(message=message):
                intent = classify_chat_intent(message)
                self.assertFalse(intent["requires_action"])
                self.assertNotEqual(intent["type"], "business_action")

    def test_explicit_vietnamese_task_creation(self):
        intent = classify_chat_intent("Tạo Task kiểm tra hệ thống GFC")
        self.assertTrue(intent["requires_action"])
        self.assertEqual(intent["domain"], "tasks")

    def test_explicit_korean_task_creation(self):
        intent = classify_chat_intent("GFC 점검 업무를 새로 등록해줘")
        self.assertTrue(intent["requires_action"])

    def test_how_to_question_is_not_an_action(self):
        for message in ("Cách tạo Task là gì?", "How to create a task?", "업무 등록은 어떻게 하나요?"):
            with self.subTest(message=message):
                self.assertFalse(classify_chat_intent(message)["requires_action"])

    def test_negated_request_is_not_an_action(self):
        self.assertFalse(
            classify_chat_intent("Đừng tạo Task GFC")["requires_action"]
        )

    def test_followup_selects_create_option_only_from_quick_actions(self):
        history = [{
            "role": "assistant",
            "content": (
                "Bạn muốn xử lý thế nào?\n:::quick-actions\n"
                "- Thêm bình luận vào thẻ hiện tại\n"
                "- Tạo mới thành một Task riêng\n:::" 
            ),
        }]
        intent = classify_chat_intent("Tạo mới", history)
        self.assertTrue(intent["requires_action"])

    def test_short_reply_without_action_menu_is_not_an_action(self):
        self.assertFalse(classify_chat_intent("Tạo mới")["requires_action"])


if __name__ == "__main__":
    unittest.main()
