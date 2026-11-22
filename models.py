from datetime import datetime, timedelta
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)  # students: "6-14" (class-roll)
    name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(10), nullable=False)  # student | teacher | admin
    class_name = db.Column(db.String(10))            # "5", "6", "7" for students
    roll_no = db.Column(db.Integer)
    total_stars = db.Column(db.Integer, default=0)
    active = db.Column(db.Boolean, default=True)
    must_change_password = db.Column(db.Boolean, default=False)
    failed_attempts = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime)
    last_active = db.Column(db.DateTime)

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return check_password_hash(self.password_hash, raw)

    def is_locked(self):
        return self.locked_until is not None and self.locked_until > datetime.utcnow()


class Resource(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(20), nullable=False)  # Textbook | Notes | Worksheet
    class_name = db.Column(db.String(10), nullable=False)
    subject = db.Column(db.String(50))
    file_path = db.Column(db.String(300), nullable=False)
    uploaded_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)


class QuizResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    subject = db.Column(db.String(50))
    chapter = db.Column(db.String(150))
    score = db.Column(db.Integer, nullable=False)
    total = db.Column(db.Integer, nullable=False)
    taken_at = db.Column(db.DateTime, default=datetime.utcnow)


class DoubtLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    subject = db.Column(db.String(50))
    topic = db.Column(db.String(200))
    question = db.Column(db.Text)
    asked_at = db.Column(db.DateTime, default=datetime.utcnow)


class AiCall(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    called_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)