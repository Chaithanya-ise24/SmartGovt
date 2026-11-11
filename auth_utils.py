from functools import wraps

from flask import g, session, redirect, url_for, request, abort

from models import db, User


def load_user():
    """Runs before every request and sets g.user."""
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
            return redirect(url_for("auth.login"))
        if g.user.must_change_password and request.endpoint != "auth.change_password":
            return redirect(url_for("auth.change_password"))
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


teacher_required = role_required("teacher", "admin")   # Headmaster also has teacher access
admin_required = role_required("admin")