"""
reports.py - Downloadable CSV Reports with Formula Injection Sanitization.

Generates CSV reports for:
1. Complete Medicine Inventory & Expiry Status
2. Critical Low-Stock Items
3. Stock Transaction & Audit History
4. Doctor Schedules & Confirmed Attendance
5. Bed Inventory & Occupancy Status
6. Aggregate Patient Footfall Summaries
7. Housekeeping & Sanitation Tasks

Includes CSV formula injection sanitization (protects against =, +, -, @ triggers).
"""

import csv
import io
from datetime import datetime
from flask import Blueprint, render_template, request, Response, session
from database import get_db
from auth import login_required
from inventory import evaluate_batch_status, get_expiry_threshold_days

reports_bp = Blueprint('reports', __name__, url_prefix='/reports')


def sanitize_csv_val(val):
    """
    Sanitize CSV field value to prevent CSV / Spreadsheet Formula Injection.
    If value begins with =, +, -, @, tab, or carriage return, prepend a single quote.
    """
    if val is None:
        return ""
    str_val = str(val)
    if str_val and str_val[0] in ('=', '+', '-', '@', '\t', '\r'):
        return f"'{str_val}"
    return str_val


def make_csv_response(rows, filename):
    """Generate a Flask downloadable CSV response from an iterable of row tuples."""
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)
    for row in rows:
        writer.writerow([sanitize_csv_val(col) for col in row])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@reports_bp.route('/')
@login_required
def index():
    """Render Reports Export Central page."""
    centre_id = request.args.get('centre_id', type=int)
    if centre_id is None and session.get('active_centre_id'):
        centre_id = session.get('active_centre_id')

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, code FROM health_centres ORDER BY name")
    centres = cursor.fetchall()
    conn.close()

    return render_template(
        'reports/index.html',
        centres=centres,
        selected_centre_id=centre_id or 0
    )


@reports_bp.route('/export/inventory.csv')
@login_required
def export_inventory():
    """Export complete medicine inventory and expiry status."""
    centre_id = request.args.get('centre_id', type=int)
    threshold_days = get_expiry_threshold_days()

    conn = get_db()
    cursor = conn.cursor()
    query = """
        SELECT b.*, c.name AS centre_name
        FROM medicine_batches b
        JOIN health_centres c ON b.centre_id = c.id
        WHERE 1=1
    """
    params = []
    if centre_id and centre_id > 0:
        query += " AND b.centre_id = ?"
        params.append(centre_id)
    query += " ORDER BY b.medicine_name ASC"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    headers = [
        "Batch ID", "Medicine Name", "Generic Name", "Batch Number", "Health Centre",
        "Recorded Quantity", "Usable Quantity", "Unit", "Min Stock Level", "Expiry Date",
        "Days To Expiry", "Expiry Status", "Stock Status", "Storage Location", "Last Updated"
    ]
    csv_data = [headers]

    for r in rows:
        st = evaluate_batch_status(r['expiry_date'], r['quantity'], r['min_stock_level'], threshold_days)
        exp_status = "EXPIRED" if st['is_expired'] else ("NEAR EXPIRY" if st['is_near_expiry'] else "VALID")
        stock_status = "OUT OF STOCK" if st['is_out_of_stock'] else ("LOW STOCK" if st['is_low_stock'] else "ADEQUATE")

        csv_data.append([
            r['batch_id'], r['medicine_name'], r['generic_name'], r['batch_number'], r['centre_name'],
            r['quantity'], st['usable_quantity'], r['unit'], r['min_stock_level'], r['expiry_date'],
            st['days_to_expiry'], exp_status, stock_status, r['storage_location'], r['last_updated']
        ])

    filename = f"smarthealth_inventory_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return make_csv_response(csv_data, filename)


