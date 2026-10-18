"""
equipment.py - Patient Equipment Allotment & Return Tracking.

Manages reusable patient transport equipment (wheelchairs, stretchers, IV stands, oxygen trolleys):
- Unique asset IDs and QR labels (non-sensitive payload)
- Allotment by Patient / Visit ID, Ward, Issue Time, and Expected Return
- Overdue tracking and alert synchronization
- Return condition inspection (Good, Needs Sanitization, Needs Repair, Damaged)
- Strict duplicate-allotment prevention (single-holder lock)
- Blocking allotment of damaged or maintenance equipment
- Full allotment, return, and maintenance audit history
"""

import io
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, jsonify, session
import qrcode
from database import get_db
from auth import login_required, validate_csrf

equipment_bp = Blueprint('equipment', __name__, url_prefix='/equipment')


def evaluate_allotment_overdue(expected_return_str, actual_return_str=None):
    """Return True if expected_return_time is in the past and actual_return_time is None."""
    if actual_return_str:
        return False
    try:
        now = datetime.now()
        expected_dt = datetime.strptime(expected_return_str[:16], "%Y-%m-%d %H:%M")
        return expected_dt < now
    except Exception:
        return False


@equipment_bp.route('/')
@login_required
def index():
    """Display active equipment allotments, equipment inventory, and overdue trackers."""
    centre_id = request.args.get('centre_id', type=int)
    view_tab = request.args.get('tab', 'allotments')  # 'allotments' or 'inventory' or 'history'
    status_filter = request.args.get('status', 'all')

    if centre_id is None and session.get('active_centre_id'):
        centre_id = session.get('active_centre_id')

    now = datetime.now()
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id, name, code FROM health_centres ORDER BY name")
    centres = cursor.fetchall()

    # 1. Fetch Allotments
    allot_query = """
        SELECT a.*, e.equipment_code, e.name AS equipment_name, e.category,
               c.name AS centre_name, c.code AS centre_code
        FROM equipment_allotments a
        JOIN equipment_items e ON a.equipment_id = e.id
        JOIN health_centres c ON a.centre_id = c.id
        WHERE 1=1
    """
    allot_params = []
    if centre_id and centre_id > 0:
        allot_query += " AND a.centre_id = ?"
        allot_params.append(centre_id)

    if status_filter == 'active':
        allot_query += " AND a.status = 'Active'"
    elif status_filter == 'returned':
        allot_query += " AND a.status = 'Returned'"

    allot_query += " ORDER BY a.issue_time DESC LIMIT 150"
    cursor.execute(allot_query, allot_params)
    raw_allotments = cursor.fetchall()

    allotments = []
    active_count = 0
    overdue_count = 0
    returned_count = 0

    for r in raw_allotments:
        item = dict(r)
        is_overdue = evaluate_allotment_overdue(item['expected_return_time'], item['actual_return_time'])
        item['is_overdue'] = is_overdue

        if item['status'] == 'Active':
            active_count += 1
            if is_overdue:
                overdue_count += 1
        elif item['status'] == 'Returned':
            returned_count += 1

        if status_filter == 'overdue' and not is_overdue:
            continue

        allotments.append(item)

    # 2. Fetch Equipment Items Inventory
    item_query = """
        SELECT e.*, c.name AS centre_name,
               (SELECT a.patient_visit_id FROM equipment_allotments a WHERE a.equipment_id = e.id AND a.status = 'Active' LIMIT 1) AS current_holder_visit_id,
               (SELECT a.expected_return_time FROM equipment_allotments a WHERE a.equipment_id = e.id AND a.status = 'Active' LIMIT 1) AS active_expected_return
        FROM equipment_items e
        JOIN health_centres c ON e.centre_id = c.id
        WHERE 1=1
    """
    item_params = []
    if centre_id and centre_id > 0:
        item_query += " AND e.centre_id = ?"
        item_params.append(centre_id)

    item_query += " ORDER BY e.category ASC, e.equipment_code ASC"
    cursor.execute(item_query, item_params)
    raw_items = cursor.fetchall()

    equipment_items = []
    avail_count = 0
    in_use_count = 0
    maint_count = 0
    damaged_count = 0

    for r in raw_items:
        it = dict(r)
        if it['current_status'] == 'Available':
            avail_count += 1
        elif it['current_status'] == 'In Use':
            in_use_count += 1
        elif it['current_status'] == 'Under Maintenance':
            maint_count += 1
        elif it['current_status'] == 'Damaged':
            damaged_count += 1

        # Check if active allotment is overdue
        it['holder_is_overdue'] = False
        if it['active_expected_return']:
            it['holder_is_overdue'] = evaluate_allotment_overdue(it['active_expected_return'])

        equipment_items.append(it)

    # Available items for quick allotment dropdown
    available_equipment = [it for it in equipment_items if it['current_status'] == 'Available']

    conn.close()

    return render_template(
        'equipment/index.html',
        allotments=allotments,
        equipment_items=equipment_items,
        available_equipment=available_equipment,
        centres=centres,
        selected_centre_id=centre_id or 0,
        view_tab=view_tab,
        status_filter=status_filter,
        active_count=active_count,
        overdue_count=overdue_count,
        returned_count=returned_count,
        avail_count=avail_count,
        in_use_count=in_use_count,
        maint_count=maint_count,
        damaged_count=damaged_count
    )


