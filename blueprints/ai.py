
from flask import (
    Blueprint, render_template, request,
    redirect, url_for, flash, g, session
)

from auth_utils import role_required
from services.ai_service import chat_reply, explain_image

bp = Blueprint("ai", __name__)


@bp.route("/student/doubt", methods=["GET", "POST"])
@role_required("student")
def doubt():
    history = session.get("doubt_history", [])

    if request.method == "POST":
        message = request.form.get("message", "").strip()
        subject = request.form.get("subject", "").strip() or None
        language = request.form.get("language", "en")

        if not message:
            flash("Please enter your question.", "error")
            return redirect(url_for("ai.doubt"))

        if len(message) > 1000:
            flash("Please keep your question under 1000 characters.", "error")
            return redirect(url_for("ai.doubt"))

        try:
            answer = chat_reply(
                history,
                message,
                language=language,
                subject=subject,
                context=f"Student class: {g.user.class_name}"
            )

            history.append({"role": "user", "content": message})
            history.append({"role": "assistant", "content": answer})

            # Keep the latest 10 exchanges
            session["doubt_history"] = history[-20:]

        except Exception:
            flash("Sorry, something went wrong. Please try again.", "error")

        return redirect(url_for("ai.doubt"))

    return render_template(
        "student/doubt.html",
        history=history
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

    if request.method == "POST":
        image = request.files.get("image")
        language = request.form.get("language", "en")

        if not image or not image.filename:
            flash("Please select an image.", "error")
            return redirect(url_for("ai.snap"))

        allowed_types = ["image/jpeg", "image/png", "image/webp"]

        if image.mimetype not in allowed_types:
            flash("Please upload a JPG, PNG, or WEBP image.", "error")
            return redirect(url_for("ai.snap"))

        image_bytes = image.read(5 * 1024 * 1024 + 1)

        if len(image_bytes) > 5 * 1024 * 1024:
            flash("Image size must be under 5 MB.", "error")
            return redirect(url_for("ai.snap"))

        try:
            result = explain_image(
                image_bytes,
                image.mimetype,
                language=language
            )
        except Exception:
            flash("Unable to process the image. Please try again.", "error")

    return render_template(
        "student/snap.html",
        result=result
    )
