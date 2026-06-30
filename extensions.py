# path: extensions.py
"""Extension instances are created here, UNBOUND to any app.

This is the classic trick that makes the application-factory pattern work
without circular imports: models.py and the blueprints import `db` from here,
and app.py later "binds" it to the real app with `db.init_app(app)`.
"""

from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Created now, connected to an app later (see create_app in app.py).
db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()

# Per-client request throttling (brute-force / abuse defence). Keyed by client
# IP — see ProxyFix in create_app(), which makes request.remote_addr the real
# caller behind Render's proxy. No global default limits: individual views opt
# in with @limiter.limit(...). In-memory storage is fine for a single instance;
# point RATELIMIT_STORAGE_URI at Redis if you ever run more than one.
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri="memory://",
)

# These need no app, so configure them here.
login_manager.login_view = "auth.login"
login_manager.login_message = "Please log in to continue."
login_manager.login_message_category = "error"
login_manager.session_protection = "strong"