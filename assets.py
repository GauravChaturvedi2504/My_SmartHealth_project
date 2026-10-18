"""
assets.py - Facility Equipment Assets & Maintenance Work Orders.

Tracks critical facility infrastructure:
- Backup Diesel Generators, Cold Chain Vaccine Refrigerators, RO Water Plants, Medical Gas, HVAC / AC units
- Asset tags, physical locations, operational condition, and scheduled preventive maintenance
- Maintenance Work Orders: fault reports, priority tiers (CRITICAL, HIGH, MEDIUM, LOW),
  assigned technicians, repair costs, resolution timestamps, and audit history.
"""

from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from database import get_db
from auth import login_required, validate_csrf

assets_bp = Blueprint('assets', __name__, url_prefix='/assets')


@assets_bp.route('/')
@login_required
def index():
    """Display facility asset directory, open maintenance work orders, and service alerts."""
    centre_id = request.args.get('centre_id', type=int)
    view_tab = request.args.get('tab', 'assets')  # 'assets' or 'work_orders'
    priority_filter = request.args.get('priority', 'all')
    status_filter = request.args.get('status', 'all')

    if centre_id is None and session.get('active_centre_id'):
        centre_id = session.get('active_centre_id')

    today_str = datetime.now().strftime("%Y-%m-%d")
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id, name, code FROM health_centres ORDER BY name")
    centres = cursor.fetchall()

    # 1. Fetch Facility Assets
    asset_query = """
        SELECT a.*, c.name AS centre_name, c.code AS centre_code,
               (SELECT COUNT(*) FROM maintenance_work_orders w WHERE w.asset_id = a.id AND w.status IN ('Open', 'In Progress')) AS open_orders_count
        FROM facility_assets a
        JOIN health_centres c ON a.centre_id = c.id
        WHERE 1=1
    """
    asset_params = []
    if centre_id and centre_id > 0:
        asset_query += " AND a.centre_id = ?"
        asset_params.append(centre_id)

    if status_filter != 'all':
        asset_query += " AND a.condition_status = ?"
        asset_params.append(status_filter)

    asset_query += " ORDER BY c.name ASC, a.category ASC, a.asset_tag ASC"
    cursor.execute(asset_query, asset_params)
    raw_assets = cursor.fetchall()

    assets_list = []
    operational_count = 0
    needs_attn_count = 0
    under_repair_count = 0
    service_overdue_count = 0

    for r in raw_assets:
        item = dict(r)
        if item['condition_status'] == 'Operational':
            operational_count += 1
        elif item['condition_status'] == 'Needs Attention':
            needs_attn_count += 1
        elif item['condition_status'] in ['Under Repair', 'Decommissioned']:
            under_repair_count += 1

        is_overdue = item['next_service_due'] < today_str
        item['is_service_overdue'] = is_overdue
        if is_overdue:
            service_overdue_count += 1

        assets_list.append(item)

    # 2. Fetch Maintenance Work Orders
    wo_query = """
        SELECT w.*, a.asset_tag, a.name AS asset_name, a.location AS asset_location,
               c.name AS centre_name
        FROM maintenance_work_orders w
        JOIN facility_assets a ON w.asset_id = a.id
        JOIN health_centres c ON w.centre_id = c.id
        WHERE 1=1
    """
    wo_params = []
    if centre_id and centre_id > 0:
        wo_query += " AND w.centre_id = ?"
        wo_params.append(centre_id)

    if priority_filter != 'all':
        wo_query += " AND w.priority = ?"
        wo_params.append(priority_filter)

    wo_query += """
        ORDER BY
            CASE w.status WHEN 'Open' THEN 1 WHEN 'In Progress' THEN 2 ELSE 3 END,
            CASE w.priority WHEN 'CRITICAL' THEN 1 WHEN 'HIGH' THEN 2 WHEN 'MEDIUM' THEN 3 ELSE 4 END,
            w.reported_at DESC
        LIMIT 100
    """
    cursor.execute(wo_query, wo_params)
    raw_work_orders = cursor.fetchall()

    work_orders = []
    open_wo_count = 0
    in_progress_wo_count = 0
    resolved_wo_count = 0
    critical_wo_count = 0

    for r in raw_work_orders:
        item = dict(r)
        if item['status'] == 'Open':
            open_wo_count += 1
            if item['priority'] == 'CRITICAL':
                critical_wo_count += 1
        elif item['status'] == 'In Progress':
            in_progress_wo_count += 1
            if item['priority'] == 'CRITICAL':
                critical_wo_count += 1
        elif item['status'] == 'Resolved':
            resolved_wo_count += 1

        work_orders.append(item)

    conn.close()

    return render_template(
        'assets/index.html',
        assets=assets_list,
        work_orders=work_orders,
        centres=centres,
        selected_centre_id=centre_id or 0,
        view_tab=view_tab,
        priority_filter=priority_filter,
        status_filter=status_filter,
        operational_count=operational_count,
        needs_attn_count=needs_attn_count,
        under_repair_count=under_repair_count,
        service_overdue_count=service_overdue_count,
        open_wo_count=open_wo_count,
        in_progress_wo_count=in_progress_wo_count,
        resolved_wo_count=resolved_wo_count,
        critical_wo_count=critical_wo_count
    )


