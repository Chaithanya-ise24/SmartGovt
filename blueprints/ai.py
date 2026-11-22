import time
from collections import defaultdict, deque

from flask import (
    Blueprint, render_template, request,
    redirect, url_for, flash, g, session, current_app
)

from auth_utils import role_required
from models import db, DoubtLog
from services.ai_service import chat_reply, explain_image

bp = Blueprint("ai", __name__)

SUBJECTS = ["Science", "Mathematics", "Social Science", "English"]
MAX_CALLS_PER_HOUR = 20
_calls = defaultdict(deque)


def _rate_limited(user_id):
    now = time.time()
    calls = _calls[user_id]

    while calls and now - calls[0] > 3600:
        calls.popleft()

    if len(calls) >= MAX_CALLS_PER_HOUR:
        return True

    calls.append(now)
    return False


def _lang(value):
    return "kn" if value == "kn" else "en"


def _looks_like_image(data, mimetype):
    if mimetype == "image/jpeg":
        return data[:3] == b"\xff\xd8\xff"
    if mimetype == "image/png":
        return data[:8] == b"\x89PNG\r\n\x1a\n"
    if mimetype == "image/webp":
        return data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return False


@bp.route("/student/doubt", methods=["GET", "POST"])
@role_required("student")
def doubt():
    history = session.get("doubt_history", [])

    if request.method == "POST":
        message = request.form.get("message", "").strip()
        subject = request.form.get("subject", "").strip()
        subject = subject if subject in SUBJECTS else None
        language = _lang(request.form.get("language", "en"))

        if not message:
            flash("Please enter your question.", "error")
        elif len(message) > 1000:
            flash("Please keep your question under 1000 characters.", "error")
        elif _rate_limited(g.user.id):
            flash("You have asked many questions. Please try again later.", "error")
        else:
            try:
                answer = chat_reply(
                    history,
                    message,
                    language=language,
                    subject=subject,
                    context=f"Student class: {g.user.class_name}"
                )

                db.session.add(
                    DoubtLog(
                        student_id=g.user.id,
                        subject=subject,
                        topic=message[:60],
                        question=message
                    )
                )
                db.session.commit()

                history.append({"role": "user", "content": message})
                history.append({"role": "assistant", "content": answer})
                session["doubt_history"] = history[-20:]

            except Exception:
                db.session.rollback()
                current_app.logger.exception("AI doubt chat error")
                flash("Sorry, something went wrong. Please try again.", "error")

        return redirect(url_for("ai.doubt"))

    return render_template("student/doubt.html", history=history)


@bp.route("/student/doubt/clear", methods=["POST"])
@role_required("student")
def clear_doubt():
    session.pop("doubt_history", None)
    return redirect(url_for("ai.doubt"))


@bp.route("/student/snap", methods=["GET", "POST"])
@role_required("student")
def snap():
    result = None

    if request.method == "POST":
        image = request.files.get("image")
        language = _lang(request.form.get("language", "en"))

        if not image or not image.filename:
            flash("Please select an image.", "error")
            return redirect(url_for("ai.snap"))

        image_bytes = image.read(5 * 1024 * 1024 + 1)

        if len(image_bytes) > 5 * 1024 * 1024:
            flash("Image size must be under 5 MB.", "error")
        elif not _looks_like_image(image_bytes, image.mimetype):
            flash("Please upload a valid JPG, PNG, or WEBP image.", "error")
        elif _rate_limited(g.user.id):
            flash("Too many requests. Please try again later.", "error")
        else:
            try:
                result = explain_image(
                    image_bytes,
                    image.mimetype,
                    language=language
                )
            except Exception:
                current_app.logger.exception("AI image explanation error")
                flash("Unable to process the image. Please try again.", "error")

    return render_template("student/snap.html", result=result)