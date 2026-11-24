import json
import logging
import math
import os
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from flask import current_app

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None


logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 45
IMAGE_REQUEST_TIMEOUT_SECONDS = 90
MAX_RETRIES = 2
RETRY_BACKOFF_SECONDS = 1
RETRYABLE_STATUS_CODES = frozenset({429, 503, 504})

DEMO_TOPIC_RESPONSES = (
    (
        re.compile(r"\bjava\b|ಜಾವಾ"),
        "Java is a computer language used to build apps and games. "
        "It runs on a special tool called JVM so the same app works on different computers.",
        "Java ಎಂಬುದು ಆ್ಯಪ್‌ಗಳು ಮತ್ತು ಗೇಮ್‌ಗಳನ್ನು ತಯಾರಿಸಲು ಬಳಸುವ ಕಂಪ್ಯೂಟರ್ ಭಾಷೆ. "
        "ಇದು JVM ಎಂಬ ಸಾಧನದ ಮೇಲೆ ನಡೆಯುವುದರಿಂದ ಬೇರೆ ಬೇರೆ ಕಂಪ್ಯೂಟರ್‌ಗಳಲ್ಲಿ ಕೆಲಸ ಮಾಡುತ್ತದೆ.",
    ),
    (
        re.compile(r"\bpython\b|ಪೈಥಾನ್|ಪೈಥನ್"),
        "Python is an easy-to-read computer language used to make websites, games, and smart tools. "
        "Its commands look almost like simple English sentences.",
        "Python ಓದಲು ಸುಲಭವಾದ ಕಂಪ್ಯೂಟರ್ ಭಾಷೆಯಾಗಿದ್ದು ವೆಬ್‌ಸೈಟ್ ಮತ್ತು ಗೇಮ್‌ಗಳನ್ನು ತಯಾರಿಸಲು ಬಳಸುತ್ತಾರೆ. "
        "ಇದರ ಆಜ್ಞೆಗಳು ಸರಳ ಇಂಗ್ಲಿಷ್ ವಾಕ್ಯಗಳಂತೆಯೇ ಇರುತ್ತವೆ.",
    ),
    (
        re.compile(r"\bevaporation\b|\bevaporate\b|ಆವಿಯಾಗುವಿಕೆ|ಆವೀಕರಣ"),
        "Evaporation happens when liquid water warms up and turns into invisible gas in the air. "
        "That is why wet clothes dry on a sunny afternoon.",
        "ನೀರು ಬಿಸಿಯಾಗಿ ಗಾಳಿಯಲ್ಲಿ ಕಾಣದ ಆವಿಯಾಗಿ ಬದಲಾಗುವುದೇ ಆವೀಕರಣ. "
        "ಬಿಸಿಲಿನಲ್ಲಿ ಒದ್ದೆ ಬಟ್ಟೆಗಳು ಒಣಗಲು ಇದೇ ಕಾರಣ.",
    ),
    (
        re.compile(r"\bphotosynthesis\b|ಪ್ರಕಾಶಸಂಶ್ಲೇಷಣೆ|ದ್ಯುತಿಸಂಶ್ಲೇಷಣೆ"),
        "Photosynthesis is how green plants make their own food using sunlight, water, and air. "
        "While making food, plants also release fresh oxygen for us to breathe.",
        "ಹಸಿರು ಸಸ್ಯಗಳು ಸೂರ್ಯನ ಬೆಳಕು, ನೀರು ಮತ್ತು ಗಾಳಿಯನ್ನು ಬಳಸಿ ತಮ್ಮ ಆಹಾರವನ್ನು ತಯಾರಿಸುವುದೇ ಪ್ರಕಾಶಸಂಶ್ಲೇಷಣೆ. "
        "ಈ ಸಮಯದಲ್ಲಿ ಸಸ್ಯಗಳು ನಾವು ಉಸಿರಾಡಲು ಆಮ್ಲಜನಕವನ್ನು ನೀಡುತ್ತವೆ.",
    ),
    (
        re.compile(r"\bdatabases?\b|ಡೇಟಾಬೇಸ್|ದತ್ತಸಂಚಯ"),
        "A database is like a neat digital register that stores information so you can find it fast. "
        "A school database keeps student names, roll numbers, and marks safe.",
        "ಡೇಟಾಬೇಸ್ ಎಂದರೆ ಮಾಹಿತಿಯನ್ನು ಅಚ್ಚುಕಟ್ಟಾಗಿ ಸಂಗ್ರಹಿಸಿಡುವ ಡಿಜಿಟಲ್ ರಿಜಿಸ್ಟರ್ ಇದ್ದಂತೆ. "
        "ಶಾಲೆಯ ಡೇಟಾಬೇಸ್‌ನಲ್ಲಿ ವಿದ್ಯಾರ್ಥಿಗಳ ಹೆಸರು ಮತ್ತು ಅಂಕಗಳನ್ನು ಸುರಕ್ಷಿತವಾಗಿ ಇಡಲಾಗುತ್ತದೆ.",
    ),
)

