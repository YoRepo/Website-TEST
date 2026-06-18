# path: cli.py
"""User/role management from the command line. Registered in create_app().

  flask --app app create-admin alice
  flask --app app create-user bob --role MODERATOR
  flask --app app set-role bob ADMIN
  flask --app app set-active bob off
  flask --app app list-users
"""

import click

from extensions import db
from models import User, UserRole

MIN_PASSWORD_LEN = 10


def _active_admin_count():
    return User.query.filter_by(role=UserRole.ADMIN, active=True).count()


def register_cli(app):
    def _create(username, display_name, password, role):
        username = (username or "").strip()
        if not (3 <= len(username) <= 40) or not username.isalnum():
            raise click.ClickException("Username must be 3–40 letters/digits.")
        if len(password) < MIN_PASSWORD_LEN:
            raise click.ClickException(
                f"Password must be at least {MIN_PASSWORD_LEN} characters.")
        if User.query.filter(db.func.lower(User.username) == username.lower()).first():
            raise click.ClickException("That username already exists.")
        user = User(username=username, display_name=display_name or None, role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo(f"Created {role.value} '{username}' (id={user.id}).")

    @app.cli.command("create-admin")
    @click.argument("username")
    @click.option("--display-name", default=None)
    @click.password_option()          # prompts twice, hidden, never in shell history
    def create_admin(username, display_name, password):
        """Create a new ADMIN (the standard way to bootstrap the first one)."""
        _create(username, display_name, password, UserRole.ADMIN)

    @app.cli.command("create-user")
    @click.argument("username")
    @click.option("--role", type=click.Choice([r.name for r in UserRole]),
                  default="USER", show_default=True)
    @click.option("--display-name", default=None)
    @click.password_option()
    def create_user(username, role, display_name, password):
        """Create a user with an explicit role."""
        _create(username, display_name, password, UserRole[role])

    @app.cli.command("set-role")
    @click.argument("username")
    @click.argument("role", type=click.Choice([r.name for r in UserRole]))
    def set_role(username, role):
        """Change a user's role."""
        user = User.query.filter(
            db.func.lower(User.username) == username.lower()).first()
        if user is None:
            raise click.ClickException(f"No user named '{username}'.")
        new_role = UserRole[role]
        if (user.role == UserRole.ADMIN and new_role != UserRole.ADMIN
                and _active_admin_count() <= 1):
            raise click.ClickException("Refusing to demote the last active admin.")
        user.role = new_role
        db.session.commit()
        click.echo(f"'{username}' is now {new_role.value}.")

    @app.cli.command("set-active")
    @click.argument("username")
    @click.argument("state", type=click.Choice(["on", "off"]))
    def set_active(username, state):
        """Enable (on) or disable (off) a user's ability to log in."""
        user = User.query.filter(
            db.func.lower(User.username) == username.lower()).first()
        if user is None:
            raise click.ClickException(f"No user named '{username}'.")
        active = state == "on"
        if (not active and user.role == UserRole.ADMIN
                and _active_admin_count() <= 1):
            raise click.ClickException("Refusing to disable the last active admin.")
        user.active = active
        db.session.commit()
        click.echo(f"'{username}' login is now {'enabled' if active else 'disabled'}.")

    @app.cli.command("list-users")
    def list_users():
        """Print all users with role and status."""
        for u in User.query.order_by(User.username).all():
            status = "active" if u.active else "DISABLED"
            click.echo(f"  {u.id:>3}  {u.username:<24} {u.role.value:<10} {status}")