@equipment_bp.route('/allot', methods=['POST'])
@login_required
def allot_equipment():
    """
    Allot a piece of equipment to a patient by visit ID.
    Enforces strict single-allotment validation:
    - Blocks duplicate allotments if equipment is already In Use.
    - Blocks allotment if equipment is Under Maintenance or Damaged.
    """
    validate_csrf()
    equipment_id = request.form.get('equipment_id', type=int)
    patient_visit_id = request.form.get('patient_visit_id', '').strip().upper()
    patient_name = request.form.get('patient_name', '').strip()
    ward = request.form.get('ward', '').strip()
    expected_return = request.form.get('expected_return_time', '').strip()
    notes = request.form.get('notes', '').strip()

    if not equipment_id or not patient_visit_id or not ward or not expected_return:
        flash("Equipment, Patient/Visit ID, Ward, and Expected Return Time are mandatory.", "danger")
        return redirect(request.referrer or url_for('equipment.index'))

    conn = get_db()
    cursor = conn.cursor()

    # Step 1: Check equipment status and availability
    cursor.execute("SELECT * FROM equipment_items WHERE id = ?", (equipment_id,))
    eq = cursor.fetchone()

    if not eq:
        conn.close()
        flash("Selected equipment item not found.", "warning")
        return redirect(url_for('equipment.index'))

    # Step 2: Block allotment if damaged or under maintenance
    if eq['current_status'] == 'Under Maintenance':
        conn.close()
        flash(f"Cannot allot {eq['equipment_code']}: item is currently Under Maintenance.", "danger")
        return redirect(request.referrer or url_for('equipment.index'))
    elif eq['current_status'] == 'Damaged':
        conn.close()
        flash(f"Cannot allot {eq['equipment_code']}: item is marked Damaged. Repair and sanitization required before use.", "danger")
        return redirect(request.referrer or url_for('equipment.index'))

    # Step 3: Prevent duplicate allotment using safe transaction check
    if eq['current_status'] == 'In Use':
        cursor.execute("SELECT patient_visit_id FROM equipment_allotments WHERE equipment_id = ? AND status = 'Active'", (equipment_id,))
        holder = cursor.fetchone()
        holder_tag = holder['patient_visit_id'] if holder else "another patient"
        conn.close()
        flash(f"Duplicate Allotment Blocked: {eq['equipment_code']} ({eq['name']}) is already in use by {holder_tag}. It must be returned first.", "danger")
        return redirect(request.referrer or url_for('equipment.index'))

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    issuing_staff = session.get('username', 'staff')

    try:
        # Insert allotment record
        cursor.execute("""
            INSERT INTO equipment_allotments (
                equipment_id, centre_id, patient_visit_id, patient_name, ward,
                issue_time, expected_return_time, issuing_staff, status, return_notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Active', ?)
        """, (equipment_id, eq['centre_id'], patient_visit_id, patient_name, ward, now_str, expected_return, issuing_staff, notes))

        # Update equipment status to 'In Use' and current ward
        cursor.execute("""
            UPDATE equipment_items
            SET current_status = 'In Use', current_ward = ?
            WHERE id = ?
        """, (ward, equipment_id))

        conn.commit()
        flash(f"Equipment {eq['equipment_code']} successfully allotted to Patient/Visit {patient_visit_id} in {ward}.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Database error during allotment: {str(e)}", "danger")
    finally:
        conn.close()

    return redirect(request.referrer or url_for('equipment.index'))