DEMO_UNMATCHED_RESPONSE = (
    "DEMO MODE\n"
    "Demo mode: This question is not included in the sample answers. "
    "Enable live Gemini AI for a generated answer."
)
DEMO_UNMATCHED_RESPONSE_KN = (
    DEMO_UNMATCHED_RESPONSE
    + "\nಡೆಮೋ ಮೋಡ್: ಈ ಪ್ರಶ್ನೆ ಮಾದರಿ ಉತ್ತರಗಳಲ್ಲಿ ಸೇರಿಲ್ಲ. "
    "ಉತ್ಪಾದಿತ ಉತ್ತರಕ್ಕಾಗಿ ಲೈವ್ Gemini AI ಅನ್ನು ಸಕ್ರಿಯಗೊಳಿಸಿ."
)


class AIError(Exception):
    """Safe, user-facing-independent exception for AI service failures."""


def _clean_plain_text(text):
    """Strip Markdown symbols (**bold**, *italic*, # headings, bullet *) for plain-text chat UI."""
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"\*(.*?)\*", r"\1", text)
    text = re.sub(r"(?m)^\s*#{1,6}\s*", "", text)
    text = re.sub(r"(?m)^\s*\*\s+", "- ", text)
    return text.strip()


def _http_status(exc):
    status = getattr(exc, "code", None)
    if isinstance(status, int) and not isinstance(status, bool):
        return status

    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if isinstance(status, int) and not isinstance(status, bool):
        return status
    return None


