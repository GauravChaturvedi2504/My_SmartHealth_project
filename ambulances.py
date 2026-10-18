"""
ambulances.py - Ambulance Fleet, Trip Dispatch, and Service Readiness.

Tracks emergency response fleet across facilities:
- Vehicle ID, registration, vehicle type (BLS / ALS / Patient Transport)
- Assigned centre, driver contact, and operational readiness
- Validated dispatch trips: destination, patient transfer, departure, and expected arrival
- Document compliance (fitness certificate, insurance validity, routine servicing dates)
- Does not simulate live GPS coordinates; relies on confirmed dispatch and arrival milestones.
"""

from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from database import get_db
from auth import login_required, validate_csrf

ambulances_bp = Blueprint('ambulances', __name__, url_prefix='/ambulances')


@ambulances_bp.route('/')
@login_required
def index():
    """Display ambulance fleet status, active dispatch trips, and compliance deadlines."""
    centre_id = request.args.get('centre_id', type=int)
    status_filter = request.args.get('status', 'all')

    if centre_id is None and session.get('active_centre_id'):
        centre_id = session.get('active_centre_id')

    today_date = datetime.now().strftime("%Y-%m-%d")
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id, name, code FROM health_centres ORDER BY name")
    centres = cursor.fetchall()

    query = """
        SELECT a.*, c.name AS centre_name, c.code AS centre_code,
               (SELECT t.destination FROM ambulance_trips t WHERE t.ambulance_id = a.id AND t.status = 'In Transit' LIMIT 1) AS active_destination,
               (SELECT t.departure_time FROM ambulance_trips t WHERE t.ambulance_id = a.id AND t.status = 'In Transit' LIMIT 1) AS active_departure_time,
               (SELECT t.patient_identifier FROM ambulance_trips t WHERE t.ambulance_id = a.id AND t.status = 'In Transit' LIMIT 1) AS active_patient_id
        FROM ambulances a
        JOIN health_centres c ON a.centre_id = c.id
        WHERE 1=1
    """
    params = []
    if centre_id and centre_id > 0:
        query += " AND a.centre_id = ?"
        params.append(centre_id)

    if status_filter != 'all':
        query += " AND a.status = ?"
        params.append(status_filter)

    query += " ORDER BY a.centre_id ASC, a.vehicle_code ASC"
    cursor.execute(query, params)
    raw_ambulances = cursor.fetchall()

    ambulances_list = []
    available_count = 0
    dispatched_count = 0
    maintenance_count = 0
    docs_expiring_count = 0

    for r in raw_ambulances:
        item = dict(r)
        if item['status'] == 'Available':
            available_count += 1
        elif item['status'] == 'Dispatched / On Trip':
            dispatched_count += 1
        elif item['status'] in ['Under Maintenance', 'Out of Service']:
            maintenance_count += 1

        # Check compliance expiry
        item['is_service_due'] = item['next_service_due'] <= today_date
        item['is_insurance_due'] = item['insurance_expiry'] <= today_date
        item['is_fitness_due'] = item['fitness_cert_expiry'] <= today_date

        if item['is_service_due'] or item['is_insurance_due'] or item['is_fitness_due']:
            docs_expiring_count += 1

        ambulances_list.append(item)

    # Fetch recent trip records
    trip_query = """
        SELECT t.*, a.vehicle_code, a.registration_number, c.name AS centre_name
        FROM ambulance_trips t
        JOIN ambulances a ON t.ambulance_id = a.id
        JOIN health_centres c ON t.centre_id = c.id
        WHERE 1=1
    """
    trip_params = []
    if centre_id and centre_id > 0:
        trip_query += " AND t.centre_id = ?"
        trip_params.append(centre_id)
    trip_query += " ORDER BY t.departure_time DESC LIMIT 30"
    cursor.execute(trip_query, trip_params)
    recent_trips = cursor.fetchall()

    conn.close()

    return render_template(
        'ambulances/index.html',
        ambulances=ambulances_list,
        trips=recent_trips,
        centres=centres,
        selected_centre_id=centre_id or 0,
        status_filter=status_filter,
        available_count=available_count,
        dispatched_count=dispatched_count,
        maintenance_count=maintenance_count,
        docs_expiring_count=docs_expiring_count
    )