@equipment_bp.route('/return/<int:allotment_id>', methods=['POST'])
@login_required
def return_equipment(allotment_id):
    """
    Process equipment return:
    - Record actual return time, receiving staff, condition, and notes.
    - If condition is Good / Needs Sanitization, set equipment status back to Available.
    - If condition is Needs Repair or Damaged, update equipment status to Under Maintenance or Damaged.
    - Record entry into equipment_maintenance_history.
    """
    validate_csrf()
    condition = request.form.get('return_condition', 'Good').strip()
    return_notes = request.form.get('return_notes', '').strip()
    receiving_staff = session.get('username', 'staff')
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    valid_conditions = ['Good', 'Needs Sanitization', 'Needs Repair', 'Damaged']
    if condition not in valid_conditions:
        condition = 'Good'

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM equipment_allotments WHERE id = ?", (allotment_id,))
    allotment = cursor.fetchone()

    if not allotment:
        conn.close()
        flash("Allotment record not found.", "warning")
        return redirect(url_for('equipment.index'))

    if allotment['status'] == 'Returned':
        conn.close()
        flash("Equipment has already been returned.", "info")
        return redirect(url_for('equipment.index'))

    equipment_id = allotment['equipment_id']

    # Determine new status of equipment
    if condition in ['Needs Repair']:
        new_status = 'Under Maintenance'
    elif condition == 'Damaged':
        new_status = 'Damaged'
    else:
        new_status = 'Available'

    try:
        # 1. Update allotment record
        cursor.execute("""
            UPDATE equipment_allotments
            SET actual_return_time = ?,
                receiving_staff = ?,
                return_condition = ?,
                status = 'Returned',
                return_notes = ?
            WHERE id = ?
        """, (now_str, receiving_staff, condition, return_notes, allotment_id))

        # 2. Update equipment item status and sanitization time if good
        sanitized_time = now_str if condition in ['Good', 'Needs Sanitization'] else None
        cursor.execute("""
            UPDATE equipment_items
            SET current_status = ?,
                last_sanitized_time = COALESCE(?, last_sanitized_time),
                notes = ?
            WHERE id = ?
        """, (new_status, sanitized_time, f"Returned condition: {condition}. {return_notes}", equipment_id))

        # 3. Log return condition / maintenance history
        cursor.execute("""
            INSERT INTO equipment_maintenance_history (
                equipment_id, centre_id, action_type, performed_by, timestamp, details
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            equipment_id, allotment['centre_id'],
            'Sanitization' if condition == 'Needs Sanitization' else ('Damage Report' if condition == 'Damaged' else 'Return Inspection'),
            receiving_staff, now_str,
            f"Returned from Visit {allotment['patient_visit_id']}. Condition: {condition}. Notes: {return_notes}"
        ))

        conn.commit()
        flash(f"Equipment returned successfully. Condition: '{condition}'. Equipment status set to '{new_status}'.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error processing equipment return: {str(e)}", "danger")
    finally:
        conn.close()

    return redirect(request.referrer or url_for('equipment.index'))


@equipment_bp.route('/add-item', methods=['POST'])
@login_required
def add_item():
    """Register a new piece of patient transport equipment."""
    validate_csrf()
    equipment_code = request.form.get('equipment_code', '').strip().upper()
    name = request.form.get('name', '').strip()
    category = request.form.get('category', 'Wheelchair').strip()
    centre_id = request.form.get('centre_id', type=int)
    current_ward = request.form.get('current_ward', 'OPD Entrance').strip()
    notes = request.form.get('notes', '').strip()

    if not equipment_code or not name or not centre_id:
        flash("Equipment Asset ID, Name, and Facility are mandatory.", "danger")
        return redirect(request.referrer or url_for('equipment.index'))

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    conn = get_db()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO equipment_items (
                equipment_code, name, category, centre_id, current_ward, current_status, last_sanitized_time, notes
            ) VALUES (?, ?, ?, ?, ?, 'Available', ?, ?)
        """, (equipment_code, name, category, centre_id, current_ward, now_str, notes))
        conn.commit()
        flash(f"New equipment asset '{name}' ({equipment_code}) registered successfully.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error adding equipment (Code must be unique): {str(e)}", "danger")
    finally:
        conn.close()

    return redirect(url_for('equipment.index', tab='inventory', centre_id=centre_id))


