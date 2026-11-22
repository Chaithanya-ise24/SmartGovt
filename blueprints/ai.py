import time
from collections import defaultdict, deque

from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash, g, current_app)

from models import db, DoubtLog
from auth_utils import role_required
import services.ai_service as ai_service

bp = Blueprint("ai", __name__)

SUBJECTS = ["Science", "Mathematics", "Social Science", "English"]
MAX_CALLS_PER_HOUR = 20
_calls = defaultdict(deque)      # user_id -> timestamps (resets when the server restarts)
_histories = {}                  # user_id -> chat history kept on the server


def _rate_limited(user_id):
    now = time.time()
    q = _calls[user_id]
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= MAX_CALLS_PER_HOUR:
        return True
    q.append(now)
    return False


def _friendly(e):
    current_app.logger.error("AI error: %s", e)
    if type(e).__name__ == "AIError":
        return str(e)
    return "Sorry, the AI helper is busy right now. Please try again in a minute."


def _lang(value):
    return "kn" if value == "kn" else "en"


@bp.route("/student/doubt", methods=["GET", "POST"])
@role_required("student")
def doubt():
    history = _histories.setdefault(g.user.id, [])

    if request.method == "POST":
        message = request.form.get("message", "").strip()
        subject = request.form.get("subject", "").strip()
        subject = subject if subject in SUBJECTS else None
        language = _lang(request.form.get("language"))

        if not message:
            flash("Please enter your question.", "error")
        elif len(message) > 1000:
            flash("Please keep your question under 1000 characters.", "error")
        elif _rate_limited(g.user.id):
            flash("You have asked many questions. Please try again after some time.", "error")
        else:
            # Contract with ai_service: roles "user"/"model", key "text"
            api_history = [{"role": "model" if h["role"] == "assistant" else "user",
                            "text": h["content"]} for h in history[-10:]]
            try:
                answer = ai_service.chat_reply(api_history, message,
                                               language=language, subject=subject)
                history.append({"role": "user", "content": message})
                history.append({"role": "assistant", "content": answer})
                del history[:-20]                       # keep the latest 10 exchanges
                db.session.add(DoubtLog(student_id=g.user.id, subject=subject,
                                        topic=message[:60], question=message))
                db.session.commit()
            except Exception as e:
                flash(_friendly(e), "error")
        return redirect(url_for("ai.doubt"))

    return render_template("student/doubt.html", history=history)


@bp.route("/student/doubt/clear", methods=["POST"])
@role_required("student")
def clear_doubt():
    _histories.pop(g.user.id, None)
    return redirect(url_for("ai.doubt"))


def _looks_like_image(data, mimetype):
    if mimetype == "image/jpeg":
        return data[:3] == b"\xff\xd8\xff"
    if mimetype == "image/png":
        return data[:8] == b"\x89PNG\r\n\x1a\n"
    if mimetype == "image/webp":
        return data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return False


@bp.route("/student/snap", methods=["GET", "POST"])
@role_required("student")
def snap():
    result = None
    if request.method == "POST":
        image = request.files.get("image")
        language = _lang(request.form.get("language"))

        if not image or not image.filename:
            flash("Please select an image.", "error")
            return redirect(url_for("ai.snap"))

        data = image.read(5 * 1024 * 1024 + 1)
        if len(data) > 5 * 1024 * 1024:
            flash("Image size must be under 5 MB.", "error")
        elif not _looks_like_image(data, image.mimetype):
            flash("Please upload a real JPG, PNG or WEBP image.", "error")
        elif _rate_limited(g.user.id):
            flash("Too many requests. Please try again after some time.", "error")
        else:
            try:
                result = ai_service.explain_image(data, image.mimetype, language=language)
            except Exception as e:
                flash(_friendly(e), "error")

    return render_template("student/snap.html", result=result)