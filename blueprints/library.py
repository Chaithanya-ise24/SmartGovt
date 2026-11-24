import os
import secrets

from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash, abort, send_file, current_app, g)
from werkzeug.utils import secure_filename

from models import db, Resource
from auth_utils import login_required, teacher_required

bp = Blueprint("library", __name__)

VALID_CLASSES = {"5", "6", "7"}
VALID_CATEGORIES = {"Textbook", "Notes", "Worksheet"}
PDF_MAGIC = b"%PDF-"


def _is_real_pdf(file):
    """Extension check plus magic bytes, so a renamed .exe is rejected."""
    if not file or not file.filename:
        return False
    if not file.filename.lower().endswith(".pdf"):
        return False
    head = file.read(5)
    file.seek(0)
    return head == PDF_MAGIC


def _student_class():
    """Students are restricted to their own class; others get None (all classes)."""
    return g.user.class_name if g.user.role == "student" else None


def _visible(resource):
    """Can the current user open this resource?"""
    return g.user.role != "student" or resource.class_name == g.user.class_name


def _resource_disk_path(resource):
    """Resolve the absolute path of an uploaded resource on disk."""
    upload_dir = os.path.abspath(current_app.config["UPLOAD_FOLDER"])
    return os.path.join(upload_dir, resource.file_path)


def _load(resource_id):
    resource = db.get_or_404(Resource, resource_id)
    if not _visible(resource):
        abort(403)
    return resource


# ------------------------------------------------------------------ student
@bp.route("/library")
@login_required
def library():
    if g.user.role != "student":
        return redirect(url_for("library.documents"))
    resources = (Resource.query
                 .filter_by(class_name=g.user.class_name)
                 .order_by(Resource.uploaded_at.desc())
                 .all())
    return render_template("student/library.html", resources=resources)


@bp.route("/library/view/<int:resource_id>")
@login_required
def view_resource(resource_id):
    resource = _load(resource_id)
    file_missing = not os.path.isfile(_resource_disk_path(resource))
    if file_missing:
        flash("This PDF file is missing on the server. Please ask a teacher to re-upload it.", "error")
    return render_template("library_view.html", resource=resource, file_missing=file_missing)


@bp.route("/library/file/<int:resource_id>")
@login_required
def file_resource(resource_id):
    """Streams the PDF for the viewer iframe (inline, not a download)."""
    resource = _load(resource_id)
    path = _resource_disk_path(resource)
    if not os.path.isfile(path):
        abort(404)
    resp = send_file(path, mimetype="application/pdf", as_attachment=False)
    resp.headers["Content-Disposition"] = "inline"
    return resp


@bp.route("/library/download/<int:resource_id>")
@login_required
def download_resource(resource_id):
    resource = _load(resource_id)
    path = _resource_disk_path(resource)
    if not os.path.isfile(path):
        flash("PDF file not found on the server.", "error")
        return redirect(url_for("library.view_resource", resource_id=resource_id))
    name = secure_filename(resource.title) or "document"
    return send_file(path, mimetype="application/pdf", as_attachment=True,
                     download_name=f"{name}.pdf")


# --------------------------------------------------- teacher / admin documents
@bp.route("/library/documents")
@teacher_required
def documents():
    resources = Resource.query.order_by(Resource.uploaded_at.desc()).all()
    return render_template("teacher/documents.html", resources=resources,
                           can_delete_any=g.user.role == "admin")


@bp.route("/library/upload", methods=["POST"])
@teacher_required
def upload_resource():
    title = request.form.get("title", "").strip()
    category = request.form.get("category", "").strip()
    class_name = request.form.get("class_name", "").strip()
    subject = request.form.get("subject", "").strip()
    file = request.files.get("pdf_file")

    if not title:
        flash("Title is required.", "error")
    elif category not in VALID_CATEGORIES:
        flash("Choose a category: Textbook, Notes or Worksheet.", "error")
    elif class_name not in VALID_CLASSES:
        flash("Choose a class (5, 6 or 7).", "error")
    elif not _is_real_pdf(file):
        flash("Please upload a real PDF file.", "error")
    else:
        filename = secrets.token_hex(16) + ".pdf"
        upload_dir = os.path.abspath(current_app.config["UPLOAD_FOLDER"])
        os.makedirs(upload_dir, exist_ok=True)
        file.save(os.path.join(upload_dir, filename))

        db.session.add(Resource(title=title[:200], category=category,
                                class_name=class_name,
                                subject=subject[:50] or None,
                                file_path=filename, uploaded_by=g.user.id))
        db.session.commit()
        flash("Document uploaded successfully.", "success")

    return redirect(url_for("library.documents"))


@bp.route("/library/delete/<int:resource_id>", methods=["POST"])
@teacher_required
def delete_resource(resource_id):
    resource = db.get_or_404(Resource, resource_id)
    if g.user.role != "admin" and resource.uploaded_by != g.user.id:
        abort(403)

    path = _resource_disk_path(resource)
    if os.path.isfile(path):
        os.remove(path)

    db.session.delete(resource)
    db.session.commit()
    flash("Document deleted.", "success")
    return redirect(url_for("library.documents"))