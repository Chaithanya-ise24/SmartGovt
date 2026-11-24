from datetime import datetime, timedelta

from models import QuizResult

IST = timedelta(hours=5, minutes=30)


def compute_streak(student_id):
    rows = (QuizResult.query.filter_by(student_id=student_id)
            .with_entities(QuizResult.taken_at).all())
    days = {(r[0] + IST).date() for r in rows if r[0]}
    day = (datetime.utcnow() + IST).date()
    if day not in days:
        day -= timedelta(days=1)
    streak = 0
    while day in days:
        streak += 1
        day -= timedelta(days=1)
    return streak