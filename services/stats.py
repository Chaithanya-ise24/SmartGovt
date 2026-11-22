from datetime import datetime, timedelta

from models import QuizResult

IST = timedelta(hours=5, minutes=30)   # school is in India; stored times are UTC


def compute_streak(student_id):
    """Consecutive days (ending today or yesterday) with at least one quiz."""
    rows = (QuizResult.query.filter_by(student_id=student_id)
            .with_entities(QuizResult.taken_at).all())
    days = {(r[0] + IST).date() for r in rows if r[0]}
    today = (datetime.utcnow() + IST).date()
    day = today if today in days else today - timedelta(days=1)
    streak = 0
    while day in days:
        streak += 1
        day -= timedelta(days=1)
    return streak