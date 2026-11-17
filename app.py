from flask import Flask, render_template, request
from flask_wtf.csrf import CSRFError
from sqlalchemy import event

from config import Config
from extensions import csrf
from models import db, User
from auth_utils import load_user


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    csrf.init_app(app)
    app.before_request(load_user)

    # SQLite WAL mode
    with app.app_context():
        @event.listens_for(db.engine, "connect")
        def set_sqlite_pragma(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL;")
            cur.close()

    # Blueprints (members: the Leader registers yours here)
    from blueprints import auth, admin, library, ai, student, dashboards
    for module in (auth, admin, library, ai, student, dashboards):
        app.register_blueprint(module.bp)

    # Seed admin account
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(role="admin").first():
            a = User(username=app.config["ADMIN_USERNAME"], name="Headmaster", role="admin")
            a.set_password(app.config["ADMIN_PASSWORD"])
            db.session.add(a)
            db.session.commit()
            print("Admin account created.")

    # Error pages
    @app.errorhandler(403)
    def forbidden(_):
        return render_template("error.html", title="Access Denied",
                               message="You don't have permission to open this page."), 403

    @app.errorhandler(404)
    def not_found(_):
        return render_template("error.html", title="Page Not Found",
                               message="We couldn't find that page."), 404

    @app.errorhandler(CSRFError)
    def csrf_error(_):
        return render_template("error.html", title="Session Expired",
                               message="Please go back, refresh the page and try again."), 400

    @app.errorhandler(413)
    def payload_too_large(_):
        return render_template("error.html", title="File Too Large",
                               message="Maximum upload size is 25 MB."), 413

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
    