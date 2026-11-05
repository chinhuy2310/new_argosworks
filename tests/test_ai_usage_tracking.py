# -*- coding: utf-8 -*-
import unittest
from unittest.mock import patch

from services.ai_client import normalize_token_usage


class TestNormalizeProviderTokenUsage(unittest.TestCase):
    def test_openai_compatible_usage(self):
        self.assertEqual(
            normalize_token_usage({
                "prompt_tokens": 120,
                "completion_tokens": 30,
                "total_tokens": 150,
            }),
            {
                "prompt_tokens": 120,
                "completion_tokens": 30,
                "total_tokens": 150,
            },
        )

    def test_anthropic_usage(self):
        self.assertEqual(
            normalize_token_usage({"input_tokens": 90, "output_tokens": 25}),
            {
                "prompt_tokens": 90,
                "completion_tokens": 25,
                "total_tokens": 115,
            },
        )

    def test_gemini_usage_metadata(self):
        self.assertEqual(
            normalize_token_usage({
                "promptTokenCount": 40,
                "candidatesTokenCount": 10,
                "totalTokenCount": 50,
            }),
            {
                "prompt_tokens": 40,
                "completion_tokens": 10,
                "total_tokens": 50,
            },
        )

    def test_missing_usage_is_not_fabricated(self):
        self.assertIsNone(normalize_token_usage(None))
        self.assertIsNone(normalize_token_usage({}))


    def test_chat_completion_records_actual_usage_with_user_session(self):
        from services import ai_client

        class DummySemaphore:
            def acquire(self, timeout=None):
                return True

            def release(self):
                return None

        recorded = []
        primary = {
            "enabled": True,
            "provider": "openai",
            "model": "gpt-test",
            "api_key": "test-key",
        }
        response = {
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "usage": {
                "prompt_tokens": 11,
                "completion_tokens": 7,
                "total_tokens": 18,
            },
        }
        with patch.object(ai_client, "_AI_CONCURRENCY_SEMAPHORE", DummySemaphore()), \
                patch.object(ai_client, "get_ai_config", return_value=primary), \
                patch.object(ai_client, "get_ai_fallback_config", return_value={"enabled": False}), \
                patch.object(ai_client, "get_provider_api_keys", return_value=["test-key"]), \
                patch.object(
                    ai_client,
                    "_execute_ai_chat_completion_single",
                    return_value=(response, None, ""),
                ), \
                patch(
                    "services.ai_usage_service.record_ai_usage",
                    side_effect=lambda **kwargs: recorded.append(kwargs),
                ):
            result = ai_client.call_ai_chat_completions(
                cfg={},
                messages=[],
                usage_context={
                    "user_name": "alice",
                    "dept_id": "dev",
                    "session_id": "session-123",
                    "feature": "chat",
                },
            )

        self.assertIs(result, response)
        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0]["user_name"], "alice")
        self.assertEqual(recorded[0]["dept_id"], "dev")
        self.assertEqual(recorded[0]["session_id"], "session-123")
        self.assertEqual(recorded[0]["prompt_tokens"], 11)
        self.assertEqual(recorded[0]["completion_tokens"], 7)
        self.assertEqual(recorded[0]["total_tokens"], 18)
        self.assertEqual(recorded[0]["feature"], "chat_actual")

    def test_usage_stats_excludes_legacy_character_estimates(self):
        from services.ai_usage_service import get_ai_usage_stats

        with patch("services.ai_usage_service.query", return_value=[]) as query_mock:
            result = get_ai_usage_stats(period="all")

        self.assertEqual(result["summary"]["total_tokens"], 0)
        self.assertEqual(query_mock.call_count, 5)
        for call in query_mock.call_args_list:
            self.assertIn("feature <> ?", call.args[0])
            self.assertIn("chat", call.args[1])


    def test_invalid_values_are_safely_normalized(self):
        self.assertEqual(
            normalize_token_usage({
                "prompt_tokens": "bad",
                "completion_tokens": 3,
            }),
            {
                "prompt_tokens": 0,
                "completion_tokens": 3,
                "total_tokens": 3,
            },
        )


if __name__ == "__main__":
    unittest.main()
