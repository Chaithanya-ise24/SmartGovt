import random
from datetime import datetime, timedelta
from app import app
from models import db, User, QuizResult

NAMES = {"5": ["Asha", "Ravi", "Meena"], "6": ["Kiran", "Divya", "Arjun"], "7": ["Sneha", "Manoj", "Latha"]}

with app.app_context():
    for grade, names in NAMES.items():
        for roll, name in enumerate(names, start=1):
            if User.query.filter_by(username=f"{grade}-{roll}").first():
                continue
            u = User(username=f"{grade}-{roll}", name=name, role="student",
                     class_name=grade, roll_no=roll, must_change_password=True)
            u.set_password("1234")
            db.session.add(u)
    db.session.commit()

    for u in User.query.filter_by(role="student").all():
        if QuizResult.query.filter_by(student_id=u.id).count():
            continue
        stars = 0
        for d in range(random.randint(1, 4)):
            s = random.randint(2, 5)
            stars += s
            db.session.add(QuizResult(student_id=u.id,
                                      subject=random.choice(["Science", "Mathematics", "Social Science", "English"]),
                                      chapter="Demo chapter", score=s, total=5,
                                      taken_at=datetime.utcnow() - timedelta(days=d)))
        u.total_stars = stars
    db.session.commit()
    print("Demo data ready. Students log in with PIN 1234, then set a new PIN.")