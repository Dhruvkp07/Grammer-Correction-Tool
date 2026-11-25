import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

from writing_assistant.core import (
    DEFAULT_MODEL, MAX_SOURCE, TONES, GeminiError, Spelling, parse_gemini_response,
    parse_shortcut, request_rewrites, trailing_word,
)


def reply(values):
    return {
        "candidates": [{
            "finishReason": "STOP",
            "content": {"parts": [
                {"thought": True, "text": "internal"},
                {"text": json.dumps(values)},
            ]},
        }],
    }


class ShortcutTests(unittest.TestCase):
    def test_normalizes_order_and_key(self):
        shortcut = parse_shortcut(" alt + shift + ctrl + g ")
        self.assertEqual((shortcut.label, shortcut.modifiers, shortcut.key), ("Ctrl+Alt+Shift+G", 7, 71))
        self.assertEqual(parse_shortcut("Win+F12").key, 0x7B)

    def test_rejects_invalid_shortcuts(self):
        for text in ("", "A", "Shift+A", "Ctrl+Ctrl+A", "Alt+é", "Windows+A", "Ctrl+F13"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_shortcut(text)


class SpellTests(unittest.TestCase):
    def test_extracts_word_at_caret(self):
        self.assertEqual(trailing_word("I typed teh ", ""), ("teh", " "))
        self.assertEqual(trailing_word("My autom", "."), ("autom", ""))

    def test_avoids_partial_words_and_identifiers(self):
        for left, right in (
            ("auto", "matic"), ("api_key", ""), ("foo@example.com", ""), ("https://example", ""),
            ("camelCase", ""), ("NASA", ""), ("alpha  ", ""), ("caf", "é"),
        ):
            with self.subTest(left=left, right=right):
                self.assertIsNone(trailing_word(left, right))

    def test_checks_local_dictionary_and_completions(self):
        class Dictionary:
            word_frequency = SimpleNamespace(dictionary={"automatic": 10000, "writing": 9000})

            def __contains__(self, item):
                return item in self.word_frequency.dictionary

            def correction(self, word):
                return {"writng": "writing"}.get(word)

        spelling = Spelling(Dictionary())
        self.assertIsNone(spelling.suggest("writing", False))
        self.assertEqual(spelling.suggest("writng", True), "writing")
        self.assertEqual(spelling.suggest("autom", False), "automatic")
        self.assertIsNone(spelling.suggest("autom", True))


class GeminiTests(unittest.TestCase):
    def test_sends_only_source_and_editor_instruction(self):
        opener = Mock()
        opener.open.return_value = io.BytesIO(json.dumps(reply({"Polished": "I'll send it tomorrow."})).encode())
        source = "I send tomorrow.\n- Dhruv"
        result = request_rewrites(source, "example-key", DEFAULT_MODEL, opener=opener)
        self.assertEqual(result, [("Polished", "I'll send it tomorrow.")])
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url,
                         f"https://generativelanguage.googleapis.com/v1beta/models/{DEFAULT_MODEL}:generateContent")
        self.assertEqual(request.get_header("X-goog-api-key"), "example-key")
        self.assertNotIn("example-key", request.full_url)
        self.assertNotIn(b"example-key", request.data)
        self.assertEqual(json.loads(request.data)["contents"], [{"role": "user", "parts": [{"text": source}]}])

    def test_requests_and_returns_five_tones_in_display_order(self):
        opener = Mock()
        values = {tone: f"{tone} result" for tone in reversed(TONES)}
        opener.open.return_value = io.BytesIO(json.dumps(reply(values)).encode())
        result = request_rewrites("Write back soon.", "example-key", DEFAULT_MODEL, True, opener)
        self.assertEqual([tone for tone, _ in result], list(TONES))
        request = opener.open.call_args.args[0]
        self.assertEqual(json.loads(request.data)["generationConfig"]["responseSchema"]["required"], list(TONES))

    def test_validates_before_network(self):
        for source, key, model in (("", "x", DEFAULT_MODEL), ("x" * (MAX_SOURCE + 1), "x", DEFAULT_MODEL),
                                   ("source", "", DEFAULT_MODEL), ("source", "x", "../invalid")):
            with self.subTest(model=model, size=len(source)):
                opener = Mock()
                with self.assertRaises(GeminiError):
                    request_rewrites(source, key, model, opener=opener)
                opener.open.assert_not_called()

    def test_friendly_errors_exclude_request_and_server_body(self):
        opener = Mock()
        opener.open.side_effect = HTTPError("https://example.test", 429, "private", {}, None)
        with self.assertRaisesRegex(GeminiError, "quota"):
            request_rewrites("private source", "example-key", DEFAULT_MODEL, opener=opener)
        opener.open.side_effect = URLError("private transport details")
        with self.assertRaisesRegex(GeminiError, "internet connection"):
            request_rewrites("private source", "example-key", DEFAULT_MODEL, opener=opener)

    def test_rejects_truncation_missing_tone_and_malformed_responses(self):
        truncated = reply({"Polished": "truncated"})
        truncated["candidates"][0]["finishReason"] = "MAX_TOKENS"
        for response, tones in ((truncated, ("Polished",)), (reply({}), TONES),
                                ({}, ("Polished",)), (reply({"Polished": "\0"}), ("Polished",))):
            with self.subTest(response=response), self.assertRaises(GeminiError):
                parse_gemini_response(response, tones)
