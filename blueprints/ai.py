import time
from io import BytesIO
from collections import defaultdict, deque

from PIL import Image, UnidentifiedImageError

from flask import (
    Blueprint, render_template, request,
    redirect, url_for, flash, g, session, current_app
)

from auth_utils import role_required
from models import db, DoubtLog
from services.ai_service import AIError, chat_reply, demo_chat_reply, explain_image

bp = Blueprint("ai", __name__)

SUBJECTS = ["Science", "Mathematics", "Social Science", "English"]
MAX_CALLS_PER_HOUR = 20
_calls = defaultdict(deque)


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
    return chat_reply(
        history,
        message,
        language=language,
        subject=subject,
        context=context
    ), False


def _detect_image_mime(data):
    try:
        with Image.open(BytesIO(data)) as image:
            image.verify()
            actual_format = (image.format or "").upper()
            return {
                "JPEG": "image/jpeg",
                "PNG": "image/png",
                "WEBP": "image/webp",
            }.get(actual_format)
    except (
        Image.DecompressionBombError,
        UnidentifiedImageError,
        OSError,
        ValueError
    ):
        return None


def _looks_like_image(data, mimetype=None):
    detected_mime = _detect_image_mime(data)
    return detected_mime is not None and (mimetype is None or detected_mime == mimetype)


@bp.route("/student/doubt", methods=["GET", "POST"])
@role_required("student")
def doubt():
    history = session.get("doubt_history", [])
    selected_language = _lang(session.get("doubt_language", "en"))
    selected_subject = session.get("doubt_subject", "")

    if request.method == "POST":
        message = request.form.get("message", "").strip()
        subject = request.form.get("subject", "").strip()
        subject = subject if subject in SUBJECTS else ""
        language = _lang(request.form.get("language", "en"))
        session["doubt_language"] = language
        session["doubt_subject"] = subject

        if not message:
            flash("Please enter your question.", "error")
        elif len(message) > 1000:
            flash("Please keep your question under 1000 characters.", "error")
        elif subject == "" and request.form.get("subject", "").strip():
            flash("Please select a supported subject.", "error")
        elif _rate_limited(g.user.id):
            flash("You have asked many questions. Please try again later.", "error")
        else:
            try:
                answer, demo_mode = _chat_answer(
                    history,
                    message,
                    language,
                    subject=subject or None,
                    context=f"Student class: {g.user.class_name}"
                )
                if demo_mode:
                    flash(
                        (
                            "DEMO MODE ಸಕ್ರಿಯವಾಗಿದೆ. ಇದು ಮಾದರಿ ಉತ್ತರ, ಲೈವ್ AI ಉತ್ತರ ಅಲ್ಲ."
                            if language == "kn"
                            else "DEMO MODE is enabled. This is a sample response, not live AI."
                        ),
                        "warning"
                    )

                existing = (
                    DoubtLog.query
                    .filter_by(student_id=g.user.id, question=message)
                    .first()
                )
                if existing is None:
                    db.session.add(
                        DoubtLog(
                            student_id=g.user.id,
                            subject=subject or None,
                            topic=message[:60],
                            question=message
                        )
                    )
                    db.session.commit()
                else:
                    db.session.rollback()

                history.append({"role": "user", "content": message})
                history.append({"role": "assistant", "content": answer})
                session["doubt_history"] = history[-20:]

            except AIError as exc:
                db.session.rollback()
                current_app.logger.warning("AI doubt chat rejected: %s", exc)
                flash(
                    "The external AI service is unavailable right now. Please try again later.",
                    "error"
                )
            except Exception:
                db.session.rollback()
                current_app.logger.exception("AI doubt chat error")
                flash("Sorry, something went wrong. Please try again.", "error")

        return redirect(url_for("ai.doubt"))

    return render_template(
        "student/doubt.html",
        history=history,
        selected_language=selected_language,
        selected_subject=selected_subject,
        subjects=SUBJECTS
    )


@bp.route("/student/doubt/clear", methods=["POST"])
@role_required("student")
def clear_doubt():
    session.pop("doubt_history", None)
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

        image_bytes = image.read(5 * 1024 * 1024 + 1)
        detected_mime = None

        if len(image_bytes) > 5 * 1024 * 1024:
            flash("Image size must be under 5 MB.", "error")
        else:
            detected_mime = _detect_image_mime(image_bytes)
            if detected_mime is None:
                flash("Please upload a valid JPG, PNG, or WEBP image.", "error")
            elif _rate_limited(g.user.id):
                flash("Too many requests. Please try again later.", "error")
            else:
                try:
                    result = explain_image(
                        image_bytes,
                        detected_mime,
                        language=language
                    )
                    session["doubt_language"] = language
                except AIError as exc:
                    current_app.logger.warning("AI image explanation rejected: %s", exc)
                    flash(
                        "The external AI service is unavailable right now. Please try again later.",
                        "error"
                    )
                except Exception:
                    current_app.logger.exception("AI image explanation error")
                    flash("Unable to process the image. Please try again.", "error")

    return render_template(
        "student/snap.html",
        result=result,
        selected_language=selected_language
    )