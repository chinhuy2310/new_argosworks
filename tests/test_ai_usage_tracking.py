# -*- coding: utf-8 -*-
import unittest

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
