from datetime import datetime, timedelta

from flask import (Blueprint, render_template, request, redirect,
                   url_for, session, flash, g, current_app)

from models import db, User
from auth_utils import login_required, role_required, teacher_required, admin_required

bp = Blueprint("auth", __name__)


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
    if user.failed_attempts >= current_app.config["MAX_FAILED_LOGINS"]:
        user.locked_until = datetime.utcnow() + timedelta(minutes=current_app.config["LOCKOUT_MINUTES"])
        user.failed_attempts = 0
    db.session.commit()
    return False, "Invalid login details."


@bp.route("/")
def index():
    if g.user:
        return redirect(url_for("auth.home"))
    return redirect(url_for("auth.login"))


@bp.route("/login", methods=["GET", "POST"])
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
            return redirect(url_for("auth.home"))
        flash(err, "error")
    return render_template("login.html")


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        new = request.form.get("new_secret", "")
        confirm = request.form.get("confirm_secret", "")
        if g.user.role == "student":
            valid = new.isdigit() and len(new) == 4 and new != current_app.config["DEFAULT_PIN"]
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
            return redirect(url_for("auth.home"))
    return render_template("change_password.html")


# ---------- Role landing pages (Member B will later move /student into student.py) ----------
@bp.route("/home")
@login_required
def home():
    return redirect(url_for({"student": "auth.student_home",
                             "teacher": "auth.teacher_home",
                             "admin": "auth.admin_home"}[g.user.role]))


@bp.route("/student")
@role_required("student")
def student_home():
    return render_template("dashboard.html", title="Student Dashboard")


@bp.route("/teacher")
@teacher_required
def teacher_home():
    return render_template("dashboard.html", title="Teacher Dashboard")


@bp.route("/admin")
@admin_required
def admin_home():
    return render_template("dashboard.html", title="Headmaster Dashboard")