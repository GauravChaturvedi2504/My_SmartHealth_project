"""
audit.py - Immutable Stock Transaction Audit Trail.

Displays complete history of stock received, dispensed, corrected, and expired.
Guarantees audit records cannot be edited or deleted via the UI.
"""

from flask import Blueprint, render_template, request, session
from database import get_db
from auth import login_required

audit_bp = Blueprint('audit', __name__, url_prefix='/audit')


@audit_bp.route('/')
@login_required
def index():
    """Display searchable, filterable stock audit history."""
    centre_id = request.args.get('centre_id', type=int)
    tx_type = request.args.get('type', 'all')
    search_q = request.args.get('q', '').strip()

    if centre_id is None and session.get('active_centre_id'):
        centre_id = session.get('active_centre_id')

    conn = get_db()
    cursor = conn.cursor()

    # Health centres for dropdown
    cursor.execute("SELECT id, name, code FROM health_centres ORDER BY name")
    centres = cursor.fetchall()

    query = """
        SELECT a.*, c.name AS centre_name, c.code AS centre_code
        FROM stock_audit_log a
        JOIN health_centres c ON a.centre_id = c.id
        WHERE 1=1
    """
    params = []

    if centre_id and centre_id > 0:
        query += " AND a.centre_id = ?"
        params.append(centre_id)

    if tx_type and tx_type != 'all':
        query += " AND a.transaction_type = ?"
        params.append(tx_type)

    if search_q:
        query += " AND (a.medicine_name LIKE ? OR a.batch_id LIKE ? OR a.staff_username LIKE ? OR a.reason LIKE ?)"
        term = f"%{search_q}%"
        params.extend([term, term, term, term])

    query += " ORDER BY a.timestamp DESC, a.id DESC LIMIT 200"

    cursor.execute(query, params)
    audit_logs = cursor.fetchall()
    conn.close()

    return render_template(
        'audit/index.html',
        logs=audit_logs,
        centres=centres,
        selected_centre_id=centre_id or 0,
        tx_type=tx_type,
        search_q=search_q
    )
