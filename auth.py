"""
auth.py - Authentication, User Sessions, and Role-Based Access Control (RBAC).

Provides login, logout, password hashing verification, and route protection decorators.
Also provides simple, robust CSRF token generation and validation for HTML forms.
"""

import functools
import secrets
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, g, abort
from werkzeug.security import check_password_hash
from database import get_db

auth_bp = Blueprint('auth', __name__)


def generate_csrf_token():
    """Generate a cryptographically secure token stored in session for CSRF prevention."""
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_hex(24)
    return session['_csrf_token']


def validate_csrf():
    """Verify that incoming POST requests contain a valid matching CSRF token."""
    if request.method == "POST":
        token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
        expected = session.get('_csrf_token')
        if not expected or not token or not secrets.compare_digest(token, expected):
            abort(400, description="Invalid or missing CSRF security token. Please try again.")


def get_current_user():
    """Return dictionary of current logged-in user from database or None."""
    if 'user_id' not in session:
        return None
    if not hasattr(g, '_current_user'):
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT u.id, u.username, u.full_name, u.role, u.centre_id, c.name AS centre_name
            FROM users u
            LEFT JOIN health_centres c ON u.centre_id = c.id
            WHERE u.id = ?
        """, (session['user_id'],))
        row = cursor.fetchone()
        conn.close()
        g._current_user = dict(row) if row else None
    return g._current_user


def login_required(view):
    """Decorator requiring a logged-in session to access the route."""
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if get_current_user() is None:
            flash("Please log in to access this page.", "warning")
            return redirect(url_for('auth.login', next=request.url))
        return view(**kwargs)
    return wrapped_view


def role_required(*allowed_roles):
    """Decorator restricting route access to specific roles (e.g. 'admin')."""
    def decorator(view):
        @functools.wraps(view)
        def wrapped_view(**kwargs):
            user = get_current_user()
            if not user:
                flash("Please log in first.", "warning")
                return redirect(url_for('auth.login', next=request.url))
            if user['role'] not in allowed_roles:
                flash(f"Access denied: '{user['role']}' role lacks permission for this action.", "danger")
                return redirect(url_for('dashboard.index'))
            return view(**kwargs)
        return wrapped_view
    return decorator


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Handle staff and administrator login."""
    if get_current_user():
        return redirect(url_for('dashboard.index'))

    error = None
    if request.method == 'POST':
        validate_csrf()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if not username or not password:
            error = "Both username and password are required."
        else:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
            user = cursor.fetchone()
            conn.close()

            if user and check_password_hash(user['password_hash'], password):
                # Successful login
                session.clear()
                session['user_id'] = user['id']
                session['username'] = user['username']
                session['full_name'] = user['full_name']
                session['role'] = user['role']
                session['centre_id'] = user['centre_id']
                # By default, active filter centre is user's centre, or 0 (All) for admin
                session['active_centre_id'] = user['centre_id'] if user['centre_id'] else 0
                generate_csrf_token()

                flash(f"Welcome back, {user['full_name']}!", "success")
                next_page = request.args.get('next')
                if next_page and next_page.startswith('/'):
                    return redirect(next_page)
                return redirect(url_for('dashboard.index'))
            else:
                error = "Invalid username or password. Please try again."

    return render_template('login.html', error=error)


@auth_bp.route('/logout')
def logout():
    """Clear session and log user out."""
    username = session.get('username')
    session.clear()
    flash("You have been successfully logged out.", "info")
    return redirect(url_for('auth.login'))