@equipment_bp.route('/<equipment_code>/qr.png')
def qr_code_image(equipment_code):
    """
    Generate and serve a dynamic QR code PNG for equipment asset.
    Encodes safe asset payload: SMARTHEALTH:EQUIPMENT:<code_id>.
    Never includes patient or personal identifiers.
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT equipment_code, name FROM equipment_items WHERE equipment_code = ?", (equipment_code,))
    item = cursor.fetchone()
    conn.close()

    if not item:
        payload = f"SMARTHEALTH:EQUIPMENT:{equipment_code}"
    else:
        payload = f"SMARTHEALTH:EQUIPMENT:{item['equipment_code']}"

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=3,
    )
    qr.add_data(payload)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    return send_file(buffer, mimetype='image/png')


@equipment_bp.route('/<equipment_code>/print-label')
@login_required
def print_label(equipment_code):
    """Render printable equipment asset label formatted for barcode printers."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT e.*, c.name AS centre_name, c.code AS centre_code
        FROM equipment_items e
        JOIN health_centres c ON e.centre_id = c.id
        WHERE e.equipment_code = ?
    """, (equipment_code,))
    item = cursor.fetchone()
    conn.close()

    if not item:
        flash("Equipment item not found.", "warning")
        return redirect(url_for('equipment.index'))

    return render_template('equipment/qr_label.html', item=dict(item))


@equipment_bp.route('/api/lookup/<equipment_code>')
@login_required
def api_lookup(equipment_code):
    """API endpoint for equipment QR code scanning and manual lookup."""
    clean_code = equipment_code.strip()
    if clean_code.startswith("SMARTHEALTH:EQUIPMENT:"):
        clean_code = clean_code.replace("SMARTHEALTH:EQUIPMENT:", "").strip()

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT e.*, c.name AS centre_name,
               (SELECT a.id FROM equipment_allotments a WHERE a.equipment_id = e.id AND a.status = 'Active' LIMIT 1) AS active_allotment_id,
               (SELECT a.patient_visit_id FROM equipment_allotments a WHERE a.equipment_id = e.id AND a.status = 'Active' LIMIT 1) AS patient_visit_id,
               (SELECT a.expected_return_time FROM equipment_allotments a WHERE a.equipment_id = e.id AND a.status = 'Active' LIMIT 1) AS expected_return_time
        FROM equipment_items e
        JOIN health_centres c ON e.centre_id = c.id
        WHERE e.equipment_code = ?
    """, (clean_code,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return jsonify({'success': False, 'message': f"No equipment item matching '{clean_code}'."}), 404

    data = dict(row)
    data['is_overdue'] = False
    if data['expected_return_time']:
        data['is_overdue'] = evaluate_allotment_overdue(data['expected_return_time'])

    return jsonify({'success': True, 'equipment': data})
