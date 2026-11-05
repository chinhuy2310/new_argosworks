# -*- coding: utf-8 -*-
import json
import unittest

from services.chat_agent import select_agent_tools


def _names(intent):
    return {
        tool["function"]["name"]
        for tool in select_agent_tools(intent)
    }


class TestChatAgentToolRouting(unittest.TestCase):
    def test_general_questions_do_not_receive_enterprise_tools(self):
        self.assertEqual(_names({"type": "general_question"}), set())

    def test_acronym_lookup_gets_broad_read_only_search(self):
        names = _names({"type": "knowledge_search", "domain": "knowledge"})
        self.assertIn("search_documents", names)
        self.assertIn("search_internal_records", names)
        self.assertNotIn("get_calendar_schedule", names)
        self.assertNotIn("generate_work_report", names)

    def test_task_query_gets_only_task_tools(self):
        names = _names({"type": "enterprise_search", "domain": "tasks"})
        self.assertIn("search_issues", names)
        self.assertIn("get_issue_details", names)
        self.assertNotIn("get_active_tasks", names)
        self.assertNotIn("search_products", names)
        self.assertNotIn("get_calendar_schedule", names)


    def test_active_task_tool_is_only_selected_for_active_task_list(self):
        task_search = _names({
            "type": "enterprise_search",
            "domain": "tasks",
            "include_active_tasks": False,
        })
        active_tasks = _names({
            "type": "enterprise_search",
            "domain": "tasks",
            "include_active_tasks": True,
        })
        self.assertNotIn("get_active_tasks", task_search)
        self.assertIn("get_active_tasks", active_tasks)

    def test_product_query_gets_product_tools(self):
        names = _names({"type": "enterprise_search", "domain": "products"})
        self.assertIn("search_products", names)
        self.assertIn("get_product_details", names)
        self.assertNotIn("search_issues", names)

    def test_cross_domain_analysis_unions_required_tools(self):
        names = _names({"type": "analysis", "domains": ["tasks", "products"]})
        self.assertIn("search_issues", names)
        self.assertIn("search_products", names)

    def test_missing_intent_preserves_legacy_tool_behavior(self):
        self.assertEqual(
            _names(None),
            {tool["function"]["name"] for tool in select_agent_tools(None)},
        )


    def test_agent_turn_limit_tracks_request_complexity(self):
        from services.chat_agent import resolve_agent_max_turns

        self.assertEqual(resolve_agent_max_turns({"type": "general_question"}, 4), 1)
        self.assertEqual(resolve_agent_max_turns({"type": "knowledge_search"}, 4), 2)
        self.assertEqual(resolve_agent_max_turns({"type": "enterprise_search"}, 4), 3)
        self.assertEqual(resolve_agent_max_turns({"type": "analysis"}, 4), 4)
        self.assertEqual(resolve_agent_max_turns({"type": "business_action"}, 2), 2)
        self.assertEqual(resolve_agent_max_turns(None, 4), 4)


    def test_byok_uses_exported_provider_defaults_without_mutating_server_config(self):
        from unittest.mock import patch
        from services.chat_agent import run_agent_conversation
        from services.ai_client import PROVIDER_CONFIGS

        cfg = {
            "ai": {
                "enabled": True,
                "provider": "openai",
                "model": "server-model",
                "api_key": "server-key",
            }
        }
        response = {
            "choices": [{"message": {"role": "assistant", "content": "ok"}}]
        }
        with patch(
            "services.chat_agent.call_ai_chat_completions",
            return_value=response,
        ) as call_mock:
            result = run_agent_conversation(
                messages=[{"role": "system", "content": "test"}],
                current_user={"name": "Alice"},
                cfg=cfg,
                intent={"type": "general_question"},
                custom_ai_config={
                    "provider": "gemini",
                    "model": "personal-model",
                    "apiKey": "personal-key",
                    "base_url": "https://attacker.invalid/v1",
                },
            )

        self.assertEqual(result, "ok")
        effective_cfg = call_mock.call_args.kwargs["cfg"]
        self.assertEqual(effective_cfg["ai"]["provider"], "gemini")
        self.assertEqual(effective_cfg["ai"]["model"], "personal-model")
        self.assertEqual(effective_cfg["ai"]["api_key"], "personal-key")
        self.assertEqual(effective_cfg["ai"]["base_url"], PROVIDER_CONFIGS["gemini"]["base_url"])
        self.assertEqual(cfg["ai"]["provider"], "openai")
        self.assertEqual(cfg["ai"]["api_key"], "server-key")


    def test_knowledge_search_uses_cautious_no_internal_evidence_instruction(self):
        from unittest.mock import patch
        from services.chat_agent import run_agent_conversation
        from prompts import POST_TOOL_NOTE_KNOWLEDGE

        tool_response = {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "call_gfc_search",
                        "type": "function",
                        "function": {
                            "name": "search_documents",
                            "arguments": json.dumps({"query": "GFC"}),
                        },
                    }],
                }
            }]
        }
        final_response = {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "No internal definition was found for GFC.",
                }
            }]
        }
        with patch(
            "services.chat_agent.call_ai_chat_completions",
            side_effect=[tool_response, final_response],
        ) as ai_mock, patch(
            "services.chat_agent.execute_tool",
            return_value={"found_count": 0, "documents": []},
        ):
            answer = run_agent_conversation(
                messages=[
                    {"role": "system", "content": "Answer carefully."},
                    {"role": "user", "content": "GFC là gì?"},
                ],
                current_user={"name": "Alice", "org": "dev"},
                cfg={"ai": {"enabled": True}},
                lang="vi",
                intent={
                    "type": "knowledge_search",
                    "domains": ["knowledge"],
                    "requires_action": False,
                },
            )

        self.assertIn("GFC", answer)
        second_messages = ai_mock.call_args_list[1].kwargs["messages"]
        self.assertIn(
            POST_TOOL_NOTE_KNOWLEDGE["vi"],
            [message.get("content") for message in second_messages],
        )


if __name__ == "__main__":
    unittest.main()
