import time

from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash, g, current_app)

from models import db, QuizResult
from auth_utils import role_required
from services.ai_service import generate_quiz
from services.stats import compute_streak

bp = Blueprint("student", __name__)

SUBJECTS = ["Science", "Mathematics", "Social Science", "English"]
QUIZ_TTL = 30 * 60                      # a quiz must be submitted within 30 minutes
_active_quizzes = {}                    # user_id -> quiz kept on the SERVER, never in the cookie


def _cleanup():
    now = time.time()
    for uid in [u for u, q in _active_quizzes.items() if now - q["created"] > QUIZ_TTL]:
        _active_quizzes.pop(uid, None)


@bp.route("/student/quiz", methods=["GET", "POST"])
@role_required("student")
def quiz():
    if request.method == "POST":
        subject = request.form.get("subject", "")
        chapter = request.form.get("chapter", "").strip()[:150]
        language = "kn" if request.form.get("language") == "kn" else "en"

        if subject not in SUBJECTS or not chapter:
            flash("Please select a subject and enter a chapter.", "error")
            return redirect(url_for("student.quiz"))

        try:
            questions = generate_quiz(g.user.class_name, subject, chapter, language)
        except Exception as e:
            current_app.logger.error("Quiz generation failed: %s", e)
            msg = str(e) if type(e).__name__ == "AIError" else \
                "The quiz helper is busy right now. Please try again in a minute."
            flash(msg, "error")
            return redirect(url_for("student.quiz"))

        _cleanup()
        _active_quizzes[g.user.id] = {"subject": subject, "chapter": chapter,
                                      "questions": questions, "created": time.time()}

        # Correct answers never leave the server
        display = [{"question": q["question"], "options": q["options"]} for q in questions]
        return render_template("quiz_questions.html", questions=display,
                               subject=subject, chapter=chapter)

    return render_template("quiz.html")


@bp.route("/student/quiz/submit", methods=["POST"])
@role_required("student")
def submit_quiz():
    _cleanup()
    quiz_data = _active_quizzes.pop(g.user.id, None)   # pop = a quiz can be submitted only once
    if not quiz_data:
        flash("Your quiz has expired. Please start again.", "error")
        return redirect(url_for("student.quiz"))

    questions = quiz_data["questions"]
    score = 0
    for i, q in enumerate(questions):
        try:
            if int(request.form.get(f"q{i + 1}", "")) == q["answer_index"]:
                score += 1
        except (ValueError, TypeError):
            pass

    db.session.add(QuizResult(student_id=g.user.id, subject=quiz_data["subject"],
                              chapter=quiz_data["chapter"], score=score,
                              total=len(questions)))
    g.user.total_stars = (g.user.total_stars or 0) + score
    db.session.commit()

    return render_template("quiz_result.html", score=score,
                           total=len(questions), stars_earned=score)


@bp.route("/student/progress")
@role_required("student")
def progress():
    history = (QuizResult.query.filter_by(student_id=g.user.id)
               .order_by(QuizResult.taken_at.desc()).all())

    total_score = sum(r.score for r in history)
    total_questions = sum(r.total for r in history)
    average = round(total_score / total_questions * 100) if total_questions else 0

    badges = []
    if any(r.subject and r.subject.lower() == "science" for r in history):
        badges.append("Science Explorer")
    if any(r.total > 0 and r.score == r.total for r in history):
        badges.append("Quiz Master")

    return render_template("student/progress.html", quiz_count=len(history),
                           average_score=average, streak=compute_streak(g.user.id),
                           badges=badges, quiz_history=history)


@bp.route("/student/flashcards")
@role_required("student")
def flashcards():
    return render_template("student/flashcards.html")