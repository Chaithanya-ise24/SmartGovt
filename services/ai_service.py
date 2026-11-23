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

REQUEST_TIMEOUT_SECONDS = 120
IMAGE_REQUEST_TIMEOUT_SECONDS = 180
MAX_RETRIES = 2
RETRY_BACKOFF_SECONDS = 1
RETRYABLE_STATUS_CODES = frozenset({429, 503, 504})

DEMO_TOPIC_RESPONSES = (
    (
        re.compile(r"\bjava\b|ಜಾವಾ"),
        "Java is a high-level, class-based programming language used to build applications. "
        "Its code runs on the Java Virtual Machine (JVM), which helps it work across systems.",
        "Java ಒಂದು ಉನ್ನತ ಮಟ್ಟದ, ಕ್ಲಾಸ್ ಆಧಾರಿತ ಪ್ರೋಗ್ರಾಮಿಂಗ್ ಭಾಷೆ. ಇದರ ಕೋಡ್ Java Virtual "
        "Machine (JVM) ಮೇಲೆ ಕಾರ್ಯನಿರ್ವಹಿಸುವುದರಿಂದ ವಿವಿಧ ವ್ಯವಸ್ಥೆಗಳಲ್ಲಿ ಬಳಸಬಹುದು.",
    ),
    (
        re.compile(r"\bpython\b|ಪೈಥಾನ್|ಪೈಥನ್"),
        "Python is a programming language with readable syntax. It is used in education, "
        "web development, automation, and data science.",
        "Python ಸುಲಭವಾಗಿ ಓದಬಹುದಾದ ರಚನೆಯಿರುವ ಪ್ರೋಗ್ರಾಮಿಂಗ್ ಭಾಷೆ. ಇದನ್ನು ಶಿಕ್ಷಣ, ವೆಬ್ "
        "ಅಭಿವೃದ್ಧಿ, ಸ್ವಯಂಚಾಲನೆ ಮತ್ತು ಡೇಟಾ ವಿಜ್ಞಾನದಲ್ಲಿ ಬಳಸುತ್ತಾರೆ.",
    ),
    (
        re.compile(r"\bevaporation\b|\bevaporate\b|ಆವಿಯಾಗುವಿಕೆ|ಆವೀಕರಣ"),
        "Evaporation is the process in which liquid at a surface gains energy and becomes "
        "gas. Water can evaporate below its boiling point.",
        "ಆವೀಕರಣದಲ್ಲಿ ದ್ರವದ ಮೇಲ್ಮೈಯಲ್ಲಿರುವ ಕಣಗಳು ಶಕ್ತಿಯನ್ನು ಪಡೆದು ಅನಿಲವಾಗುತ್ತವೆ. ನೀರು "
        "ಕುದಿಯುವ ಬಿಂದುವಿಗಿಂತ ಕಡಿಮೆ ತಾಪಮಾನದಲ್ಲಿಯೂ ಆವಿಯಾಗಬಹುದು.",
    ),
    (
        re.compile(r"\bphotosynthesis\b|ಪ್ರಕಾಶಸಂಶ್ಲೇಷಣೆ|ದ್ಯುತಿಸಂಶ್ಲೇಷಣೆ"),
        "Photosynthesis is how green plants use sunlight, water, and carbon dioxide to "
        "make sugar and release oxygen.",
        "ಪ್ರಕಾಶಸಂಶ್ಲೇಷಣೆಯಲ್ಲಿ ಹಸಿರು ಸಸ್ಯಗಳು ಸೂರ್ಯನ ಬೆಳಕು, ನೀರು ಮತ್ತು ಕಾರ್ಬನ್ ಡೈಆಕ್ಸೈಡ್ "
        "ಬಳಸಿ ಸಕ್ಕರೆಯನ್ನು ತಯಾರಿಸಿ ಆಮ್ಲಜನಕವನ್ನು ಬಿಡುಗಡೆ ಮಾಡುತ್ತವೆ.",
    ),
    (
        re.compile(r"\bdatabases?\b|ಡೇಟಾಬೇಸ್|ದತ್ತಸಂಚಯ"),
        "A database is an organized collection of information that can be stored, searched, "
        "and updated. A school database might store student records.",
        "ದತ್ತಸಂಚಯವು ಸಂಗ್ರಹಿಸಲು, ಹುಡುಕಲು ಮತ್ತು ನವೀಕರಿಸಲು ಸಾಧ್ಯವಾದ ಮಾಹಿತಿಯ ವ್ಯವಸ್ಥಿತ "
        "ಸಂಗ್ರಹವಾಗಿದೆ. ಶಾಲೆಯ ದತ್ತಸಂಚಯದಲ್ಲಿ ವಿದ್ಯಾರ್ಥಿಗಳ ದಾಖಲೆಗಳಿರಬಹುದು.",
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
    model_name = "gemini-3.8-flash"
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
            http_options=types.HttpOptions(timeout=timeout * 1000)
        )
        return client, model_name
    except Exception as exc:
        _log_gemini_error(
            "client_init",
            model_name,
            exc,
            duration_ms=int((time.monotonic() - started_at) * 1000),
            attempts=1
        )
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


def _generate(client, model_name, prompt, operation):
    response = _run_gemini_request(
        operation,
        model_name,
        lambda selected_model: client.models.generate_content(
            model=selected_model,
            contents=prompt
        )
    )
    return _extract_text(response)


def chat_reply(history, message, language="en", subject=None, context=None):
    client, model_name = _client()
    language_name = _language_name(language)
    history = history[-20:] if isinstance(history, (list, tuple)) else []

    gemini_history = []
    for item in history:
        if not isinstance(item, dict):
            continue
        role = "model" if item.get("role") == "assistant" else "user"
        content = item.get("content")
        if content:
            gemini_history.append({"role": role, "parts": [str(content)]})

    prompt = (
        f"Reply in {language_name}. You are a school tutor for an Indian student. "
        f"Subject: {subject or 'General'}. {context or ''}\n"
        f"Give a clear, age-appropriate educational answer.\n\nStudent question: {message}"
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
        answer = _extract_text(response)
    finally:
        client.close()

    if not answer:
        raise AIError("Gemini returned an empty response.")
    return answer


def explain_image(image_bytes, mime_type, language="en"):
    client, model_name = _client(timeout=IMAGE_REQUEST_TIMEOUT_SECONDS)
    language_name = _language_name(language)
    prompt = (
        f"Analyze this school study image and respond in {language_name}. "
        "Return a JSON object with exactly these keys: summary, definitions, analogy. "
        "summary must be an array of 3 short useful points. "
        "definitions must be an array of important terms and meanings. "
        "analogy must be a short simple analogy."
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
    return {"summary": summary, "definitions": definitions, "analogy": analogy}


def generate_quiz(class_name, subject, chapter, language="en", context=None):
    client, model_name = _client()
    language_name = _language_name(language)
    prompt = (
        f"Create exactly 5 multiple-choice questions for Class {class_name} in {language_name}. "
        f"Subject: {subject}. Chapter: {chapter}. {context or ''}\n"
        "Return only valid JSON as an array. Each item must contain exactly: "
        'question (string), options (array of exactly 4 strings), answer_index '
        "(integer from 0 to 3), and explanation (short string)."
    )
    try:
        text = _generate(client, model_name, prompt, "quiz")
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
            "question": question.strip(),
            "options": [option.strip() for option in options],
            "answer_index": answer_index,
            "explanation": explanation.strip()
        })
    return quiz


def generate_summary(class_name, subject, chapter, language="en", context=None):
    client, model_name = _client()
    language_name = _language_name(language)
    prompt = (
        f"Write a clear educational summary for Class {class_name} in {language_name}. "
        f"Subject: {subject}. Chapter: {chapter}. {context or ''}\n"
        "Keep it useful for revision and organize it with headings and bullet points."
    )
    try:
        summary = _generate(client, model_name, prompt, "summary")
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
        f"Create a worksheet for Class {class_name} in {language_name}. "
        f"Subject: {subject}. Chapter: {chapter}. {context or ''}\n"
        f"Generate exactly {n_questions} questions. "
        "Return only valid JSON with title (string), instructions (string), "
        "questions (array of objects containing number, question, answer), "
        "and answer_key (array of strings)."
    )
    try:
        text = _generate(client, model_name, prompt, "worksheet")
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