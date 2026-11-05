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


    def test_action_proposal_metadata_requires_explicit_intent_gate(self):
        from handlers.chat_handler import _parse_metadata

        answer = (
            "Please review this.\n:::action-proposal\n"
            "action_type: create_task\nsummary: GFC review\n:::"
        )
        self.assertIsNone(_parse_metadata(answer)["action_proposal"])
        self.assertEqual(
            _parse_metadata(answer, allow_action_proposal=True)["action_proposal"]["action_type"],
            "create_task",
        )

    def test_unknown_action_type_is_not_exposed(self):
        from handlers.chat_handler import _parse_metadata

        answer = (
            "Please review this.\n:::action-proposal\n"
            "action_type: run_shell\nsummary: unsafe\n:::"
        )
        self.assertIsNone(
            _parse_metadata(answer, allow_action_proposal=True)["action_proposal"]
        )



    def test_short_ordinary_words_do_not_trigger_acronym_lookup(self):
        intent = classify_chat_intent("Show my active tasks")
        self.assertEqual(intent["type"], "enterprise_search")
        self.assertEqual(intent["domain"], "tasks")

    def test_gfc_acronym_remains_a_knowledge_lookup(self):
        for message in ("gfc", "gfc là gì?", "What is GFC?", "GFC가 뭐야?"):
            with self.subTest(message=message):
                self.assertEqual(
                    classify_chat_intent(message)["type"], "knowledge_search"
                )

    def test_active_task_query_is_flagged_for_specific_tool(self):
        from services.chat_intent import should_include_active_tasks

        self.assertTrue(should_include_active_tasks("Show my active tasks"))
        self.assertTrue(should_include_active_tasks("내 진행 중 업무"))
        self.assertTrue(should_include_active_tasks("Danh sách công việc của tôi"))
        self.assertFalse(should_include_active_tasks("Tìm Task GFC"))

    def test_short_reply_without_action_menu_is_not_an_action(self):
        self.assertFalse(classify_chat_intent("Tạo mới")["requires_action"])


    def test_negation_only_blocks_the_action_it_modifies(self):
        positive_requests = (
            "Tạo Task GFC, không cần gấp",
            "Create a task for GFC, not urgent",
            "GFC 업무 새로 등록해줘. 급하지 않아",
        )
        for message in positive_requests:
            with self.subTest(message=message):
                self.assertTrue(classify_chat_intent(message)["requires_action"])

        negative_requests = (
            "Không tạo Task GFC",
            "Tôi không muốn tạo Task GFC",
            "Don't create a task for GFC",
            "GFC 업무 등록하지 마",
            "GFC 업무 만들지 말아줘",
        )
        for message in negative_requests:
            with self.subTest(message=message):
                self.assertFalse(classify_chat_intent(message)["requires_action"])

    def test_english_natural_language_create_request_is_recognized(self):
        intent = classify_chat_intent("I want you to create a task about GFC")
        self.assertTrue(intent["requires_action"])
        self.assertEqual(intent["domain"], "tasks")


if __name__ == "__main__":
    unittest.main()