@reports_bp.route('/export/low-stock.csv')
@login_required
def export_low_stock():
    """Export items at or below minimum required stock level."""
    centre_id = request.args.get('centre_id', type=int)
    threshold_days = get_expiry_threshold_days()

    conn = get_db()
    cursor = conn.cursor()
    query = """
        SELECT b.*, c.name AS centre_name
        FROM medicine_batches b
        JOIN health_centres c ON b.centre_id = c.id
        WHERE b.quantity <= b.min_stock_level
    """
    params = []
    if centre_id and centre_id > 0:
        query += " AND b.centre_id = ?"
        params.append(centre_id)
    query += " ORDER BY b.quantity ASC"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    headers = [
        "Batch ID", "Medicine Name", "Generic Name", "Health Centre",
        "Available Qty", "Min Required Qty", "Unit", "Deficit", "Storage Location"
    ]
    csv_data = [headers]

    for r in rows:
        deficit = max(0, r['min_stock_level'] - r['quantity'])
        csv_data.append([
            r['batch_id'], r['medicine_name'], r['generic_name'], r['centre_name'],
            r['quantity'], r['min_stock_level'], r['unit'], deficit, r['storage_location']
        ])

    filename = f"smarthealth_low_stock_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return make_csv_response(csv_data, filename)


@reports_bp.route('/export/audit-history.csv')
@login_required
def export_audit_history():
    """Export complete immutable stock transaction audit log."""
    centre_id = request.args.get('centre_id', type=int)

    conn = get_db()
    cursor = conn.cursor()
    query = """
        SELECT a.*, c.name AS centre_name
        FROM stock_audit_log a
        JOIN health_centres c ON a.centre_id = c.id
        WHERE 1=1
    """
    params = []
    if centre_id and centre_id > 0:
        query += " AND a.centre_id = ?"
        params.append(centre_id)
    query += " ORDER BY a.timestamp DESC"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    headers = [
        "Audit Log ID", "Timestamp", "Health Centre", "Medicine Name", "Batch ID",
        "Transaction Type", "Previous Qty", "Change Qty", "Updated Qty", "Staff Username", "Reason / Notes"
    ]
    csv_data = [headers]

    for r in rows:
        csv_data.append([
            r['id'], r['timestamp'], r['centre_name'], r['medicine_name'], r['batch_id'],
            r['transaction_type'], r['previous_quantity'], r['change_quantity'],
            r['updated_quantity'], r['staff_username'], r['reason']
        ])

    filename = f"smarthealth_audit_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return make_csv_response(csv_data, filename)


@reports_bp.route('/export/doctors.csv')
@login_required
def export_doctors():
    """Export doctor rosters, schedules, and attendance."""
    centre_id = request.args.get('centre_id', type=int)

    conn = get_db()
    cursor = conn.cursor()
    query = """
        SELECT d.*, c.name AS centre_name
        FROM doctors d
        JOIN health_centres c ON d.centre_id = c.id
        WHERE 1=1
    """
    params = []
    if centre_id and centre_id > 0:
        query += " AND d.centre_id = ?"
        params.append(centre_id)
    query += " ORDER BY d.name ASC"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    headers = [
        "Doctor ID", "Doctor Name", "Specialty", "Health Centre", "Contact Phone",
        "Scheduled Days", "Duty Start Time", "Duty End Time", "Confirmed Status",
        "Leave Start Date", "Leave End Date", "Leave Reason", "Last Status Update", "Updated By"
    ]
    csv_data = [headers]

    for r in rows:
        csv_data.append([
            r['id'], r['name'], r['specialty'], r['centre_name'], r['contact_phone'],
            r['scheduled_days'], r['duty_start_time'], r['duty_end_time'], r['current_status'],
            r['leave_start_date'], r['leave_end_date'], r['leave_reason'],
            r['last_status_update'], r['updated_by']
        ])

    filename = f"smarthealth_doctors_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return make_csv_response(csv_data, filename)


