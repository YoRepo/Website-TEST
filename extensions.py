# path: extensions.py
"""Extension instances are created here, UNBOUND to any app.

This is the classic trick that makes the application-factory pattern work
without circular imports: models.py and the blueprints import `db` from here,
and app.py later "binds" it to the real app with `db.init_app(app)`.
"""

from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf import CSRFProtect

# Created now, connected to an app later (see create_app in app.py).
db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()

# These need no app, so configure them here.
login_manager.login_view = "auth.login"
login_manager.login_message = "Please log in to continue."
login_manager.login_message_category = "error"
login_manager.session_protection = "strong"