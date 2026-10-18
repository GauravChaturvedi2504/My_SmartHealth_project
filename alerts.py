"""
alerts.py - Priority-Based Health Centre Alert Engine.

Monitors inventory shortages, expired stock, bed occupancy, doctor rosters,
and overdue sanitation tasks. Provides severity levels:
CRITICAL, HIGH, MEDIUM, INFO with user acknowledgment tracking.
"""

from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from database import get_db
from auth import login_required, validate_csrf
from inventory import evaluate_batch_status, get_expiry_threshold_days

alerts_bp = Blueprint('alerts', __name__, url_prefix='/alerts')


def sync_system_alerts(conn):
    """
    Scan real-time database state and insert or update priority alerts without
    overwriting previous acknowledgment history.
    """
    cursor = conn.cursor()
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    threshold_days = 30

    # 1. Check Medicine Batches
    cursor.execute("""
        SELECT b.*, c.name AS centre_name
        FROM medicine_batches b
        JOIN health_centres c ON b.centre_id = c.id
    """)
    batches = cursor.fetchall()

    for b in batches:
        status = evaluate_batch_status(b['expiry_date'], b['quantity'], b['min_stock_level'], threshold_days)
        batch_id = b['batch_id']
        c_id = b['centre_id']
        med_name = b['medicine_name']

        if status['is_expired']:
            alert_key = f"EXP-{batch_id}"
            cursor.execute("""
                INSERT INTO alerts (alert_key, centre_id, severity, category, title, message, created_at)
                VALUES (?, ?, 'CRITICAL', 'inventory', ?, ?, ?)
                ON CONFLICT(alert_key) DO UPDATE SET
                    message = excluded.message
            """, (
                alert_key, c_id,
                f"EXPIRED MEDICINE: {med_name}",
                f"Batch {batch_id} ({b['batch_number']}) expired on {b['expiry_date']}. Immediate segregation and safe disposal required.",
                now_str
            ))
        elif status['is_low_stock']:
            alert_key = f"LOW-{batch_id}"
            sev = 'CRITICAL' if b['quantity'] <= 0 else 'HIGH'
            cursor.execute("""
                INSERT INTO alerts (alert_key, centre_id, severity, category, title, message, created_at)
                VALUES (?, ?, ?, 'inventory', ?, ?, ?)
                ON CONFLICT(alert_key) DO UPDATE SET
                    severity = excluded.severity,
                    message = excluded.message
            """, (
                alert_key, c_id, sev,
                f"STOCK SHORTAGE: {med_name}",
                f"Only {b['quantity']} {b['unit']} remaining (minimum safe threshold is {b['min_stock_level']}). Restock requisition recommended.",
                now_str
            ))
        elif status['is_near_expiry']:
            alert_key = f"NEAR-EXP-{batch_id}"
            cursor.execute("""
                INSERT INTO alerts (alert_key, centre_id, severity, category, title, message, created_at)
                VALUES (?, ?, 'MEDIUM', 'inventory', ?, ?, ?)
                ON CONFLICT(alert_key) DO UPDATE SET
                    message = excluded.message
            """, (
                alert_key, c_id,
                f"EXPIRING SOON: {med_name}",
                f"Batch {batch_id} expires in {status['days_to_expiry']} days ({b['expiry_date']}). Prioritize FEFO dispensing.",
                now_str
            ))

    # 2. Check Overdue Housekeeping Tasks
    cursor.execute("""
        SELECT t.*, c.name AS centre_name
        FROM cleaning_tasks t
        JOIN health_centres c ON t.centre_id = c.id
        WHERE t.status != 'Completed'
    """)
    tasks = cursor.fetchall()
    for t in tasks:
        try:
            sched_dt = datetime.strptime(t['scheduled_time'], "%Y-%m-%d %H:%M")
            if sched_dt < now:
                mins_overdue = int((now - sched_dt).total_seconds() / 60)
                alert_key = f"TASK-{t['id']}-OVERDUE"
                cursor.execute("""
                    INSERT INTO alerts (alert_key, centre_id, severity, category, title, message, created_at)
                    VALUES (?, ?, 'MEDIUM', 'cleaning', ?, ?, ?)
                    ON CONFLICT(alert_key) DO UPDATE SET
                        message = excluded.message
                """, (
                    alert_key, t['centre_id'],
                    f"OVERDUE CLEANING: {t['area']}",
                    f"Sanitation task for {t['area']} is overdue by {mins_overdue} minutes (scheduled at {t['scheduled_time']}).",
                    now_str
                ))
        except Exception:
            pass

    # 3. Check Beds Out of Service
    cursor.execute("""
        SELECT b.*, c.name AS centre_name
        FROM beds b
        JOIN health_centres c ON b.centre_id = c.id
        WHERE b.status = 'Out of Service'
    """)
    oos_beds = cursor.fetchall()
    for b in oos_beds:
        alert_key = f"BED-{b['id']}-OOS"
        cursor.execute("""
            INSERT INTO alerts (alert_key, centre_id, severity, category, title, message, created_at)
            VALUES (?, ?, 'INFO', 'beds', ?, ?, ?)
            ON CONFLICT(alert_key) DO UPDATE SET
                message = excluded.message
        """, (
            alert_key, b['centre_id'],
            f"BED OUT OF SERVICE: {b['bed_number']}",
            f"Bed {b['bed_number']} ({b['ward']}) is out of service. Notes: {b['notes'] or 'Undergoing inspection'}.",
            now_str
        ))

    # 4. Check Overdue Equipment Allotments
    cursor.execute("""
        SELECT a.*, e.equipment_code, e.name AS equipment_name, c.name AS centre_name
        FROM equipment_allotments a
        JOIN equipment_items e ON a.equipment_id = e.id
        JOIN health_centres c ON a.centre_id = c.id
        WHERE a.status = 'Active'
    """)
    allotments = cursor.fetchall()
    for a in allotments:
        try:
            exp_dt = datetime.strptime(a['expected_return_time'][:16], "%Y-%m-%d %H:%M")
            if exp_dt < now:
                mins_over = int((now - exp_dt).total_seconds() / 60)
                alert_key = f"EQ-OVERDUE-{a['id']}"
                cursor.execute("""
                    INSERT INTO alerts (alert_key, centre_id, severity, category, title, message, created_at)
                    VALUES (?, ?, 'HIGH', 'equipment', ?, ?, ?)
                    ON CONFLICT(alert_key) DO UPDATE SET
                        message = excluded.message
                """, (
                    alert_key, a['centre_id'],
                    f"OVERDUE EQUIPMENT: {a['equipment_code']}",
                    f"Equipment {a['equipment_code']} ({a['equipment_name']}) allotted to Visit {a['patient_visit_id']} in {a['ward']} is overdue by {mins_over} minutes (scheduled return: {a['expected_return_time']}).",
                    now_str
                ))
        except Exception:
            pass

    # 5. Check Critical Maintenance Work Orders
    cursor.execute("""
        SELECT w.*, a.asset_tag, a.name AS asset_name, c.name AS centre_name
        FROM maintenance_work_orders w
        JOIN facility_assets a ON w.asset_id = a.id
        JOIN health_centres c ON w.centre_id = c.id
        WHERE w.status IN ('Open', 'In Progress') AND w.priority IN ('CRITICAL', 'HIGH')
    """)
    work_orders = cursor.fetchall()
    for w in work_orders:
        alert_key = f"WO-{w['id']}-CRITICAL"
        cursor.execute("""
            INSERT INTO alerts (alert_key, centre_id, severity, category, title, message, created_at)
            VALUES (?, ?, ?, 'assets', ?, ?, ?)
            ON CONFLICT(alert_key) DO UPDATE SET
                message = excluded.message
        """, (
            alert_key, w['centre_id'], w['priority'],
            f"INFRASTRUCTURE BREAKDOWN: {w['asset_name']}",
            f"Critical work order {w['work_order_code']} ({w['asset_tag']}): {w['issue_description']}",
            now_str
        ))

    conn.commit()