@reports_bp.route('/export/beds.csv')
@login_required
def export_beds():
    """Export bed inventory and occupancy report."""
    centre_id = request.args.get('centre_id', type=int)

    conn = get_db()
    cursor = conn.cursor()
    query = """
        SELECT b.*, c.name AS centre_name
        FROM beds b
        JOIN health_centres c ON b.centre_id = c.id
        WHERE 1=1
    """
    params = []
    if centre_id and centre_id > 0:
        query += " AND b.centre_id = ?"
        params.append(centre_id)
    query += " ORDER BY c.name ASC, b.ward ASC, b.bed_number ASC"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    headers = ["Bed ID", "Bed Number", "Health Centre", "Ward", "Current Status", "Patient Identifier", "Last Updated", "Notes"]
    csv_data = [headers]

    for r in rows:
        csv_data.append([
            r['id'], r['bed_number'], r['centre_name'], r['ward'], r['status'],
            r['patient_identifier'], r['last_updated'], r['notes']
        ])

    filename = f"smarthealth_beds_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return make_csv_response(csv_data, filename)


@reports_bp.route('/export/footfall.csv')
@login_required
def export_footfall():
    """Export patient footfall summaries."""
    centre_id = request.args.get('centre_id', type=int)

    conn = get_db()
    cursor = conn.cursor()
    query = """
        SELECT f.*, c.name AS centre_name
        FROM patient_footfall f
        JOIN health_centres c ON f.centre_id = c.id
        WHERE 1=1
    """
    params = []
    if centre_id and centre_id > 0:
        query += " AND f.centre_id = ?"
        params.append(centre_id)
    query += " ORDER BY f.record_date DESC"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    headers = [
        "Record ID", "Date", "Health Centre", "Outpatients (OPD)",
        "Emergency Admissions", "Referrals", "Total Footfall", "Recorded By", "Notes"
    ]
    csv_data = [headers]

    for r in rows:
        csv_data.append([
            r['id'], r['record_date'], r['centre_name'], r['outpatient_count'],
            r['emergency_count'], r['referral_count'], r['total_count'],
            r['recorded_by'], r['notes']
        ])

    filename = f"smarthealth_footfall_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return make_csv_response(csv_data, filename)


@reports_bp.route('/export/cleaning.csv')
@login_required
def export_cleaning():
    """Export housekeeping tasks and sanitation logs."""
    centre_id = request.args.get('centre_id', type=int)

    conn = get_db()
    cursor = conn.cursor()
    query = """
        SELECT t.*, c.name AS centre_name, s.name AS staff_name
        FROM cleaning_tasks t
        JOIN health_centres c ON t.centre_id = c.id
        LEFT JOIN cleaning_staff s ON t.staff_id = s.id
        WHERE 1=1
    """
    params = []
    if centre_id and centre_id > 0:
        query += " AND t.centre_id = ?"
        params.append(centre_id)
    query += " ORDER BY t.scheduled_time DESC"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    headers = [
        "Task ID", "Health Centre", "Area", "Assigned Staff", "Scheduled Time",
        "Current Status", "Last Completed Time", "Notes"
    ]
    csv_data = [headers]

    for r in rows:
        csv_data.append([
            r['id'], r['centre_name'], r['area'], r['staff_name'] or "Unassigned",
            r['scheduled_time'], r['status'], r['last_completed_time'], r['notes']
        ])

    filename = f"smarthealth_cleaning_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return make_csv_response(csv_data, filename)


@reports_bp.route('/export/equipment.csv')
@login_required
def export_equipment():
    """Export equipment allotment history and current inventory."""
    centre_id = request.args.get('centre_id', type=int)

    conn = get_db()
    cursor = conn.cursor()
    query = """
        SELECT a.*, e.equipment_code, e.name AS equipment_name, e.category,
               c.name AS centre_name
        FROM equipment_allotments a
        JOIN equipment_items e ON a.equipment_id = e.id
        JOIN health_centres c ON a.centre_id = c.id
        WHERE 1=1
    """
    params = []
    if centre_id and centre_id > 0:
        query += " AND a.centre_id = ?"
        params.append(centre_id)
    query += " ORDER BY a.issue_time DESC"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    headers = [
        "Allotment ID", "Asset Tag", "Equipment Name", "Category", "Centre",
        "Ward", "Patient/Visit ID", "Patient Name", "Issue Time", "Expected Return Time",
        "Issuing Staff", "Actual Return Time", "Receiving Staff", "Return Condition",
        "Status", "Notes"
    ]
    csv_data = [headers]

    for r in rows:
        csv_data.append([
            r['id'], r['equipment_code'], r['equipment_name'], r['category'],
            r['centre_name'], r['ward'], r['patient_visit_id'], r['patient_name'] or '',
            r['issue_time'], r['expected_return_time'], r['issuing_staff'],
            r['actual_return_time'] or '', r['receiving_staff'] or '',
            r['return_condition'] or '', r['status'], r['return_notes'] or ''
        ])

    filename = f"smarthealth_equipment_allotments_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return make_csv_response(csv_data, filename)


