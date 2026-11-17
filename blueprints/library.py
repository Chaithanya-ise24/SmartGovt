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
    return render_template("library_view.html", resource=resource)


@bp.route("/library/file/<int:resource_id>")
@login_required
def file_resource(resource_id):
    """Streams the PDF for the viewer iframe (inline, not a download)."""
    resource = _load(resource_id)
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], resource.file_path)
    if not os.path.isfile(path):
        abort(404)
    resp = send_file(path, mimetype="application/pdf", as_attachment=False)
    resp.headers["Content-Disposition"] = "inline"
    return resp


@bp.route("/library/download/<int:resource_id>")
@login_required
def download_resource(resource_id):
    resource = _load(resource_id)
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], resource.file_path)
    if not os.path.isfile(path):
        abort(404)
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
        filename = secrets.token_hex(16) + ".pdf"      # random, unguessable
        upload_dir = current_app.config["UPLOAD_FOLDER"]
        os.makedirs(upload_dir, exist_ok=True)
        file.save(os.path.join(upload_dir, filename))

        db.session.add(Resource(title=title[:200], category=category,
                                class_name=class_name,
                                subject=subject[:50] or None,
                                file_path=filename, uploaded_by=g.user.id))
        db.session.commit()
        flash(f"Uploaded “{title}”.", "success")
    return redirect(url_for("library.documents"))


@bp.route("/library/delete/<int:resource_id>", methods=["POST"])
@teacher_required
def delete_resource(resource_id):
    resource = db.get_or_404(Resource, resource_id)
    if g.user.role != "admin" and resource.uploaded_by != g.user.id:
        abort(403)                      # teachers can only delete their own files
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], resource.file_path)
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass
    db.session.delete(resource)
    db.session.commit()
    flash("Document deleted.", "success")
    return redirect(request.referrer or url_for("library.documents"))