@alerts_bp.route('/')
@login_required
def index():
    """Display priority alerts list with severity filtering and acknowledgment options."""
    centre_id = request.args.get('centre_id', type=int)
    severity_filter = request.args.get('severity', 'all').upper()
    ack_filter = request.args.get('ack', 'all')

    if centre_id is None and session.get('active_centre_id'):
        centre_id = session.get('active_centre_id')

    conn = get_db()
    sync_system_alerts(conn)
    cursor = conn.cursor()

    # Centres
    cursor.execute("SELECT id, name, code FROM health_centres ORDER BY name")
    centres = cursor.fetchall()

    query = """
        SELECT a.*, c.name AS centre_name, c.code AS centre_code
        FROM alerts a
        LEFT JOIN health_centres c ON a.centre_id = c.id
        WHERE 1=1
    """
    params = []

    if centre_id and centre_id > 0:
        query += " AND a.centre_id = ?"
        params.append(centre_id)

    if severity_filter != 'ALL':
        query += " AND a.severity = ?"
        params.append(severity_filter)

    if ack_filter == 'unacknowledged':
        query += " AND a.is_acknowledged = 0"
    elif ack_filter == 'acknowledged':
        query += " AND a.is_acknowledged = 1"

    # Order by severity priority, then unacknowledged first, then date
    query += """
        ORDER BY
            a.is_acknowledged ASC,
            CASE a.severity
                WHEN 'CRITICAL' THEN 1
                WHEN 'HIGH' THEN 2
                WHEN 'MEDIUM' THEN 3
                WHEN 'INFO' THEN 4
                ELSE 5
            END,
            a.created_at DESC
    """
    cursor.execute(query, params)
    alerts_list = cursor.fetchall()

    # Count statistics
    cursor.execute("""
        SELECT
            SUM(CASE WHEN severity = 'CRITICAL' AND is_acknowledged = 0 THEN 1 ELSE 0 END) AS unack_critical,
            SUM(CASE WHEN severity = 'HIGH' AND is_acknowledged = 0 THEN 1 ELSE 0 END) AS unack_high,
            SUM(CASE WHEN severity = 'MEDIUM' AND is_acknowledged = 0 THEN 1 ELSE 0 END) AS unack_medium,
            SUM(CASE WHEN is_acknowledged = 0 THEN 1 ELSE 0 END) AS total_unack
        FROM alerts
    """)
    stats = cursor.fetchone()
    conn.close()

    return render_template(
        'alerts/index.html',
        alerts=alerts_list,
        centres=centres,
        selected_centre_id=centre_id or 0,
        severity_filter=severity_filter,
        ack_filter=ack_filter,
        stats=stats
    )


@alerts_bp.route('/acknowledge/<int:alert_id>', methods=['POST'])
@login_required
def acknowledge(alert_id):
    """
    Acknowledge an alert to record staff awareness.
    Explicitly does NOT remove the underlying physical issue from the facility.
    """
    validate_csrf()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    username = session.get('username', 'staff')

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE alerts
        SET is_acknowledged = 1, acknowledged_by = ?, acknowledged_at = ?
        WHERE id = ?
    """, (username, now_str, alert_id))
    conn.commit()
    conn.close()

    flash("Alert marked as acknowledged. Note: Acknowledging registers staff awareness but does not resolve the physical condition.", "info")
    return redirect(request.referrer or url_for('alerts.index'))


@alerts_bp.route('/unacknowledge/<int:alert_id>', methods=['POST'])
@login_required
def unacknowledge(alert_id):
    """Reset an alert back to unacknowledged state."""
    validate_csrf()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE alerts
        SET is_acknowledged = 0, acknowledged_by = NULL, acknowledged_at = NULL
        WHERE id = ?
    """, (alert_id,))
    conn.commit()
    conn.close()

    flash("Alert reset to unacknowledged.", "secondary")
    return redirect(request.referrer or url_for('alerts.index'))