@assets_bp.route('/create-work-order', methods=['POST'])
@login_required
def create_work_order():
    """Report an asset fault and create a maintenance work order."""
    validate_csrf()
    asset_id = request.form.get('asset_id', type=int)
    priority = request.form.get('priority', 'MEDIUM').strip()
    issue_description = request.form.get('issue_description', '').strip()
    assigned_technician = request.form.get('assigned_technician', '').strip() or None
    estimated_cost = request.form.get('estimated_cost', type=float) or 0.0

    if not asset_id or not issue_description:
        flash("Asset selection and fault description are required.", "danger")
        return redirect(request.referrer or url_for('assets.index'))

    valid_priorities = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']
    if priority not in valid_priorities:
        priority = 'MEDIUM'

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM facility_assets WHERE id = ?", (asset_id,))
    asset = cursor.fetchone()

    if not asset:
        conn.close()
        flash("Asset not found.", "warning")
        return redirect(url_for('assets.index'))

    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    wo_code = f"WO-{now.strftime('%Y%m%d')}-{asset_id:02d}-{int(now.timestamp()) % 1000:03d}"
    username = session.get('username', 'staff')

    try:
        # Create work order
        cursor.execute("""
            INSERT INTO maintenance_work_orders (
                work_order_code, asset_id, centre_id, priority, issue_description,
                reported_by, reported_at, assigned_technician, status, estimated_cost
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Open', ?)
        """, (wo_code, asset_id, asset['centre_id'], priority, issue_description, username, now_str, assigned_technician, estimated_cost))

        # If priority is CRITICAL or HIGH, update asset condition to Under Repair or Needs Attention
        new_asset_cond = 'Under Repair' if priority == 'CRITICAL' else 'Needs Attention'
        cursor.execute("""
            UPDATE facility_assets
            SET condition_status = ?
            WHERE id = ?
        """, (new_asset_cond, asset_id))

        conn.commit()
        flash(f"Work order {wo_code} created successfully for {asset['name']} ({asset['asset_tag']}).", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error creating work order: {str(e)}", "danger")
    finally:
        conn.close()

    return redirect(url_for('assets.index', tab='work_orders', centre_id=asset['centre_id']))


@assets_bp.route('/resolve-work-order/<int:order_id>', methods=['POST'])
@login_required
def resolve_work_order(order_id):
    """Mark a maintenance work order resolved and restore asset operational status."""
    validate_csrf()
    new_status = request.form.get('status', 'Resolved').strip()
    actual_cost = request.form.get('actual_cost', type=float) or 0.0
    resolution_notes = request.form.get('resolution_notes', '').strip()
    asset_condition = request.form.get('asset_condition', 'Operational').strip()

    valid_statuses = ['In Progress', 'Resolved', 'Cancelled']
    if new_status not in valid_statuses:
        new_status = 'Resolved'

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    username = session.get('username', 'staff')

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM maintenance_work_orders WHERE id = ?", (order_id,))
    order = cursor.fetchone()

    if not order:
        conn.close()
        flash("Work order not found.", "warning")
        return redirect(url_for('assets.index'))

    try:
        resolved_at = now_str if new_status == 'Resolved' else None
        resolved_by = username if new_status == 'Resolved' else None

        cursor.execute("""
            UPDATE maintenance_work_orders
            SET status = ?,
                actual_cost = ?,
                resolution_notes = ?,
                resolved_at = COALESCE(?, resolved_at),
                resolved_by = COALESCE(?, resolved_by)
            WHERE id = ?
        """, (new_status, actual_cost, resolution_notes, resolved_at, resolved_by, order_id))

        # If work order resolved, restore asset condition
        if new_status == 'Resolved':
            cursor.execute("""
                UPDATE facility_assets
                SET condition_status = ?, last_service_date = ?
                WHERE id = ?
            """, (asset_condition, now_str[:10], order['asset_id']))

        conn.commit()
        flash(f"Work order {order['work_order_code']} updated to '{new_status}'.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error updating work order: {str(e)}", "danger")
    finally:
        conn.close()

    return redirect(url_for('assets.index', tab='work_orders', centre_id=order['centre_id']))


@assets_bp.route('/add-asset', methods=['POST'])
@login_required
def add_asset():
    """Register a new facility asset item."""
    validate_csrf()
    asset_tag = request.form.get('asset_tag', '').strip().upper()
    name = request.form.get('name', '').strip()
    category = request.form.get('category', 'Power & Electrical').strip()
    centre_id = request.form.get('centre_id', type=int)
    location = request.form.get('location', '').strip()
    next_service_due = request.form.get('next_service_due', '').strip()
    vendor = request.form.get('vendor_support', '').strip()
    serial = request.form.get('model_serial', '').strip()

    if not asset_tag or not name or not centre_id or not next_service_due:
        flash("Asset Tag, Name, Health Facility, and Next Service Date are mandatory.", "danger")
        return redirect(request.referrer or url_for('assets.index'))

    now_date = datetime.now().strftime("%Y-%m-%d")
    conn = get_db()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO facility_assets (
                asset_tag, name, category, centre_id, location, condition_status,
                installation_date, next_service_due, model_serial, vendor_support
            ) VALUES (?, ?, ?, ?, ?, 'Operational', ?, ?, ?, ?)
        """, (asset_tag, name, category, centre_id, location, now_date, next_service_due, serial, vendor))
        conn.commit()
        flash(f"Asset '{name}' ({asset_tag}) registered successfully.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error registering asset (Tag must be unique): {str(e)}", "danger")
    finally:
        conn.close()

    return redirect(url_for('assets.index', centre_id=centre_id))