def _provider_error_code(exc):
    response_json = getattr(exc, "response_json", None)
    error_details = response_json.get("error", {}) if isinstance(response_json, dict) else {}
    if not isinstance(error_details, dict):
        error_details = {}

    error_code = error_details.get("status") or getattr(exc, "status", None)
    if isinstance(error_code, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", error_code):
        return error_code
    return "unavailable"


def _safe_model_name(model_name):
    if isinstance(model_name, str) and re.fullmatch(r"[A-Za-z0-9._/-]{1,100}", model_name):
        return model_name
    return "configured"


def _fallback_model_name(primary_model):
    try:
        fallback_model = current_app.config.get("GEMINI_FALLBACK_MODEL", "")
    except RuntimeError:
        fallback_model = os.getenv("GEMINI_FALLBACK_MODEL", "")

    if not isinstance(fallback_model, str):
        return None
    fallback_model = fallback_model.strip()
    if not fallback_model or not re.fullmatch(r"[A-Za-z0-9._/-]{1,100}", fallback_model):
        return None
    if fallback_model.rsplit("/", 1)[-1].casefold() == primary_model.rsplit("/", 1)[-1].casefold():
        return None
    return fallback_model


def _log_gemini_error(operation, model_name, exc, duration_ms=None, attempts=None, level=logging.ERROR):
    http_status = _http_status(exc)
    if http_status is None:
        http_status = "unavailable"

    logger.log(
        level,
        "Gemini request failed operation=%s model=%s exception_class=%s "
        "http_status=%s error_code=%s duration_ms=%s attempts=%s",
        operation,
        _safe_model_name(model_name),
        type(exc).__name__,
        http_status,
        _provider_error_code(exc),
        duration_ms if duration_ms is not None else "unavailable",
        attempts if attempts is not None else "unavailable"
    )


def _retry_after_seconds(exc):
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None

    retry_after = headers.get("Retry-After")
    if retry_after is None:
        return None

    try:
        seconds = float(retry_after)
        return max(0.0, seconds) if math.isfinite(seconds) else None
    except (TypeError, ValueError):
        pass

    try:
        retry_at = parsedate_to_datetime(retry_after)
    except (TypeError, ValueError, OverflowError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())


def _run_gemini_request(operation, model_name, request):
    started_at = time.monotonic()
    total_attempts = 0
    fallback_model = _fallback_model_name(model_name)
    models = [model_name]
    if fallback_model:
        models.append(fallback_model)

    for model_index, active_model in enumerate(models):
        attempt_limit = MAX_RETRIES + 1 if model_index == 0 else 1
        for attempt in range(1, attempt_limit + 1):
            total_attempts += 1
            try:
                response = request(active_model)
            except Exception as exc:
                status = _http_status(exc)
                is_retryable = status in RETRYABLE_STATUS_CODES
                can_retry = is_retryable and model_index == 0 and attempt < attempt_limit
                can_fallback = (
                    is_retryable
                    and model_index == 0
                    and attempt == attempt_limit
                    and fallback_model is not None
                )

                if can_retry:
                    backoff = RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))
                    retry_after = _retry_after_seconds(exc)
                    delay = max(backoff, retry_after or 0)
                    _log_gemini_error(
                        operation,
                        active_model,
                        exc,
                        duration_ms=int((time.monotonic() - started_at) * 1000),
                        attempts=total_attempts,
                        level=logging.WARNING
                    )
                    time.sleep(delay)
                    continue

                if can_fallback:
                    _log_gemini_error(
                        operation,
                        active_model,
                        exc,
                        duration_ms=int((time.monotonic() - started_at) * 1000),
                        attempts=total_attempts,
                        level=logging.WARNING
                    )
                    break

                _log_gemini_error(
                    operation,
                    active_model,
                    exc,
                    duration_ms=int((time.monotonic() - started_at) * 1000),
                    attempts=total_attempts
                )
                raise AIError("Gemini is temporarily unavailable.") from exc

            logger.info(
                "Gemini request completed operation=%s model=%s duration_ms=%d "
                "attempts=%d fallback_used=%s",
                operation,
                _safe_model_name(active_model),
                int((time.monotonic() - started_at) * 1000),
                total_attempts,
                model_index > 0
            )
            return response

    raise AIError("Gemini is temporarily unavailable.")


def demo_chat_reply(message, language="en"):
    normalized_message = message.casefold() if isinstance(message, str) else ""
    use_kannada = language == "kn"

    for pattern, english_response, kannada_response in DEMO_TOPIC_RESPONSES:
        if pattern.search(normalized_message):
            sample = kannada_response if use_kannada else english_response
            if use_kannada:
                return "DEMO MODE — ಮಾದರಿ ಉತ್ತರ (ಲೈವ್ AI ರಚಿಸಿದುದಲ್ಲ): " + sample
            return "DEMO MODE — Sample answer (not live AI-generated): " + sample

    return DEMO_UNMATCHED_RESPONSE_KN if use_kannada else DEMO_UNMATCHED_RESPONSE


def _language_name(language):
    return "Kannada" if language == "kn" else "English"


def _api_settings():
    api_key = None
    model_name = "gemini-2.5-flash"
    try:
        api_key = current_app.config.get("GEMINI_API_KEY")
        model_name = current_app.config.get("GEMINI_MODEL", model_name)
    except RuntimeError:
        api_key = os.getenv("GEMINI_API_KEY")
        model_name = os.getenv("GEMINI_MODEL", model_name)

    if not isinstance(api_key, str) or not api_key.strip():
        raise AIError("Gemini API key is not configured.")
    if genai is None or types is None:
        raise AIError("The Gemini SDK is not installed.")
    return api_key.strip(), model_name


def _client(timeout=REQUEST_TIMEOUT_SECONDS):
    api_key, model_name = _api_settings()
    started_at = time.monotonic()
    try:
        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=int(timeout * 1000)),
        )
        return client, model_name
    except Exception as exc:
        _log_gemini_error("client_init", model_name, exc,
                          duration_ms=int((time.monotonic() - started_at) * 1000),
                          attempts=1)
        raise AIError("Gemini is temporarily unavailable.") from exc


