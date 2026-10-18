"""
dashboard.py - Main Healthcare Command Centre Dashboard.

Aggregates operational metrics across:
- Today's patient footfall
- Bed occupancy & availability
- Medicine stock levels & expiry alerts
- Doctor duty and leave rosters
- Housekeeping and overdue sanitation
- High-priority active system alerts
Supports facility-specific filtering as well as multi-centre overall aggregation.
"""

from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, session
from database import get_db
from auth import login_required
from inventory import evaluate_batch_status, get_expiry_threshold_days
from alerts import sync_system_alerts

dashboard_bp = Blueprint('dashboard', __name__)


@dashboard_bp.route('/')
@login_required
def index():
    """Main executive operational dashboard view."""
    centre_id = request.args.get('centre_id', type=int)

    # Use session active centre if no query param
    if centre_id is None:
        centre_id = session.get('active_centre_id', 0)
    else:
        session['active_centre_id'] = centre_id

    threshold_days = get_expiry_threshold_days()
    today_str = datetime.now().strftime("%Y-%m-%d")
    now = datetime.now()

    conn = get_db()
    # Trigger system alerts synchronization
    sync_system_alerts(conn)
    cursor = conn.cursor()

    # 1. Fetch Centres list
    cursor.execute("SELECT id, name, code, centre_type, location, contact_number FROM health_centres ORDER BY name")
    centres = cursor.fetchall()

    selected_centre = None
    if centre_id > 0:
        for c in centres:
            if c['id'] == centre_id:
                selected_centre = c
                break

    # 2. Patient Footfall Today
    footfall_query = "SELECT SUM(total_count), SUM(outpatient_count), SUM(emergency_count), SUM(referral_count) FROM patient_footfall WHERE record_date = ?"
    footfall_params = [today_str]
    if centre_id > 0:
        footfall_query += " AND centre_id = ?"
        footfall_params.append(centre_id)
    cursor.execute(footfall_query, footfall_params)
    ff_row = cursor.fetchone()
    total_patients_today = ff_row[0] or 0
    op_today = ff_row[1] or 0
    em_today = ff_row[2] or 0
    ref_today = ff_row[3] or 0

    # 3. Beds Summary
    beds_query = "SELECT status, COUNT(*) FROM beds WHERE 1=1"
    beds_params = []
    if centre_id > 0:
        beds_query += " AND centre_id = ?"
        beds_params.append(centre_id)
    beds_query += " GROUP BY status"
    cursor.execute(beds_query, beds_params)
    bed_counts = {row[0]: row[1] for row in cursor.fetchall()}
    available_beds = bed_counts.get('Available', 0)
    occupied_beds = bed_counts.get('Occupied', 0)
    out_of_service_beds = bed_counts.get('Out of Service', 0)
    total_beds = available_beds + occupied_beds + out_of_service_beds
    usable_beds = total_beds - out_of_service_beds
    occupancy_rate = round((occupied_beds / usable_beds * 100), 1) if usable_beds > 0 else 0.0

    # 4. Medicine Inventory Summary
    inv_query = "SELECT * FROM medicine_batches WHERE 1=1"
    inv_params = []
    if centre_id > 0:
        inv_query += " AND centre_id = ?"
        inv_params.append(centre_id)
    cursor.execute(inv_query, inv_params)
    batches = cursor.fetchall()

    total_medicines = len(batches)
    low_stock_medicines = 0
    nearing_expiry_medicines = 0
    expired_medicines = 0
    usable_medicines_count = 0

    for b in batches:
        st = evaluate_batch_status(b['expiry_date'], b['quantity'], b['min_stock_level'], threshold_days)
        if st['is_expired']:
            expired_medicines += 1
        else:
            usable_medicines_count += 1

        if st['is_low_stock']:
            low_stock_medicines += 1
        if st['is_near_expiry']:
            nearing_expiry_medicines += 1

    # 5. Doctors Summary
    doc_query = "SELECT current_status, COUNT(*) FROM doctors WHERE 1=1"
    doc_params = []
    if centre_id > 0:
        doc_query += " AND centre_id = ?"
        doc_params.append(centre_id)
    doc_query += " GROUP BY current_status"
    cursor.execute(doc_query, doc_params)
    doc_counts = {row[0]: row[1] for row in cursor.fetchall()}
    doctors_on_duty = doc_counts.get('On Duty', 0)
    doctors_available = doc_counts.get('Available', 0)
    doctors_on_leave = doc_counts.get('On Leave', 0)
    doctors_unavailable = doc_counts.get('Unavailable', 0)
    total_doctors = sum(doc_counts.values())

    # 6. Cleaning Tasks Summary
    clean_query = "SELECT * FROM cleaning_tasks WHERE 1=1"
    clean_params = []
    if centre_id > 0:
        clean_query += " AND centre_id = ?"
        clean_params.append(centre_id)
    cursor.execute(clean_query, clean_params)
    tasks = cursor.fetchall()
    pending_cleaning_tasks = 0
    in_progress_cleaning_tasks = 0
    overdue_cleaning_tasks = 0

    for t in tasks:
        if t['status'] == 'Pending':
            pending_cleaning_tasks += 1
        elif t['status'] == 'In Progress':
            in_progress_cleaning_tasks += 1

        if t['status'] != 'Completed':
            try:
                s_dt = datetime.strptime(t['scheduled_time'], "%Y-%m-%d %H:%M")
                if s_dt < now:
                    overdue_cleaning_tasks += 1
            except Exception:
                pass

    # 7. Priority Alerts Summary (Unacknowledged)
    alert_query = """
        SELECT a.*, c.name AS centre_name
        FROM alerts a
        LEFT JOIN health_centres c ON a.centre_id = c.id
        WHERE a.is_acknowledged = 0
    """
    alert_params = []
    if centre_id > 0:
        alert_query += " AND a.centre_id = ?"
        alert_params.append(centre_id)

    alert_query += """
        ORDER BY
            CASE a.severity
                WHEN 'CRITICAL' THEN 1
                WHEN 'HIGH' THEN 2
                WHEN 'MEDIUM' THEN 3
                ELSE 4
            END,
            a.created_at DESC
        LIMIT 6
    """
    cursor.execute(alert_query, alert_params)
    active_alerts = cursor.fetchall()

    critical_alerts_count = sum(1 for a in active_alerts if a['severity'] == 'CRITICAL')

    # 8. Recent 7-Day Footfall Trend for Chart
    trend_query = """
        SELECT record_date, SUM(total_count) as day_total
        FROM patient_footfall
        WHERE 1=1
    """
    trend_params = []
    if centre_id > 0:
        trend_query += " AND centre_id = ?"
        trend_params.append(centre_id)
    trend_query += " GROUP BY record_date ORDER BY record_date DESC LIMIT 7"
    cursor.execute(trend_query, trend_params)
    footfall_trend_rows = cursor.fetchall()
    # Reverse to chronological order (oldest to newest)
    footfall_trends = list(reversed(footfall_trend_rows))

    # 9. Recent Activity / Audit Log (last 5 records)
    recent_query = """
        SELECT a.*, c.name as centre_name
        FROM stock_audit_log a
        JOIN health_centres c ON a.centre_id = c.id
        WHERE 1=1
    """
    recent_params = []
    if centre_id > 0:
        recent_query += " AND a.centre_id = ?"
        recent_params.append(centre_id)
    recent_query += " ORDER BY a.timestamp DESC LIMIT 5"
    cursor.execute(recent_query, recent_params)
    recent_activity = cursor.fetchall()

    # 10. Patient Equipment Metrics
    eq_query = "SELECT current_status, COUNT(*) FROM equipment_items WHERE 1=1"
    eq_params = []
    if centre_id > 0:
        eq_query += " AND centre_id = ?"
        eq_params.append(centre_id)
    eq_query += " GROUP BY current_status"
    cursor.execute(eq_query, eq_params)
    eq_counts = {row[0]: row[1] for row in cursor.fetchall()}
    avail_equipment = eq_counts.get('Available', 0)
    in_use_equipment = eq_counts.get('In Use', 0)
    maint_equipment = eq_counts.get('Under Maintenance', 0) + eq_counts.get('Damaged', 0)

    # Overdue equipment count
    overdue_eq_query = """
        SELECT COUNT(*) FROM equipment_allotments
        WHERE status = 'Active' AND expected_return_time < ?
    """
    now_min_str = now.strftime("%Y-%m-%d %H:%M")
    overdue_eq_params = [now_min_str]
    if centre_id > 0:
        overdue_eq_query += " AND centre_id = ?"
        overdue_eq_params.append(centre_id)
    cursor.execute(overdue_eq_query, overdue_eq_params)
    overdue_equipment = cursor.fetchone()[0]

    # 11. Ambulances Availability
    amb_query = "SELECT status, COUNT(*) FROM ambulances WHERE 1=1"
    amb_params = []
    if centre_id > 0:
        amb_query += " AND centre_id = ?"
        amb_params.append(centre_id)
    amb_query += " GROUP BY status"
    cursor.execute(amb_query, amb_params)
    amb_counts = {row[0]: row[1] for row in cursor.fetchall()}
    avail_ambulances = amb_counts.get('Available', 0)
    total_ambulances = sum(amb_counts.values())

    # 12. Facility Maintenance Work Orders
    wo_query = "SELECT COUNT(*) FROM maintenance_work_orders WHERE status IN ('Open', 'In Progress')"
    wo_params = []
    if centre_id > 0:
        wo_query += " AND centre_id = ?"
        wo_params.append(centre_id)
    cursor.execute(wo_query, wo_params)
    open_work_orders = cursor.fetchone()[0]

    conn.close()

    return render_template(
        'dashboard.html',
        centres=centres,
        selected_centre_id=centre_id,
        selected_centre=selected_centre,
        total_patients_today=total_patients_today,
        op_today=op_today,
        em_today=em_today,
        ref_today=ref_today,
        available_beds=available_beds,
        occupied_beds=occupied_beds,
        out_of_service_beds=out_of_service_beds,
        total_beds=total_beds,
        occupancy_rate=occupancy_rate,
        total_medicines=total_medicines,
        low_stock_medicines=low_stock_medicines,
        nearing_expiry_medicines=nearing_expiry_medicines,
        expired_medicines=expired_medicines,
        doctors_on_duty=doctors_on_duty,
        doctors_available=doctors_available,
        doctors_on_leave=doctors_on_leave,
        doctors_unavailable=doctors_unavailable,
        total_doctors=total_doctors,
        pending_cleaning_tasks=pending_cleaning_tasks,
        in_progress_cleaning_tasks=in_progress_cleaning_tasks,
        overdue_cleaning_tasks=overdue_cleaning_tasks,
        avail_equipment=avail_equipment,
        in_use_equipment=in_use_equipment,
        overdue_equipment=overdue_equipment,
        maint_equipment=maint_equipment,
        avail_ambulances=avail_ambulances,
        total_ambulances=total_ambulances,
        open_work_orders=open_work_orders,
        active_alerts=active_alerts,
        critical_alerts_count=critical_alerts_count,
        footfall_trends=footfall_trends,
        recent_activity=recent_activity
    )


@dashboard_bp.route('/centres/select/<int:centre_id>')
@login_required
def select_centre(centre_id):
    """Switch the current active facility filter."""
    session['active_centre_id'] = centre_id
    next_page = request.referrer or url_for('dashboard.index')
    return redirect(next_page)