@ambulances_bp.route('/dispatch', methods=['POST'])
@login_required
def dispatch_ambulance():
    """Dispatch an ambulance on an emergency or transfer trip."""
    validate_csrf()
    ambulance_id = request.form.get('ambulance_id', type=int)
    trip_purpose = request.form.get('trip_purpose', 'Emergency Pickup').strip()
    patient_id = request.form.get('patient_identifier', '').strip().upper()
    destination = request.form.get('destination', '').strip()
    expected_return = request.form.get('expected_return_time', '').strip()
    paramedic = request.form.get('paramedic_staff', '').strip()
    notes = request.form.get('notes', '').strip()

    if not ambulance_id or not destination:
        flash("Ambulance and destination are required.", "danger")
        return redirect(request.referrer or url_for('ambulances.index'))

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM ambulances WHERE id = ?", (ambulance_id,))
    amb = cursor.fetchone()

    if not amb:
        conn.close()
        flash("Ambulance not found.", "warning")
        return redirect(url_for('ambulances.index'))

    if amb['status'] != 'Available':
        conn.close()
        flash(f"Cannot dispatch {amb['vehicle_code']}: current status is '{amb['status']}'.", "danger")
        return redirect(request.referrer or url_for('ambulances.index'))

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    username = session.get('username', 'staff')

    try:
        # Create trip record
        cursor.execute("""
            INSERT INTO ambulance_trips (
                ambulance_id, centre_id, trip_purpose, patient_identifier, destination,
                departure_time, expected_return_time, driver_name, paramedic_staff, status, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'In Transit', ?)
        """, (ambulance_id, amb['centre_id'], trip_purpose, patient_id, destination, now_str, expected_return, amb['primary_driver_name'], paramedic, notes))

        # Update ambulance status
        cursor.execute("""
            UPDATE ambulances
            SET status = 'Dispatched / On Trip', last_status_update = ?, updated_by = ?
            WHERE id = ?
        """, (now_str, username, ambulance_id))

        conn.commit()
        flash(f"Ambulance {amb['vehicle_code']} ({amb['registration_number']}) dispatched to {destination}.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error during dispatch: {str(e)}", "danger")
    finally:
        conn.close()

    return redirect(request.referrer or url_for('ambulances.index'))


@ambulances_bp.route('/return-trip/<int:ambulance_id>', methods=['POST'])
@login_required
def return_trip(ambulance_id):
    """Mark an ambulance trip completed and set vehicle back to Available."""
    validate_csrf()
    notes = request.form.get('return_notes', '').strip()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    username = session.get('username', 'staff')

    conn = get_db()
    cursor = conn.cursor()

    try:
        # Close open trip
        cursor.execute("""
            UPDATE ambulance_trips
            SET actual_return_time = ?, status = 'Completed', notes = COALESCE(notes || ' | Return: ' || ?, notes)
            WHERE ambulance_id = ? AND status = 'In Transit'
        """, (now_str, notes, ambulance_id))

        # Set ambulance status to Available
        cursor.execute("""
            UPDATE ambulances
            SET status = 'Available', last_status_update = ?, updated_by = ?
            WHERE id = ?
        """, (now_str, username, ambulance_id))

        conn.commit()
        flash("Ambulance trip completed. Vehicle returned to Available pool.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error completing trip: {str(e)}", "danger")
    finally:
        conn.close()

    return redirect(request.referrer or url_for('ambulances.index'))


@ambulances_bp.route('/update-status/<int:ambulance_id>', methods=['POST'])
@login_required
def update_status(ambulance_id):
    """Update maintenance or out of service status for an ambulance."""
    validate_csrf()
    new_status = request.form.get('status', 'Available').strip()
    next_service = request.form.get('next_service_due', '').strip()
    notes = request.form.get('notes', '').strip()

    valid_statuses = ['Available', 'Under Maintenance', 'Out of Service']
    if new_status not in valid_statuses:
        flash("Invalid ambulance status.", "danger")
        return redirect(request.referrer or url_for('ambulances.index'))

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    username = session.get('username', 'staff')

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE ambulances
        SET status = ?,
            next_service_due = COALESCE(NULLIF(?, ''), next_service_due),
            last_status_update = ?,
            updated_by = ?
        WHERE id = ?
    """, (new_status, next_service, now_str, username, ambulance_id))
    conn.commit()
    conn.close()

    flash(f"Ambulance status updated to '{new_status}'.", "success")
    return redirect(request.referrer or url_for('ambulances.index'))
