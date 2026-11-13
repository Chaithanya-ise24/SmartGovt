"""Stubs. Member A replaces the bodies with real Gemini calls.
Keep function names and signatures EXACTLY as they are."""


def chat_reply(history, message, language="en", subject=None, context=None):
    return f"Sample answer to: {message} (stub)"


def explain_image(image_bytes, mime_type, language="en"):
    return {"summary": ["Point 1", "Point 2", "Point 3"],
            "definitions": ["Term: meaning"],
            "analogy": "Sample analogy"}


def generate_quiz(class_name, subject, chapter, language="en", context=None):
    return [{"question": f"Sample question {i} about {chapter}?",
             "options": ["Option A", "Option B", "Option C", "Option D"],
             "answer_index": i % 4,
             "explanation": "Sample explanation."} for i in range(1, 6)]


def generate_summary(class_name, subject, chapter, language="en", context=None):
    return "Sample summary (stub)."


def generate_worksheet(class_name, subject, chapter, n_questions, language="en", context=None):
    return "Sample worksheet (stub)."