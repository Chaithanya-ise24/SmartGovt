import time
from collections import defaultdict, deque
from io import BytesIO

from PIL import Image, UnidentifiedImageError
from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash, g, session, current_app)

from auth_utils import role_required
from models import db, DoubtLog
from services.ai_service import AIError, chat_reply, demo_chat_reply, explain_image

bp = Blueprint("ai", __name__)

SUBJECTS = ["Science", "Mathematics", "Social Science", "English"]
MAX_CALLS_PER_HOUR = 20
_calls = defaultdict(deque)
_histories = {}            # user_id -> chat history on the server (not in the cookie)

DEMO_IMAGE_RESULT = {
    "summary": ["This is a sample explanation (demo mode).",
                "Live AI will read your picture and explain it simply.",
                "Turn off AI_DEMO_MODE in .env to use Gemini."],
    "definitions": ["Demo: a sample meaning appears here."],
    "analogy": "Like a teacher explaining one page of your book in easy words.",
}


def _rate_limited(user_id):
    now = time.time()
    calls = _calls[user_id]
    while calls and now - calls[0] >= 3600:
        calls.popleft()
    if len(calls) >= MAX_CALLS_PER_HOUR:
        return True
    calls.append(now)
    return False


def _lang(value):
    return "kn" if value == "kn" else "en"


def _chat_answer(history, message, language, subject=None, context=None):
    if current_app.config.get("AI_DEMO_MODE", True):
        return demo_chat_reply(message, language), True
    return chat_reply(history, message, language=language,
                      subject=subject, context=context), False


def _detect_image_mime(data):
    try:
        with Image.open(BytesIO(data)) as image:
            image.verify()
            return {"JPEG": "image/jpeg", "PNG": "image/png",
                    "WEBP": "image/webp"}.get((image.format or "").upper())
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError):
        return None


def _looks_like_image(data, mimetype=None):
    detected = _detect_image_mime(data)
    return detected is not None and (mimetype is None or detected == mimetype)


def _demo_notice(language):
    return ("DEMO MODE ಸಕ್ರಿಯವಾಗಿದೆ. ಇದು ಮಾದರಿ ಉತ್ತರ, ಲೈವ್ AI ಉತ್ತರ ಅಲ್ಲ."
            if language == "kn"
            else "DEMO MODE is enabled. This is a sample response, not live AI.")


@bp.route("/student/doubt", methods=["GET", "POST"])
@role_required("student")
def doubt():
    history = _histories.setdefault(g.user.id, [])
    selected_language = _lang(session.get("doubt_language", "en"))
    selected_subject = session.get("doubt_subject", "")

    if request.method == "POST":
        message = request.form.get("message", "").strip()
        raw_subject = request.form.get("subject", "").strip()
        subject = raw_subject if raw_subject in SUBJECTS else ""
        language = _lang(request.form.get("language", "en"))
        session["doubt_language"] = language
        session["doubt_subject"] = subject

        if not message:
            flash("Please enter your question.", "error")
        elif len(message) > 1000:
            flash("Please keep your question under 1000 characters.", "error")
        elif raw_subject and not subject:
            flash("Please select a supported subject.", "error")
        elif _rate_limited(g.user.id):
            flash("You have asked many questions. Please try again later.", "error")
        else:
            try:
                answer, demo_mode = _chat_answer(
                    list(history[-10:]), message, language,
                    subject=subject or None,
                    context=f"Student class: {g.user.class_name}")
                if demo_mode:
                    flash(_demo_notice(language), "warning")

                db.session.add(DoubtLog(student_id=g.user.id, subject=subject or None,
                                        topic=message[:60], question=message))
                db.session.commit()

                history.append({"role": "user", "content": message})
                history.append({"role": "assistant", "content": answer})
                del history[:-20]
            except AIError as exc:
                db.session.rollback()
                current_app.logger.warning("AI doubt chat rejected: %s", exc)
                flash("The AI service is busy right now. Please try again in a minute.", "error")
            except Exception:
                db.session.rollback()
                current_app.logger.exception("AI doubt chat error")
                flash("Sorry, something went wrong. Please try again.", "error")
        return redirect(url_for("ai.doubt"))

    return render_template("student/doubt.html", history=history,
                           selected_language=selected_language,
                           selected_subject=selected_subject, subjects=SUBJECTS)


@bp.route("/student/doubt/clear", methods=["POST"])
@role_required("student")
def clear_doubt():
    _histories.pop(g.user.id, None)
    return redirect(url_for("ai.doubt"))


@bp.route("/student/snap", methods=["GET", "POST"])
@role_required("student")
def snap():
    result = None
    selected_language = _lang(session.get("doubt_language", "en"))

    if request.method == "POST":
        image = request.files.get("image")
        language = _lang(request.form.get("language", "en"))
        selected_language = language
        session["doubt_language"] = language

        if not image or not image.filename:
            flash("Please select an image.", "error")
            return redirect(url_for("ai.snap"))

        data = image.read(5 * 1024 * 1024 + 1)
        if len(data) > 5 * 1024 * 1024:
            flash("Image size must be under 5 MB.", "error")
        else:
            mime = _detect_image_mime(data)
            if mime is None:
                flash("Please upload a valid JPG, PNG, or WEBP image.", "error")
            elif _rate_limited(g.user.id):
                flash("Too many requests. Please try again later.", "error")
            elif current_app.config.get("AI_DEMO_MODE", True):
                result = DEMO_IMAGE_RESULT
                flash(_demo_notice(language), "warning")
            else:
                try:
                    result = explain_image(data, mime, language=language)
                except AIError as exc:
                    current_app.logger.warning("AI image rejected: %s", exc)
                    flash("The AI service is busy right now. Please try again in a minute.", "error")
                except Exception:
                    current_app.logger.exception("AI image error")
                    flash("Unable to process the image. Please try again.", "error")

    return render_template("student/snap.html", result=result,
                           selected_language=selected_language)