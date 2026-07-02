# path: extensions.py
"""Extension instances are created here, UNBOUND to any app.

This is the classic trick that makes the application-factory pattern work
without circular imports: models.py and the blueprints import `db` from here,
and app.py later "binds" it to the real app with `db.init_app(app)`.
"""

import os

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
# in with @limiter.limit(...).
#
# Storage defaults to in-memory, which is fine for a single instance but resets
# on every restart/deploy and can't be shared across workers or instances. Set
# RATELIMIT_STORAGE_URI (e.g. redis://…) in production so throttles actually
# persist and span processes — otherwise brute-force protection is reset every
# time Render restarts the dyno.
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=os.environ.get("RATELIMIT_STORAGE_URI", "memory://"),
)

# These need no app, so configure them here.
login_manager.login_view = "auth.login"
login_manager.login_message = "Please log in to continue."
login_manager.login_message_category = "error"
login_manager.session_protection = "strong"