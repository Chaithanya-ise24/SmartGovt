import os
import secrets

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, abort, g, current_app, send_from_directory)
from werkzeug.utils import secure_filename

from models import db, User, Resource
from auth_utils import login_required, role_required, teacher_required

bp = Blueprint("library", __name__)

CATEGORIES = ["Textbook", "Notes", "Worksheet"]
CLASSES = ["5", "6", "7"]
SUBJECTS = ["Science", "Social Studies", "Mathematics", "English"]


def _folder():
    folder = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(folder, exist_ok=True)
    return folder


def _get_openable(rid):
    res = db.get_or_404(Resource, rid)
    if g.user.role == "student" and res.class_name != g.user.class_name:
        abort(403)
    return res


# ---------- Student ----------
@bp.route("/student/library")
@role_required("student")
def student_library():
    subject = request.args.get("subject", "")
    category = request.args.get("category", "")
    query = Resource.query.filter_by(class_name=g.user.class_name)
    if subject in SUBJECTS:
        query = query.filter_by(subject=subject)
    if category in CATEGORIES:
        query = query.filter_by(category=category)
    files = query.order_by(Resource.category, Resource.title).all()
    return render_template("student/library.html", files=files, subject=subject,
                           category=category, subjects=SUBJECTS, categories=CATEGORIES)


# ---------- Viewer and file access ----------
@bp.route("/library/<int:rid>")
@login_required
def view_page(rid):
    res = _get_openable(rid)
    back = "library.student_library" if g.user.role == "student" else "library.documents"
    return render_template("library_view.html", res=res, back=back)


@bp.route("/library/<int:rid>/file")
@login_required
def file_inline(rid):
    res = _get_openable(rid)
    return send_from_directory(_folder(), res.file_path, mimetype="application/pdf")


@bp.route("/library/<int:rid>/download")
@login_required
def file_download(rid):
    res = _get_openable(rid)
    name = secure_filename(res.title) or "document"
    return send_from_directory(_folder(), res.file_path, mimetype="application/pdf",
                               as_attachment=True, download_name=f"{name}.pdf")


# ---------- Teacher / Headmaster ----------
@bp.route("/teacher/documents")
@teacher_required
def documents():
    grade = request.args.get("grade", "")
    query = Resource.query
    if grade in CLASSES:
        query = query.filter_by(class_name=grade)
    files = query.order_by(Resource.class_name, Resource.category, Resource.title).all()
    uploaders = {u.id: u.name for u in User.query.filter(User.role != "student").all()}
    return render_template("teacher/documents.html", files=files, uploaders=uploaders,
                           grade=grade, classes=CLASSES, subjects=SUBJECTS, categories=CATEGORIES)


@bp.route("/teacher/documents/upload", methods=["POST"])
@teacher_required
def upload():
    file = request.files.get("pdf")
    class_name = request.form.get("class_name", "")
    subject = request.form.get("subject", "")
    category = request.form.get("category", "")
    title = request.form.get("title", "").strip()

    if class_name not in CLASSES or subject not in SUBJECTS or category not in CATEGORIES:
        flash("Please choose a class, subject and category.", "error")
        return redirect(url_for("library.documents"))
    if not file or not file.filename.lower().endswith(".pdf"):
        flash("Please choose a PDF file.", "error")
        return redirect(url_for("library.documents"))

    head = file.stream.read(5)
    file.stream.seek(0)
    if head != b"%PDF-":
        flash("That file is not a valid PDF.", "error")
        return redirect(url_for("library.documents"))

    if not title:
        title = os.path.splitext(secure_filename(file.filename))[0].replace("_", " ")
    stored = secrets.token_hex(16) + ".pdf"
    file.save(os.path.join(_folder(), stored))

    db.session.add(Resource(title=title[:200], category=category, class_name=class_name,
                            subject=subject, file_path=stored, uploaded_by=g.user.id))
    db.session.commit()
    flash(f"Uploaded '{title}' for Class {class_name}.", "success")
    return redirect(url_for("library.documents"))


@bp.route("/teacher/documents/<int:rid>/delete", methods=["POST"])
@teacher_required
def delete(rid):
    res = db.get_or_404(Resource, rid)
    if g.user.role != "admin" and res.uploaded_by != g.user.id:
        abort(403)
    path = os.path.join(_folder(), res.file_path)
    if os.path.exists(path):
        os.remove(path)
    title = res.title
    db.session.delete(res)
    db.session.commit()
    flash(f"Deleted '{title}'.", "success")
    return redirect(url_for("library.documents"))