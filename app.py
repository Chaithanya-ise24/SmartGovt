import csv
import io
import secrets
from datetime import datetime, timedelta
from functools import wraps

from flask import (Flask, g, jsonify, render_template, request, redirect,
                   url_for, session, flash, abort)
from sqlalchemy import event, func, select

from config import Config
from models import AiCall, db, User, QuizResult, DoubtLog
from services.ai_service import chat_reply

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

# ---------- SQLite WAL mode ----------
with app.app_context():
    @event.listens_for(db.engine, "connect")
    def set_sqlite_pragma(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.close()


# ---------- Seed admin ----------
def init_db():
    db.create_all()
    if not User.query.filter_by(role="admin").first():
        admin = User(username=app.config["ADMIN_USERNAME"], name="Headmaster", role="admin")
        admin.set_password(app.config["ADMIN_PASSWORD"])
        db.session.add(admin)
        db.session.commit()
        print("Admin account created.")

with app.app_context():
    init_db()


# ---------- Access control ----------
@app.before_request
def load_user():
    g.user = None
    uid = session.get("user_id")
    if uid:
        user = db.session.get(User, uid)
        if user and user.active:
            g.user = user
        else:
            session.clear()


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("login"))
        if g.user.must_change_password and request.endpoint != "change_password":
            return redirect(url_for("change_password"))
        return f(*args, **kwargs)
    return wrapper


def role_required(*roles):
    def decorator(f):
        @wraps(f)
        @login_required
        def wrapper(*args, **kwargs):
            if g.user.role not in roles:
                abort(403)
            return f(*args, **kwargs)
        return wrapper
    return decorator

teacher_required = role_required("teacher", "admin")
admin_required = role_required("admin")


# ---------- Auth routes ----------
def attempt_login(user, secret):
    """Returns (ok, error_message). Handles lockout."""
    if user is None or not user.active:
        return False, "Invalid login details."
    if user.is_locked():
        return False, "Too many wrong attempts. Please wait a few minutes."
    if user.check_password(secret):
        user.failed_attempts = 0
        user.locked_until = None
        user.last_active = datetime.utcnow()
        db.session.commit()
        return True, None
    user.failed_attempts += 1
    if user.failed_attempts >= app.config["MAX_FAILED_LOGINS"]:
        user.locked_until = datetime.utcnow() + timedelta(minutes=app.config["LOCKOUT_MINUTES"])
        user.failed_attempts = 0
    db.session.commit()
    return False, "Invalid login details."


