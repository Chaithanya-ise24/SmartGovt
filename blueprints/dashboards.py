from flask import Blueprint, render_template
from sqlalchemy import func

from models import db, User, QuizResult, DoubtLog, Resource
from auth_utils import teacher_required

bp = Blueprint("dashboards", __name__)


@bp.route("/teacher/analytics")
@teacher_required
def analytics():
    classes = []
    for c in ("5", "6", "7"):
        students = User.query.filter_by(role="student", class_name=c, active=True).count()
        quizzes, score, total = (
            db.session.query(func.count(QuizResult.id),
                             func.coalesce(func.sum(QuizResult.score), 0),
                             func.coalesce(func.sum(QuizResult.total), 0))
            .select_from(QuizResult)
            .join(User, User.id == QuizResult.student_id)
            .filter(User.class_name == c).one())
        doubts = (db.session.query(func.count(DoubtLog.id)).select_from(DoubtLog)
                  .join(User, User.id == DoubtLog.student_id)
                  .filter(User.class_name == c).scalar())
        classes.append({
            "name": c, "students": students, "quizzes": quizzes,
            "avg": round(score / total * 100) if total else 0,
            "doubts": doubts or 0,
            "docs": Resource.query.filter_by(class_name=c).count()})

    subject_rows = (db.session.query(QuizResult.subject, func.sum(QuizResult.score),
                                     func.sum(QuizResult.total))
                    .group_by(QuizResult.subject).all())
    subjects = [{"name": s or "-", "avg": round(a / b * 100) if b else 0}
                for s, a, b in subject_rows]

    top = (User.query.filter_by(role="student", active=True)
           .order_by(User.total_stars.desc()).limit(5).all())
    recent = (db.session.query(DoubtLog, User).join(User, User.id == DoubtLog.student_id)
              .order_by(DoubtLog.asked_at.desc()).limit(8).all())
    return render_template("teacher/analytics.html", classes=classes,
                           subjects=subjects, top=top, recent=recent)