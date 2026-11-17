import csv
import io
import secrets

from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash, abort, current_app)

from models import db, User, QuizResult, DoubtLog
from auth_utils import admin_required

bp = Blueprint("admin", __name__)

VALID_CLASSES = {"5", "6", "7"}
MAX_CSV_ROWS = 500


def create_student(name, grade, roll):
    """Adds a student to the session. Returns False if the account already exists."""
    username = f"{grade}-{roll}"
    if User.query.filter_by(username=username).first():
        return False
    u = User(username=username, name=name, role="student",
             class_name=grade, roll_no=roll, must_change_password=True)
    u.set_password(current_app.config["DEFAULT_PIN"])
    db.session.add(u)
    return True


@bp.route("/admin/users")
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
                           default_pin=current_app.config["DEFAULT_PIN"])


@bp.route("/admin/users/add", methods=["POST"])
@admin_required
def admin_add_user():
    role = request.form.get("role")
    name = request.form.get("name", "").strip()
    if not name:
        flash("Name is required.", "error")
        return redirect(url_for("admin.admin_users"))

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
            flash(f"Student created: Class {grade}, Roll {roll}, PIN {current_app.config['DEFAULT_PIN']} "
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
    return redirect(url_for("admin.admin_users"))


@bp.route("/admin/users/import", methods=["POST"])
@admin_required
def admin_import_csv():
    file = request.files.get("csv_file")
    if not file or not file.filename.lower().endswith(".csv"):
        flash("Please upload a .csv file.", "error")
        return redirect(url_for("admin.admin_users"))

    try:
        reader = csv.DictReader(io.TextIOWrapper(file.stream, encoding="utf-8-sig"))
        reader.fieldnames = [h.strip().lower() for h in (reader.fieldnames or [])]
        if not {"name", "class", "roll"}.issubset(reader.fieldnames):
            flash("CSV must have the columns: name, class, roll.", "error")
            return redirect(url_for("admin.admin_users"))

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
        return redirect(url_for("admin.admin_users"))

    flash(f"Imported {created} students. Default PIN: {current_app.config['DEFAULT_PIN']}.", "success")
    if skipped:
        flash("Skipped: " + "; ".join(skipped[:10]) + ("..." if len(skipped) > 10 else ""), "error")
    return redirect(url_for("admin.admin_users"))


def _get_managed_user(uid):
    user = db.get_or_404(User, uid)
    if user.role == "admin":
        abort(403)          # the Headmaster account can't be changed from this screen
    return user


@bp.route("/admin/users/<int:uid>/reset", methods=["POST"])
@admin_required
def admin_reset_pin(uid):
    user = _get_managed_user(uid)
    if user.role == "student":
        user.set_password(current_app.config["DEFAULT_PIN"])
        msg = f"PIN for {user.name} reset to {current_app.config['DEFAULT_PIN']}."
    else:
        temp = secrets.token_urlsafe(8)
        user.set_password(temp)
        msg = f"Temporary password for {user.username}: {temp} (shown only once)."
    user.must_change_password = True
    user.failed_attempts = 0
    user.locked_until = None
    db.session.commit()
    flash(msg, "success")
    return redirect(request.referrer or url_for("admin.admin_users"))


@bp.route("/admin/users/<int:uid>/toggle", methods=["POST"])
@admin_required
def admin_toggle_user(uid):
    user = _get_managed_user(uid)
    user.active = not user.active
    db.session.commit()
    flash(f"{user.name} is now {'active' if user.active else 'deactivated'}.", "success")
    return redirect(request.referrer or url_for("admin.admin_users"))


@bp.route("/admin/users/<int:uid>/delete", methods=["POST"])
@admin_required
def admin_delete_user(uid):
    user = _get_managed_user(uid)
    name = user.name
    QuizResult.query.filter_by(student_id=user.id).delete()
    DoubtLog.query.filter_by(student_id=user.id).delete()
    db.session.delete(user)
    db.session.commit()
    flash(f"{name} and all their data were deleted.", "success")
    return redirect(request.referrer or url_for("admin.admin_users"))