def _extract_text(response):
    text = getattr(response, "text", None)
    if text:
        return text.strip()

    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) if content else None
        if parts:
            for part in parts:
                value = getattr(part, "text", None)
                if value:
                    return value.strip()
    raise AIError("Gemini returned an empty response.")


def _parse_json(text):
    text = text.strip()
    if text.startswith("```"):
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
        if match:
            text = match.group(1).strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise AIError("Gemini returned malformed structured data.") from exc


def _generate(client, model_name, prompt, operation, json_mode=False):
    config = (types.GenerateContentConfig(response_mime_type="application/json")
              if json_mode else None)
    response = _run_gemini_request(
        operation, model_name,
        lambda selected_model: client.models.generate_content(
            model=selected_model, contents=prompt, config=config))
    return _extract_text(response)


def chat_reply(history, message, language="en", subject=None, context=None):
    client, model_name = _client()
    language_name = _language_name(language)
    history = history[-20:] if isinstance(history, (list, tuple)) else []

    gemini_history = []
    for item in history:
        if not isinstance(item, dict):
            continue
        raw_role = item.get("role")
        role = "model" if raw_role in ("assistant", "model") else "user"
        text = item.get("text") or item.get("content")
        if text:
            gemini_history.append(
                types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=str(text))]
                )
            )

    prompt = (
        f"Reply in {language_name}. You are explaining a school topic to a 12-year-old middle school student (Class 5 to 7) in Karnataka, India. "
        f"Subject: {subject or 'General'}. {context or ''}\n"
        "Rules:\n"
        "1. Use very simple, everyday words—no heavy textbook or college jargon.\n"
        "2. Keep the entire answer to 3 or 4 short sentences maximum.\n"
        "3. Give 1 simple real-life example a kid knows (like food, plants, cricket, or kitchen items).\n"
        "4. Do NOT use Markdown symbols like **, *, or #—use plain text only.\n\n"
        f"Student question: {message}"
    )

    try:
        response = _run_gemini_request(
            "chat",
            model_name,
            lambda selected_model: client.chats.create(
                model=selected_model,
                history=gemini_history
            ).send_message(message=prompt)
        )
        answer = _clean_plain_text(_extract_text(response))
    finally:
        client.close()

    if not answer:
        raise AIError("Gemini returned an empty response.")
    return answer


def explain_image(image_bytes, mime_type, language="en"):
    client, model_name = _client(timeout=IMAGE_REQUEST_TIMEOUT_SECONDS)
    language_name = _language_name(language)
    prompt = (
        f"Explain this school study image to a 12-year-old middle school student (Class 5 to 7) in {language_name} using very simple words. "
        "Return a JSON object with exactly these keys: summary, definitions, analogy. "
        "summary must be an array of 3 short, easy-to-read sentences (no jargon). "
        "definitions must be an array of key words explained like you are talking to a kid. "
        "analogy must be 1 fun everyday comparison (like toys, sports, or cooking). "
        "Do not use ** or # formatting."
    )
    try:
        response = _run_gemini_request(
            "image_explanation",
            model_name,
            lambda selected_model: client.models.generate_content(
                model=selected_model,
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                    prompt
                ]
            )
        )
        result = _parse_json(_extract_text(response))
    except AIError:
        raise
    finally:
        client.close()

    if not isinstance(result, dict):
        raise AIError("Gemini returned invalid image explanation data.")
    summary = result.get("summary")
    definitions = result.get("definitions")
    analogy = result.get("analogy")
    if not isinstance(summary, list) or not all(isinstance(x, str) for x in summary):
        raise AIError("Gemini returned invalid image summary data.")
    if not isinstance(definitions, list) or not all(isinstance(x, str) for x in definitions):
        raise AIError("Gemini returned invalid image definitions.")
    if not isinstance(analogy, str):
        raise AIError("Gemini returned invalid image analogy.")
    return {
        "summary": [_clean_plain_text(x) for x in summary],
        "definitions": [_clean_plain_text(x) for x in definitions],
        "analogy": _clean_plain_text(analogy),
    }


