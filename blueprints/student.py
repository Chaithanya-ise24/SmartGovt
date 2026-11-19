
from datetime import date, timedelta

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, g, session
)
from models import db, QuizResult, User
from auth_utils import role_required
from services.ai_service import generate_quiz
bp = Blueprint("student", __name__)
@bp.route("/student/quiz", methods=["GET", "POST"])
@role_required("student")
def quiz():
    if request.method == "POST":
        subject = request.form.get("subject")
        chapter = request.form.get("chapter")
        language = request.form.get("language", "en")

        if not subject or not chapter:
            flash("Please select a subject and enter a chapter.", "error")
            return redirect(url_for("student.quiz"))

        questions = generate_quiz(
            g.user.class_name,
            subject,
            chapter,
            language
        )

        session["active_quiz"] = {
            "subject": subject,
            "chapter": chapter,
            "questions": questions
        }

        # Hide correct answers before displaying questions
        display_questions = [
            {
                "question": q["question"],
                "options": q["options"]
            }
            for q in questions
        ]

        return render_template(
            "quiz_questions.html",
            questions=display_questions,
            subject=subject,
            chapter=chapter
        )

    return render_template("quiz.html")


@bp.route("/student/progress")
@role_required("student")
def progress():

    # Fetch only the logged-in student's quiz results
    quiz_history = (
        QuizResult.query
        .filter_by(student_id=g.user.id)
        .order_by(QuizResult.taken_at.desc())
        .all()
    )

    quiz_count = len(quiz_history)

    # Calculate average score as a percentage
    total_score = sum(quiz.score for quiz in quiz_history)
    total_questions = sum(quiz.total for quiz in quiz_history)

    average_score = (
        round((total_score / total_questions) * 100)
        if total_questions > 0 else 0
    )

    # Calculate consecutive-day learning streak
    active_dates = {
        quiz.taken_at.date()
        for quiz in quiz_history
        if quiz.taken_at
    }

    today = date.today()
    current_day = today if today in active_dates else today - timedelta(days=1)

    streak = 0
    while current_day in active_dates:
        streak += 1
        current_day -= timedelta(days=1)

    # Unlock achievements
    badges = []

    if any(quiz.subject and quiz.subject.lower() == "science"
           for quiz in quiz_history):
        badges.append("Science Explorer")

    if any(quiz.total > 0 and quiz.score == quiz.total
           for quiz in quiz_history):
        badges.append("Quiz Master")

    return render_template(
        "student/progress.html",
        quiz_count=quiz_count,
        average_score=average_score,
        streak=streak,
        badges=badges,
        quiz_history=quiz_history
    )
@bp.route("/student/flashcards")
@role_required("student")
def flashcards():
    return render_template("student/flashcards.html")

@bp.route("/student/quiz/submit", methods=["POST"])
@role_required("student")
def submit_quiz():

    quiz_data = session.get("active_quiz")

    if not quiz_data:
        flash("Your quiz session has expired. Please start again.", "error")
        return redirect(url_for("student.quiz"))

    questions = quiz_data["questions"]
    score = 0

    for i, question in enumerate(questions):
        selected_answer = request.form.get(f"q{i + 1}")

        if selected_answer is not None:
            try:
                if int(selected_answer) == question["answer_index"]:
                    score += 1
            except (ValueError, TypeError):
                pass

    total = len(questions)

    # Save quiz result
    result = QuizResult(
        student_id=g.user.id,
        subject=quiz_data["subject"],
        chapter=quiz_data["chapter"],
        score=score,
        total=total
    )

    # Award one star per correct answer
    g.user.total_stars = (g.user.total_stars or 0) + score

    db.session.add(result)
    db.session.commit()

    # Clear completed quiz from session
    session.pop("active_quiz", None)

    return render_template(
        "quiz_result.html",
        score=score,
        total=total,
        stars_earned=score
    )
