import json

from flask import current_app
from google import genai
from google.genai import types


class AIServiceError(RuntimeError):
    pass


class AIConfigurationError(AIServiceError):
    pass


class AIResponseError(AIServiceError):
    pass


def _client_and_model():
    api_key = current_app.config.get("GEMINI_API_KEY")
    if not api_key:
        raise AIConfigurationError("GEMINI_API_KEY is not configured.")
    model = current_app.config.get("GEMINI_MODEL")
    if not model:
        raise AIConfigurationError("GEMINI_MODEL is not configured.")
    return genai.Client(api_key=api_key), model


def _language_name(language):
    if language == "kn":
        return "simple Kannada"
    if language == "en":
        return "easy English"
    raise ValueError("language must be 'en' or 'kn'")


def chat_reply(question, history=None, language="en"):
    """Return one student-friendly Gemini answer using up to ten prior turns."""
    language_name = _language_name(language)
    history = history or []
    contents = []
    for turn in history[-10:]:
        if not isinstance(turn, dict):
            continue
        previous_question = turn.get("question")
        previous_answer = turn.get("answer")
        if isinstance(previous_question, str) and isinstance(previous_answer, str):
            contents.extend([
                {"role": "user", "parts": [{"text": previous_question}]},
                {"role": "model", "parts": [{"text": previous_answer}]},
            ])
    contents.append({"role": "user", "parts": [{"text": question}]})

    client, model = _client_and_model()
    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=(
                "You are a kind tutor for Karnataka State Board students in classes 5, 6, and 7. "
                f"Answer in {language_name}. Use short, clear explanations and age-appropriate "
                "examples. Stay focused on the student's learning question."
            ),
            temperature=0.4,
        ),
    )
    answer = response.text
    if not isinstance(answer, str) or not answer.strip():
        raise AIResponseError("Gemini returned an empty chat answer.")
    return answer.strip()


def generate_quiz(subject, chapter, grade, language="en"):
    """Return exactly five validated multiple-choice questions."""
    language_name = _language_name(language)
    client, model = _client_and_model()
    response = client.models.generate_content(
        model=model,
        contents=(
            f"Create exactly 5 age-appropriate multiple-choice questions for class {grade}, "
            f"subject {subject}, chapter {chapter}. Write in {language_name}. "
            "Return only a JSON array. Each item must have exactly these fields: "
            "question (string), options (array of four strings), answer_index (integer from 0 to 3), "
            "explanation (string)."
        ),
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.4,
        ),
    )
    text = response.text
    if not isinstance(text, str) or not text.strip():
        raise AIResponseError("Gemini returned an empty quiz.")
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[-1].strip().startswith("```"):
            text = "\n".join(lines[1:-1]).strip()

    try:
        questions = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AIResponseError("Gemini returned invalid quiz JSON.") from exc
    if not isinstance(questions, list) or len(questions) != 5:
        raise AIResponseError("Gemini did not return exactly five quiz questions.")

    validated = []
    for item in questions:
        if not isinstance(item, dict):
            raise AIResponseError("A quiz question has an invalid shape.")
        question = item.get("question")
        options = item.get("options")
        answer_index = item.get("answer_index")
        explanation = item.get("explanation")
        if (
            not isinstance(question, str) or not question.strip()
            or not isinstance(options, list) or len(options) != 4
            or any(not isinstance(option, str) or not option.strip() for option in options)
            or type(answer_index) is not int or answer_index not in range(4)
            or not isinstance(explanation, str) or not explanation.strip()
        ):
            raise AIResponseError("A quiz question is missing valid required fields.")
        validated.append({
            "question": question.strip(),
            "options": [option.strip() for option in options],
            "answer_index": answer_index,
            "explanation": explanation.strip(),
        })
    return validated
