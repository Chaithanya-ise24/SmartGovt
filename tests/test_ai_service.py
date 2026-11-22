import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

from services.ai_service import AIResponseError, chat_reply, generate_quiz


class AIServiceTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            GEMINI_API_KEY="test-key",
            GEMINI_MODEL="test-model",
        )
        self.context = self.app.app_context()
        self.context.push()
        self.addCleanup(self.context.pop)

    @patch("services.ai_service.genai.Client")
    def test_chat_uses_config_model_history_and_requested_language(self, client_factory):
        client = client_factory.return_value
        client.models.generate_content.return_value = SimpleNamespace(text="ಉತ್ತರ")

        answer = chat_reply(
            "Explain simpler",
            history=[{"question": "What is gravity?", "answer": "It pulls things down."}],
            language="kn",
        )

        self.assertEqual(answer, "ಉತ್ತರ")
        call = client.models.generate_content.call_args.kwargs
        self.assertEqual(call["model"], "test-model")
        self.assertEqual(len(call["contents"]), 3)
        self.assertIn("simple Kannada", call["config"].system_instruction)

    @patch("services.ai_service.genai.Client")
    def test_generate_quiz_returns_five_questions_in_expected_shape(self, client_factory):
        questions = [{
            "question": f"Question {index}?",
            "options": ["A", "B", "C", "D"],
            "answer_index": 1,
            "explanation": "Because it is correct.",
        } for index in range(5)]
        client_factory.return_value.models.generate_content.return_value = SimpleNamespace(
            text=json.dumps(questions)
        )

        result = generate_quiz("Science", "Plants", "6")

        self.assertEqual(result, questions)

    @patch("services.ai_service.genai.Client")
    def test_generate_quiz_rejects_wrong_question_count(self, client_factory):
        client_factory.return_value.models.generate_content.return_value = SimpleNamespace(
            text="[]"
        )

        with self.assertRaises(AIResponseError):
            generate_quiz("Science", "Plants", "6")


if __name__ == "__main__":
    unittest.main()
