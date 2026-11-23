import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from flask import Flask
from google.genai.errors import ClientError, ServerError

from blueprints import ai as ai_blueprint
from services import ai_service


class GeminiRequestRetryTests(unittest.TestCase):
    @staticmethod
    def _provider_error(status_code, retry_after=None):
        headers = {}
        if retry_after is not None:
            headers["Retry-After"] = retry_after
        response = SimpleNamespace(status_code=status_code, headers=headers)
        error_status = {
            400: "INVALID_ARGUMENT",
            401: "UNAUTHENTICATED",
            429: "RESOURCE_EXHAUSTED",
            503: "UNAVAILABLE",
            504: "DEADLINE_EXCEEDED",
            403: "PERMISSION_DENIED",
        }[status_code]
        error = {
            "error": {
                "status": error_status,
                "message": "test-secret-api-key private-student-details",
            }
        }
        error_type = ClientError if status_code < 500 else ServerError
        return error_type(status_code, error, response)

    def test_retries_only_temporary_provider_statuses(self):
        for status_code in (429, 503, 504):
            with self.subTest(status_code=status_code):
                request = Mock(side_effect=[self._provider_error(status_code), "ok"])
                with patch.object(ai_service.time, "sleep") as sleep:
                    result = ai_service._run_gemini_request("test", "test-model", request)

                self.assertEqual(result, "ok")
                self.assertEqual(request.call_count, 2)
                sleep.assert_called_once_with(1)

    def test_retry_after_is_respected(self):
        request = Mock(side_effect=[self._provider_error(429, "4"), "ok"])
        with patch.object(ai_service.time, "sleep") as sleep:
            result = ai_service._run_gemini_request("test", "test-model", request)

        self.assertEqual(result, "ok")
        sleep.assert_called_once_with(4)

    def test_retries_are_limited(self):
        error = self._provider_error(504)
        request = Mock(side_effect=[error, error, error])
        with patch.object(ai_service.time, "sleep") as sleep:
            with self.assertRaises(ai_service.AIError):
                ai_service._run_gemini_request("test", "test-model", request)

        self.assertEqual(request.call_count, ai_service.MAX_RETRIES + 1)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2])

    def test_configured_fallback_is_tried_after_primary_retries(self):
        app = Flask(__name__)
        app.config["GEMINI_FALLBACK_MODEL"] = "gemini-3.7-flash"
        requested_models = []

        def request(model_name):
            requested_models.append(model_name)
            if model_name == "primary-model":
                raise self._provider_error(503)
            return "fallback response"

        with app.app_context(), patch.object(ai_service.time, "sleep"):
            result = ai_service._run_gemini_request(
                "test",
                "primary-model",
                request
            )

        self.assertEqual(result, "fallback response")
        self.assertEqual(
            requested_models,
            ["primary-model"] * (ai_service.MAX_RETRIES + 1) + ["gemini-3.7-flash"]
        )

    def test_permanent_primary_error_does_not_try_fallback(self):
        app = Flask(__name__)
        app.config["GEMINI_FALLBACK_MODEL"] = "gemini-3.7-flash"
        requested_models = []

        def request(model_name):
            requested_models.append(model_name)
            raise self._provider_error(401)

        with app.app_context(), patch.object(ai_service.time, "sleep"):
            with self.assertRaises(ai_service.AIError):
                ai_service._run_gemini_request(
                    "test",
                    "primary-model",
                    request
                )

        self.assertEqual(requested_models, ["primary-model"])

    def test_demo_mode_returns_labeled_samples_without_live_call(self):
        app = Flask(__name__)
        app.config["AI_DEMO_MODE"] = True
        with app.app_context(), patch.object(ai_blueprint, "chat_reply") as live_reply:
            for language in ("en", "kn"):
                with self.subTest(language=language):
                    answer, demo_mode = ai_blueprint._chat_answer(
                        [],
                        "What is Java?" if language == "en" else "ಜಾವಾ ಎಂದರೇನು?",
                        language
                    )

                    self.assertTrue(demo_mode)
                    self.assertIn("DEMO MODE", answer)
                    self.assertIn("ಲೈವ್ AI ರಚಿಸಿದುದಲ್ಲ" if language == "kn" else "not live AI-generated", answer)
            live_reply.assert_not_called()

    def test_demo_answers_match_supported_topics_in_english_and_kannada(self):
        english_questions = (
            ("What is Java?", "Java is"),
            ("What is Python?", "Python is"),
            ("What is evaporation?", "Evaporation is"),
            ("What is photosynthesis?", "Photosynthesis is"),
            ("What is a database?", "A database is"),
        )
        for question, expected in english_questions:
            with self.subTest(question=question):
                answer = ai_service.demo_chat_reply(question, "en")
                self.assertIn("DEMO MODE", answer)
                self.assertIn("not live AI-generated", answer)
                self.assertIn(expected, answer)

        kannada_questions = (
            ("ಜಾವಾ ಎಂದರೇನು?", "Java ಒಂದು"),
            ("ಪೈಥಾನ್ ಎಂದರೇನು?", "Python"),
            ("ಆವಿಯಾಗುವಿಕೆ ಎಂದರೇನು?", "ಆವೀಕರಣದಲ್ಲಿ"),
            ("ಪ್ರಕಾಶಸಂಶ್ಲೇಷಣೆ ಎಂದರೇನು?", "ಹಸಿರು ಸಸ್ಯಗಳು"),
            ("ದತ್ತಸಂಚಯ ಎಂದರೇನು?", "ದತ್ತಸಂಚಯವು"),
        )
        for question, expected in kannada_questions:
            with self.subTest(question=question):
                answer = ai_service.demo_chat_reply(question, "kn")
                self.assertIn("DEMO MODE", answer)
                self.assertIn("ಲೈವ್ AI ರಚಿಸಿದುದಲ್ಲ", answer)
                self.assertIn(expected, answer)

    def test_unmatched_demo_question_shows_requested_message(self):
        answer = ai_service.demo_chat_reply("Why is the sky blue?", "en")
        self.assertIn("DEMO MODE", answer)
        self.assertIn(
            "Demo mode: This question is not included in the sample answers. "
            "Enable live Gemini AI for a generated answer.",
            answer
        )
        kannada_answer = ai_service.demo_chat_reply("ಆಕಾಶ ನೀಲಿಯಾಗಿರುವುದು ಏಕೆ?", "kn")
        self.assertIn("DEMO MODE", kannada_answer)
        self.assertIn("ಈ ಪ್ರಶ್ನೆ ಮಾದರಿ ಉತ್ತರಗಳಲ್ಲಿ ಸೇರಿಲ್ಲ", kannada_answer)

    def test_live_mode_propagates_provider_failure_instead_of_faking(self):
        app = Flask(__name__)
        app.config["AI_DEMO_MODE"] = False
        with app.app_context(), patch.object(
            ai_blueprint,
            "chat_reply",
            side_effect=ai_service.AIError("Gemini is temporarily unavailable.")
        ):
            with self.assertRaises(ai_service.AIError):
                ai_blueprint._chat_answer([], "Explain fractions", "kn")

    def test_permanent_error_is_not_retried_or_logged_with_payload(self):
        for status_code in (400, 401, 403):
            with self.subTest(status_code=status_code):
                request = Mock(side_effect=self._provider_error(status_code))
                with patch.object(ai_service.time, "sleep") as sleep:
                    with self.assertLogs(ai_service.logger, level="ERROR") as captured:
                        with self.assertRaises(ai_service.AIError):
                            ai_service._run_gemini_request(
                                "test",
                                "test-model",
                                request
                            )

                self.assertEqual(request.call_count, 1)
                sleep.assert_not_called()
                logs = "\n".join(captured.output)
                self.assertIn("http_status={}".format(status_code), logs)
                self.assertIn("duration_ms=", logs)
                self.assertNotIn("test-secret-api-key", logs)
                self.assertNotIn("private-student-details", logs)
                if status_code == 403:
                    self.assertIn("error_code=PERMISSION_DENIED", logs)

    def test_chat_and_generated_content_paths_remain_available(self):
        chat = Mock()
        chat.send_message.side_effect = [
            SimpleNamespace(text="English reply"),
            SimpleNamespace(text="Kannada reply"),
        ]
        questions = [
            {
                "question": "Q{}".format(index),
                "options": ["A", "B", "C", "D"],
                "answer_index": 0,
                "explanation": "Reason",
            }
            for index in range(5)
        ]
        image_result = {
            "summary": ["Point 1"],
            "definitions": ["Term"],
            "analogy": "Comparison",
        }
        worksheet_result = {
            "title": "Worksheet",
            "instructions": "Answer the question",
            "questions": [{"number": 1, "question": "Q", "answer": "A"}],
            "answer_key": ["A"],
        }
        client = Mock()
        client.chats.create.return_value = chat
        client.models.generate_content.side_effect = [
            SimpleNamespace(text=json.dumps(image_result)),
            SimpleNamespace(text=json.dumps(questions)),
            SimpleNamespace(text="Summary"),
            SimpleNamespace(text=json.dumps(worksheet_result)),
        ]

        with patch.object(ai_service, "_client", return_value=(client, "test-model")):
            self.assertEqual(ai_service.chat_reply([], "Question", "en"), "English reply")
            self.assertEqual(ai_service.chat_reply([], "ಪ್ರಶ್ನೆ", "kn"), "Kannada reply")
            self.assertEqual(
                ai_service.explain_image(b"image", "image/png", "kn"),
                image_result
            )
            self.assertEqual(
                len(ai_service.generate_quiz("5", "Science", "Plants", "kn")),
                5
            )
            self.assertEqual(
                ai_service.generate_summary("5", "Science", "Plants", "en"),
                "Summary"
            )
            self.assertEqual(
                ai_service.generate_worksheet("5", "Science", "Plants", 1, "kn"),
                worksheet_result
            )

        chat_prompts = [
            call.kwargs["message"] for call in chat.send_message.call_args_list
        ]
        self.assertIn("English", chat_prompts[0])
        self.assertIn("Kannada", chat_prompts[1])
        generated_prompts = [
            call.kwargs["contents"]
            for call in client.models.generate_content.call_args_list
        ]
        self.assertIn("Kannada", generated_prompts[0][1])
        self.assertIn("Kannada", generated_prompts[1])
        self.assertIn("English", generated_prompts[2])
        self.assertIn("Kannada", generated_prompts[3])

    def test_timeout_is_configured_in_milliseconds(self):
        app = Flask(__name__)
        app.config["GEMINI_API_KEY"] = "test-key"
        with app.app_context(), patch.object(
            ai_service.genai, "Client", return_value=Mock()
        ) as create_client:
            ai_service._client()

        options = create_client.call_args.kwargs["http_options"]
        self.assertEqual(options.timeout, ai_service.REQUEST_TIMEOUT_SECONDS * 1000)