def generate_quiz(class_name, subject, chapter, language="en", context=None):
    client, model_name = _client()
    language_name = _language_name(language)
    prompt = (
        f"Create exactly 5 simple multiple-choice questions for a Class {class_name} middle school student (age 11-13) in {language_name}. "
        f"Subject: {subject}. Chapter: {chapter}. {context or ''}\n"
        "Use clear, simple language suitable for middle school kids. "
        "Return only valid JSON as an array. Each item must contain exactly: "
        'question (string), options (array of exactly 4 strings), answer_index '
        "(integer from 0 to 3), and explanation (1 short, easy-to-understand sentence)."
    )
    try:
        text = _generate(client, model_name, prompt, "quiz", json_mode=True)
    finally:
        client.close()
    result = _parse_json(text)
    if not isinstance(result, list) or len(result) != 5:
        raise AIError("Gemini did not return exactly 5 quiz questions.")

    quiz = []
    for item in result:
        if not isinstance(item, dict):
            raise AIError("Gemini returned invalid quiz data.")
        question = item.get("question")
        options = item.get("options")
        answer_index = item.get("answer_index")
        explanation = item.get("explanation")
        if not isinstance(question, str) or not question.strip():
            raise AIError("Gemini returned an invalid quiz question.")
        if not isinstance(options, list) or len(options) != 4 or not all(isinstance(x, str) and x.strip() for x in options):
            raise AIError("Gemini returned invalid quiz options.")
        if not isinstance(answer_index, int) or isinstance(answer_index, bool) or not 0 <= answer_index <= 3:
            raise AIError("Gemini returned an invalid quiz answer index.")
        if not isinstance(explanation, str):
            raise AIError("Gemini returned an invalid quiz explanation.")
        quiz.append({
            "question": _clean_plain_text(question),
            "options": [_clean_plain_text(option) for option in options],
            "answer_index": answer_index,
            "explanation": _clean_plain_text(explanation),
        })
    return quiz


def generate_summary(class_name, subject, chapter, language="en", context=None):
    client, model_name = _client()
    language_name = _language_name(language)
    prompt = (
        f"Write a short, easy-to-read revision summary for a Class {class_name} middle school student (age 11-13) in {language_name}. "
        f"Subject: {subject}. Chapter: {chapter}. {context or ''}\n"
        "Use simple everyday words, 4 to 6 short bullet points with '-', and 1 relatable real-life example. "
        "Do NOT use Markdown symbols like **, *, or #."
    )
    try:
        summary = _clean_plain_text(_generate(client, model_name, prompt, "summary"))
    finally:
        client.close()
    if not summary:
        raise AIError("Gemini returned an empty summary.")
    return summary


def generate_worksheet(class_name, subject, chapter, n_questions, language="en", context=None):
    language_name = _language_name(language)
    if not isinstance(n_questions, int) or isinstance(n_questions, bool) or n_questions < 1:
        raise AIError("Question count must be a positive integer.")
    client, model_name = _client()
    prompt = (
        f"Create a simple practice worksheet for a Class {class_name} middle school student (age 11-13) in {language_name}. "
        f"Subject: {subject}. Chapter: {chapter}. {context or ''}\n"
        f"Generate exactly {n_questions} short, clear questions using simple words. "
        "Return only valid JSON with title (string), instructions (string), "
        "questions (array of objects containing number, question, answer), "
        "and answer_key (array of strings)."
    )
    try:
        text = _generate(client, model_name, prompt, "worksheet", json_mode=True)
    finally:
        client.close()
    result = _parse_json(text)
    if not isinstance(result, dict):
        raise AIError("Gemini returned invalid worksheet data.")
    if not isinstance(result.get("title"), str) or not isinstance(result.get("instructions"), str):
        raise AIError("Gemini returned invalid worksheet metadata.")
    questions = result.get("questions")
    answer_key = result.get("answer_key")
    if not isinstance(questions, list) or len(questions) != n_questions:
        raise AIError("Gemini did not create the requested worksheet questions.")
    if not isinstance(answer_key, list) or len(answer_key) != n_questions:
        raise AIError("Gemini returned an invalid worksheet answer key.")
    return result