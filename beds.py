"""
beds.py - Ward and Bed Occupancy Management.

Tracks individual beds by health centre and ward.
Enforces strict single-state validation:
A bed cannot be marked both Available and Occupied.
"""

from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from database import get_db
from auth import login_required, validate_csrf

beds_bp = Blueprint('beds', __name__, url_prefix='/beds')


@beds_bp.route('/')
@login_required
def index():
    """Display bed grid, ward occupancy breakdown, and shortage warnings."""
    centre_id = request.args.get('centre_id', type=int)
    ward_filter = request.args.get('ward', 'all')
    status_filter = request.args.get('status', 'all')

    if centre_id is None and session.get('active_centre_id'):
        centre_id = session.get('active_centre_id')

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id, name, code FROM health_centres ORDER BY name")
    centres = cursor.fetchall()

    query = """
        SELECT b.*, c.name AS centre_name, c.code AS centre_code
        FROM beds b
        JOIN health_centres c ON b.centre_id = c.id
        WHERE 1=1
    """
    params = []

    if centre_id and centre_id > 0:
        query += " AND b.centre_id = ?"
        params.append(centre_id)

    if ward_filter != 'all':
        query += " AND b.ward = ?"
        params.append(ward_filter)

    if status_filter != 'all':
        query += " AND b.status = ?"
        params.append(status_filter)

    query += " ORDER BY c.name ASC, b.ward ASC, b.bed_number ASC"
    cursor.execute(query, params)
    beds_list = cursor.fetchall()

    # Get distinct wards for filtering
    cursor.execute("SELECT DISTINCT ward FROM beds ORDER BY ward")
    wards = [w['ward'] for w in cursor.fetchall()]

    # Occupancy counts
    total_beds = len(beds_list)
    available_beds = sum(1 for b in beds_list if b['status'] == 'Available')
    occupied_beds = sum(1 for b in beds_list if b['status'] == 'Occupied')
    out_of_service = sum(1 for b in beds_list if b['status'] == 'Out of Service')

    usable_total = total_beds - out_of_service
    occupancy_pct = round((occupied_beds / usable_total * 100), 1) if usable_total > 0 else 0.0

    conn.close()

    return render_template(
        'beds/index.html',
        beds=beds_list,
        centres=centres,
        selected_centre_id=centre_id or 0,
        ward_filter=ward_filter,
        status_filter=status_filter,
        wards=wards,
        total_beds=total_beds,
        available_beds=available_beds,
        occupied_beds=occupied_beds,
        out_of_service=out_of_service,
        occupancy_pct=occupancy_pct
    )


@beds_bp.route('/update/<int:bed_id>', methods=['POST'])
@login_required
def update_bed(bed_id):
    """
    Update a bed's status with validation to prevent inconsistent dual states.
    If bed is Available, patient identifier is cleared.
    """
    validate_csrf()
    new_status = request.form.get('status', '').strip()
    patient_id = request.form.get('patient_identifier', '').strip() or None
    notes = request.form.get('notes', '').strip() or None

    valid_statuses = ['Available', 'Occupied', 'Out of Service']
    if new_status not in valid_statuses:
        flash("Invalid bed status selected.", "danger")
        return redirect(request.referrer or url_for('beds.index'))

    # Strict validation: Available beds must NOT retain a patient identifier
    if new_status == 'Available':
        patient_id = None
    elif new_status == 'Occupied' and not patient_id:
        patient_id = "Occupied (Patient In Bed)"

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE beds
        SET status = ?, patient_identifier = ?, notes = ?, last_updated = ?
        WHERE id = ?
    """, (new_status, patient_id, notes, now_str, bed_id))
    conn.commit()
    conn.close()

    flash("Bed status updated successfully.", "success")
    return redirect(request.referrer or url_for('beds.index'))
