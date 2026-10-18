"""
doctors.py - Doctor Duty Rosters, Availability Status, and Leave Management.

Tracks:
- Scheduled duty hours vs confirmed real-time attendance status.
- Statuses: 'On Duty', 'Available', 'Unavailable', 'On Leave'.
- Leave start/end dates and leave reasons.
- Accurate audit timestamp of the latest attendance confirmation.
"""

from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from database import get_db
from auth import login_required, validate_csrf

doctors_bp = Blueprint('doctors', __name__, url_prefix='/doctors')


@doctors_bp.route('/')
@login_required
def index():
    """Display doctor schedules, current availability, and leave tracking."""
    centre_id = request.args.get('centre_id', type=int)
    status_filter = request.args.get('status', 'all')

    if centre_id is None and session.get('active_centre_id'):
        centre_id = session.get('active_centre_id')

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id, name, code FROM health_centres ORDER BY name")
    centres = cursor.fetchall()

    query = """
        SELECT d.*, c.name AS centre_name, c.code AS centre_code
        FROM doctors d
        JOIN health_centres c ON d.centre_id = c.id
        WHERE 1=1
    """
    params = []

    if centre_id and centre_id > 0:
        query += " AND d.centre_id = ?"
        params.append(centre_id)

    if status_filter != 'all':
        query += " AND d.current_status = ?"
        params.append(status_filter)

    query += " ORDER BY c.name ASC, d.name ASC"
    cursor.execute(query, params)
    doctors_list = cursor.fetchall()

    # Calculate status summary metrics
    on_duty_count = 0
    available_count = 0
    on_leave_count = 0
    unavailable_count = 0

    for d in doctors_list:
        st = d['current_status']
        if st == 'On Duty':
            on_duty_count += 1
        elif st == 'Available':
            available_count += 1
        elif st == 'On Leave':
            on_leave_count += 1
        else:
            unavailable_count += 1

    conn.close()

    return render_template(
        'doctors/index.html',
        doctors=doctors_list,
        centres=centres,
        selected_centre_id=centre_id or 0,
        status_filter=status_filter,
        on_duty_count=on_duty_count,
        available_count=available_count,
        on_leave_count=on_leave_count,
        unavailable_count=unavailable_count
    )


@doctors_bp.route('/update-status/<int:doctor_id>', methods=['POST'])
@login_required
def update_status(doctor_id):
    """
    Update a doctor's attendance and duty status.
    Clearly records server timestamp and updating staff member.
    """
    validate_csrf()
    new_status = request.form.get('current_status', '').strip()
    leave_start = request.form.get('leave_start_date', '').strip() or None
    leave_end = request.form.get('leave_end_date', '').strip() or None
    leave_reason = request.form.get('leave_reason', '').strip() or None

    valid_statuses = ['On Duty', 'Available', 'Unavailable', 'On Leave']
    if new_status not in valid_statuses:
        flash("Invalid doctor status submitted.", "danger")
        return redirect(request.referrer or url_for('doctors.index'))

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    username = session.get('username', 'staff')

    # If status is not 'On Leave', clear active leave dates unless explicitly preserved
    if new_status != 'On Leave':
        leave_start = None
        leave_end = None
        leave_reason = None

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE doctors
        SET current_status = ?,
            leave_start_date = ?,
            leave_end_date = ?,
            leave_reason = ?,
            last_status_update = ?,
            updated_by = ?
        WHERE id = ?
    """, (new_status, leave_start, leave_end, leave_reason, now_str, username, doctor_id))
    conn.commit()
    conn.close()

    flash(f"Doctor status successfully updated to '{new_status}'.", "success")
    return redirect(request.referrer or url_for('doctors.index'))
