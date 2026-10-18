"""
cleaning.py - Housekeeping, Sanitation Schedules, and Area Hygiene Checklists.

Manages sanitation tasks, checklists, and assigned cleaning staff across facilities.
Distinguishes between active employment status and confirmed task completion.
Identifies overdue cleaning tasks requiring immediate attention.
"""

import json
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from database import get_db
from auth import login_required, validate_csrf

cleaning_bp = Blueprint('cleaning', __name__, url_prefix='/cleaning')


@cleaning_bp.route('/')
@login_required
def index():
    """Display housekeeping tasks, checklists, and staff overview."""
    centre_id = request.args.get('centre_id', type=int)
    status_filter = request.args.get('status', 'all')

    if centre_id is None and session.get('active_centre_id'):
        centre_id = session.get('active_centre_id')

    now = datetime.now()
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id, name, code FROM health_centres ORDER BY name")
    centres = cursor.fetchall()

    # Fetch tasks
    query = """
        SELECT t.*, c.name AS centre_name, s.name AS staff_name, s.is_active AS staff_is_active
        FROM cleaning_tasks t
        JOIN health_centres c ON t.centre_id = c.id
        LEFT JOIN cleaning_staff s ON t.staff_id = s.id
        WHERE 1=1
    """
    params = []

    if centre_id and centre_id > 0:
        query += " AND t.centre_id = ?"
        params.append(centre_id)

    if status_filter != 'all':
        query += " AND t.status = ?"
        params.append(status_filter)

    query += " ORDER BY t.scheduled_time ASC, t.id DESC"
    cursor.execute(query, params)
    raw_tasks = cursor.fetchall()

    tasks = []
    pending_count = 0
    in_progress_count = 0
    completed_count = 0
    overdue_count = 0

    for r in raw_tasks:
        item = dict(r)
        # Parse checklists
        try:
            item['checklist'] = json.loads(item['checklist_json'])
        except Exception:
            item['checklist'] = []

        try:
            item['completed_indices'] = json.loads(item['completed_checklist_json'])
        except Exception:
            item['completed_indices'] = []

        # Check overdue
        is_overdue = False
        if item['status'] != 'Completed':
            try:
                sched_dt = datetime.strptime(item['scheduled_time'], "%Y-%m-%d %H:%M")
                if sched_dt < now:
                    is_overdue = True
                    overdue_count += 1
            except Exception:
                pass
        item['is_overdue'] = is_overdue

        if item['status'] == 'Pending':
            pending_count += 1
        elif item['status'] == 'In Progress':
            in_progress_count += 1
        elif item['status'] == 'Completed':
            completed_count += 1

        tasks.append(item)

    # Fetch cleaning staff for centre
    staff_query = """
        SELECT s.*, c.name AS centre_name
        FROM cleaning_staff s
        JOIN health_centres c ON s.centre_id = c.id
        WHERE 1=1
    """
    staff_params = []
    if centre_id and centre_id > 0:
        staff_query += " AND s.centre_id = ?"
        staff_params.append(centre_id)
    staff_query += " ORDER BY s.name ASC"
    cursor.execute(staff_query, staff_params)
    staff_list = cursor.fetchall()

    conn.close()

    return render_template(
        'cleaning/index.html',
        tasks=tasks,
        staff=staff_list,
        centres=centres,
        selected_centre_id=centre_id or 0,
        status_filter=status_filter,
        pending_count=pending_count,
        in_progress_count=in_progress_count,
        completed_count=completed_count,
        overdue_count=overdue_count
    )


@cleaning_bp.route('/update-task/<int:task_id>', methods=['POST'])
@login_required
def update_task(task_id):
    """Update cleaning task status, completed checklist items, and completion timestamp."""
    validate_csrf()
    new_status = request.form.get('status', '').strip()
    notes = request.form.get('notes', '').strip()
    checked_items = request.form.getlist('checklist_items')  # list of index strings e.g. ['0', '2']

    valid_statuses = ['Pending', 'In Progress', 'Completed']
    if new_status not in valid_statuses:
        flash("Invalid task status submitted.", "danger")
        return redirect(request.referrer or url_for('cleaning.index'))

    completed_indices = [int(i) for i in checked_items if i.isdigit()]
    completed_json = json.dumps(completed_indices)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    last_completed = now_str if new_status == 'Completed' else None

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE cleaning_tasks
        SET status = ?,
            completed_checklist_json = ?,
            last_completed_time = COALESCE(?, last_completed_time),
            notes = ?
        WHERE id = ?
    """, (new_status, completed_json, last_completed, notes, task_id))
    conn.commit()
    conn.close()

    flash("Cleaning task status updated successfully.", "success")
    return redirect(request.referrer or url_for('cleaning.index'))


@cleaning_bp.route('/add-task', methods=['POST'])
@login_required
def add_task():
    """Schedule a new housekeeping task."""
    validate_csrf()
    centre_id = request.form.get('centre_id', type=int)
    area = request.form.get('area', '').strip()
    staff_id = request.form.get('staff_id', type=int) or None
    scheduled_time = request.form.get('scheduled_time', '').strip()
    notes = request.form.get('notes', '').strip()

    if not centre_id or not area or not scheduled_time:
        flash("Health centre, area, and scheduled time are required.", "danger")
        return redirect(request.referrer or url_for('cleaning.index'))

    # Default checklist
    default_checklist = json.dumps([
        "Floor swept and mopped with hospital-grade disinfectant",
        "Bio-medical waste bins cleared into designated color-coded bags",
        "High-touch surfaces (bed railings, door knobs, taps) sanitized",
        "Hand sanitizer stations refilled and verified",
        "Restrooms cleaned and odor neutralizer applied"
    ])

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO cleaning_tasks (
            centre_id, area, staff_id, scheduled_time, status, checklist_json, completed_checklist_json, notes
        ) VALUES (?, ?, ?, ?, 'Pending', ?, '[]', ?)
    """, (centre_id, area, staff_id, scheduled_time, default_checklist, notes))
    conn.commit()
    conn.close()

    flash(f"New cleaning task scheduled for {area}.", "success")
    return redirect(url_for('cleaning.index', centre_id=centre_id))