@app.route("/")
def index():
    if g.user:
        return redirect(url_for("home"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        login_type = request.form.get("login_type")
        if login_type == "student":
            grade = request.form.get("grade", "").strip()
            roll = request.form.get("roll", "").strip()
            pin = request.form.get("pin", "").strip()
            user = User.query.filter_by(username=f"{grade}-{roll}", role="student").first()
            ok, err = attempt_login(user, pin)
        else:
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            user = User.query.filter(User.username == username,
                                     User.role.in_(["teacher", "admin"])).first()
            ok, err = attempt_login(user, password)

        if ok:
            session.clear()
            session["user_id"] = user.id
            return redirect(url_for("home"))
        flash(err, "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        new = request.form.get("new_secret", "")
        confirm = request.form.get("confirm_secret", "")
        if g.user.role == "student":
            valid = new.isdigit() and len(new) == 4 and new != app.config["DEFAULT_PIN"]
            msg = "PIN must be 4 digits and not 1234."
        else:
            valid = len(new) >= 8
            msg = "Password must be at least 8 characters."
        if not valid:
            flash(msg, "error")
        elif new != confirm:
            flash("Entries do not match.", "error")
        else:
            g.user.set_password(new)
            g.user.must_change_password = False
            db.session.commit()
            return redirect(url_for("home"))
    return render_template("change_password.html")


# ---------- Role landing pages ----------
@app.route("/home")
@login_required
def home():
    return redirect(url_for({"student": "student_home",
                             "teacher": "teacher_home",
                             "admin": "admin_home"}[g.user.role]))

@app.route("/student")
@role_required("student")
def student_home():
    return render_template("dashboard.html", title="Student Dashboard")

@app.route("/student/chat")
@role_required("student")
def student_chat():
    return render_template("student/chat.html")


def reserve_ai_call(student_id):
    cutoff = datetime.utcnow() - timedelta(hours=1)
    with db.engine.connect() as conn:
        try:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            count = conn.execute(
                select(func.count()).select_from(AiCall).where(
                    AiCall.student_id == student_id,
                    AiCall.called_at >= cutoff,
                )
            ).scalar_one()
            if count >= app.config["AI_CALLS_PER_HOUR"]:
                conn.rollback()
                return False
            conn.execute(AiCall.__table__.insert().values(
                student_id=student_id,
                called_at=datetime.utcnow(),
            ))
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise


def _log_doubt_and_reserve_call(student_id, subject, topic, question, reserve_call=True):
    cutoff = datetime.utcnow() - timedelta(hours=1)
    with db.engine.connect() as conn:
        try:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            count = conn.execute(
                select(func.count()).select_from(AiCall).where(
                    AiCall.student_id == student_id,
                    AiCall.called_at >= cutoff,
                )
            ).scalar_one()
            conn.execute(DoubtLog.__table__.insert().values(
                student_id=student_id,
                subject=subject,
                topic=topic,
                question=question,
                asked_at=datetime.utcnow(),
            ))
            allowed = not reserve_call or count < app.config["AI_CALLS_PER_HOUR"]
            if reserve_call and allowed:
                conn.execute(AiCall.__table__.insert().values(
                    student_id=student_id,
                    called_at=datetime.utcnow(),
                ))
            conn.commit()
            return allowed
        except Exception:
            conn.rollback()
            raise


@app.route("/api/chat", methods=["POST"])
def student_chat_api():
    if g.user is None:
        return jsonify(error="Please log in to use the chat."), 401
    if g.user.role != "student":
        return jsonify(error="Student access is required."), 403
    if g.user.must_change_password:
        return jsonify(error="Please change your PIN before using the chat."), 403
    if not request.is_json:
        return jsonify(error="Send your question as JSON."), 400

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="The chat request is not valid."), 400
    question = data.get("question")
    if not isinstance(question, str) or not question.strip() or len(question) > 2000:
        return jsonify(error="Enter a question of 1 to 2000 characters."), 400
    question = question.strip()
    language = data.get("language", "en")
    if language not in ("en", "kn"):
        return jsonify(error="Choose English or Kannada."), 400

    subject = data.get("subject", "")
    topic = data.get("topic", "")
    subject = subject.strip()[:50] if isinstance(subject, str) else ""
    topic = topic.strip()[:200] if isinstance(topic, str) else ""

    raw_history = data.get("history", [])
    if not isinstance(raw_history, list):
        return jsonify(error="The conversation history is not valid."), 400
    history = []
    for turn in raw_history[-10:]:
        if not isinstance(turn, dict):
            continue
        previous_question = turn.get("question")
        previous_answer = turn.get("answer")
        if (isinstance(previous_question, str) and isinstance(previous_answer, str)):
            history.append({
                "question": previous_question[:2000],
                "answer": previous_answer[:4000],
            })

    has_api_key = bool(app.config.get("GEMINI_API_KEY"))
    try:
        allowed = _log_doubt_and_reserve_call(
            g.user.id, subject, topic, question, reserve_call=has_api_key
        )
    except Exception:
        app.logger.exception("Could not record a student chat request.")
        return jsonify(error="Your question could not be saved. Please try again."), 503
    if not has_api_key:
        return jsonify(error="The chat service is not configured yet. Please ask your teacher for help."), 503
    if not allowed:
        return jsonify(error="You have reached the limit of 20 AI questions per hour. Please try again later."), 429

    try:
        answer = chat_reply(question, history=history, language=language)
    except Exception:
        app.logger.exception("Gemini chat request failed for student %s.", g.user.id)
        return jsonify(error="Sorry, I couldn't get an answer right now. Please try again in a moment."), 503
    return jsonify(answer=answer)


@app.route("/teacher")
@teacher_required
def teacher_home():
    return render_template("dashboard.html", title="Teacher Dashboard")

@app.route("/admin")
@admin_required
def admin_home():
    return render_template("dashboard.html", title="Headmaster Dashboard")


# ---------- Headmaster: user management (Phase 3) ----------
VALID_CLASSES = {"5", "6", "7"}
MAX_CSV_ROWS = 500


def create_student(name, grade, roll):
    """Adds a student to the session. Returns False if the account already exists."""
    username = f"{grade}-{roll}"
    if User.query.filter_by(username=username).first():
        return False
    u = User(username=username, name=name, role="student",
             class_name=grade, roll_no=roll, must_change_password=True)
    u.set_password(app.config["DEFAULT_PIN"])
    db.session.add(u)
    return True


@app.route("/admin/users")
@admin_required
def admin_users():
    role = request.args.get("role", "")
    grade = request.args.get("grade", "")
    q = request.args.get("q", "").strip()

    query = User.query.filter(User.role != "admin")
    if role in ("student", "teacher"):
        query = query.filter_by(role=role)
    if grade in VALID_CLASSES:
        query = query.filter_by(class_name=grade)
    if q:
        query = query.filter(User.name.ilike(f"%{q}%"))
    users = query.order_by(User.role, User.class_name, User.roll_no, User.name).all()
    return render_template("admin/users.html", users=users,
                           role=role, grade=grade, q=q,
                           default_pin=app.config["DEFAULT_PIN"])


@app.route("/admin/users/add", methods=["POST"])
@admin_required
def admin_add_user():
    role = request.form.get("role")
    name = request.form.get("name", "").strip()
    if not name:
        flash("Name is required.", "error")
        return redirect(url_for("admin_users"))

    if role == "student":
        grade = request.form.get("grade", "")
        try:
            roll = int(request.form.get("roll", ""))
        except ValueError:
            roll = 0
        if grade not in VALID_CLASSES or roll < 1:
            flash("Choose a class (5, 6 or 7) and a valid roll number.", "error")
        elif create_student(name, grade, roll):
            db.session.commit()
            flash(f"Student created: Class {grade}, Roll {roll}, PIN {app.config['DEFAULT_PIN']} "
                  f"(they must change it at first login).", "success")
        else:
            flash(f"Class {grade}, Roll {roll} already exists.", "error")

    elif role == "teacher":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not username or len(password) < 8:
            flash("Teacher needs a username and a password of at least 8 characters.", "error")
        elif User.query.filter_by(username=username).first():
            flash("That username is already taken.", "error")
        else:
            t = User(username=username, name=name, role="teacher", must_change_password=True)
            t.set_password(password)
            db.session.add(t)
            db.session.commit()
            flash(f"Teacher '{username}' created. They must change the password at first login.", "success")
    else:
        flash("Invalid role.", "error")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/import", methods=["POST"])
@admin_required
def admin_import_csv():
    file = request.files.get("csv_file")
    if not file or not file.filename.lower().endswith(".csv"):
        flash("Please upload a .csv file.", "error")
        return redirect(url_for("admin_users"))

    try:
        reader = csv.DictReader(io.TextIOWrapper(file.stream, encoding="utf-8-sig"))
        reader.fieldnames = [h.strip().lower() for h in (reader.fieldnames or [])]
        if not {"name", "class", "roll"}.issubset(reader.fieldnames):
            flash("CSV must have the columns: name, class, roll.", "error")
            return redirect(url_for("admin_users"))

        created, skipped = 0, []
        for i, row in enumerate(reader, start=2):
            if i > MAX_CSV_ROWS + 1:
                skipped.append("file truncated at 500 rows")
                break
            name = (row.get("name") or "").strip()
            grade = (row.get("class") or "").strip()
            try:
                roll = int((row.get("roll") or "").strip())
            except ValueError:
                roll = 0
            if not name or grade not in VALID_CLASSES or roll < 1:
                skipped.append(f"row {i}: invalid data")
            elif create_student(name, grade, roll):
                created += 1
            else:
                skipped.append(f"row {i}: {grade}-{roll} already exists")
        db.session.commit()
    except UnicodeDecodeError:
        db.session.rollback()
        flash("Could not read the file. Save it as CSV UTF-8 and try again.", "error")
        return redirect(url_for("admin_users"))

    flash(f"Imported {created} students. Default PIN: {app.config['DEFAULT_PIN']}.", "success")
    if skipped:
        flash("Skipped: " + "; ".join(skipped[:10]) + ("..." if len(skipped) > 10 else ""), "error")
    return redirect(url_for("admin_users"))


def _get_managed_user(uid):
    user = db.get_or_404(User, uid)
    if user.role == "admin":
        abort(403)          # the Headmaster account can't be changed from this screen
    return user


@app.route("/admin/users/<int:uid>/reset", methods=["POST"])
@admin_required
def admin_reset_pin(uid):
    user = _get_managed_user(uid)
    if user.role == "student":
        user.set_password(app.config["DEFAULT_PIN"])
        msg = f"PIN for {user.name} reset to {app.config['DEFAULT_PIN']}."
    else:
        temp = secrets.token_urlsafe(8)
        user.set_password(temp)
        msg = f"Temporary password for {user.username}: {temp} (shown only once)."
    user.must_change_password = True
    user.failed_attempts = 0
    user.locked_until = None
    db.session.commit()
    flash(msg, "success")
    return redirect(request.referrer or url_for("admin_users"))


@app.route("/admin/users/<int:uid>/toggle", methods=["POST"])
@admin_required
def admin_toggle_user(uid):
    user = _get_managed_user(uid)
    user.active = not user.active
    db.session.commit()
    flash(f"{user.name} is now {'active' if user.active else 'deactivated'}.", "success")
    return redirect(request.referrer or url_for("admin_users"))


@app.route("/admin/users/<int:uid>/delete", methods=["POST"])
@admin_required
def admin_delete_user(uid):
    user = _get_managed_user(uid)
    name = user.name
    QuizResult.query.filter_by(student_id=user.id).delete()
    DoubtLog.query.filter_by(student_id=user.id).delete()
    AiCall.query.filter_by(student_id=user.id).delete()
    db.session.delete(user)
    db.session.commit()
    flash(f"{name} and all their data were deleted.", "success")
    return redirect(request.referrer or url_for("admin_users"))


@app.errorhandler(403)
def forbidden(_):
    return render_template("dashboard.html", title="403 - Access Denied"), 403


if __name__ == "__main__":
    app.run(debug=True)