@reports_bp.route('/export/ambulances.csv')
@login_required
def export_ambulances():
    """Export ambulance fleet and dispatch trip log."""
    centre_id = request.args.get('centre_id', type=int)

    conn = get_db()
    cursor = conn.cursor()
    query = """
        SELECT t.*, a.vehicle_code, a.registration_number, a.ambulance_type,
               c.name AS centre_name
        FROM ambulance_trips t
        JOIN ambulances a ON t.ambulance_id = a.id
        JOIN health_centres c ON t.centre_id = c.id
        WHERE 1=1
    """
    params = []
    if centre_id and centre_id > 0:
        query += " AND t.centre_id = ?"
        params.append(centre_id)
    query += " ORDER BY t.departure_time DESC"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    headers = [
        "Trip ID", "Vehicle Tag", "Registration No", "Ambulance Type", "Centre",
        "Trip Purpose", "Patient Identifier", "Destination", "Departure Time",
        "Expected Return", "Actual Return", "Driver Name", "Paramedic Staff",
        "Trip Status", "Notes"
    ]
    csv_data = [headers]

    for r in rows:
        csv_data.append([
            r['id'], r['vehicle_code'], r['registration_number'], r['ambulance_type'],
            r['centre_name'], r['trip_purpose'], r['patient_identifier'] or '',
            r['destination'], r['departure_time'], r['expected_return_time'] or '',
            r['actual_return_time'] or '', r['driver_name'], r['paramedic_staff'] or '',
            r['status'], r['notes'] or ''
        ])

    filename = f"smarthealth_ambulance_trips_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return make_csv_response(csv_data, filename)


@reports_bp.route('/export/assets.csv')
@login_required
def export_assets():
    """Export facility assets and maintenance work orders."""
    centre_id = request.args.get('centre_id', type=int)

    conn = get_db()
    cursor = conn.cursor()
    query = """
        SELECT w.*, fa.asset_tag, fa.name AS asset_name, fa.category, fa.location,
               c.name AS centre_name
        FROM maintenance_work_orders w
        JOIN facility_assets fa ON w.asset_id = fa.id
        JOIN health_centres c ON w.centre_id = c.id
        WHERE 1=1
    """
    params = []
    if centre_id and centre_id > 0:
        query += " AND w.centre_id = ?"
        params.append(centre_id)
    query += " ORDER BY w.reported_at DESC"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    headers = [
        "Work Order Code", "Asset Tag", "Asset Name", "Category", "Location",
        "Centre", "Priority", "Issue Description", "Reported By", "Reported At",
        "Assigned Technician", "Status", "Estimated Cost", "Actual Cost",
        "Resolved At", "Resolved By", "Resolution Notes"
    ]
    csv_data = [headers]

    for r in rows:
        csv_data.append([
            r['work_order_code'], r['asset_tag'], r['asset_name'], r['category'],
            r['location'], r['centre_name'], r['priority'], r['issue_description'],
            r['reported_by'], r['reported_at'], r['assigned_technician'] or '',
            r['status'], r['estimated_cost'] or 0.0, r['actual_cost'] or 0.0,
            r['resolved_at'] or '', r['resolved_by'] or '', r['resolution_notes'] or ''
        ])

    filename = f"smarthealth_facility_work_orders_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return make_csv_response(csv_data, filename)
