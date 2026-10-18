"""
inventory.py - Medicine batch inventory, stock updates, QR code generation,
printable batch labels, and batch lookup for the SmartHealth system.
"""

import io
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, jsonify, abort, session
import qrcode
from database import get_db
from auth import login_required, validate_csrf

inventory_bp = Blueprint('inventory', __name__, url_prefix='/inventory')


def get_expiry_threshold_days():
    """Fetch configurable expiry warning period (default 30 days)."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = 'expiry_threshold_days'")
    row = cursor.fetchone()
    conn.close()
    if row and row['value'].isdigit():
        return int(row['value'])
    return 30


def evaluate_batch_status(expiry_date_str, quantity, min_stock_level, threshold_days=30):
    """
    Evaluate a batch's expiry and stock status flags:
    - is_expired: True if expiry_date < today
    - is_near_expiry: True if not expired but expiry_date <= today + threshold_days
    - is_low_stock: True if quantity <= min_stock_level
    - is_out_of_stock: True if quantity <= 0
    - usable_quantity: 0 if expired, else current quantity
    """
    today = datetime.now().date()
    try:
        exp_date = datetime.strptime(expiry_date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        exp_date = today

    days_to_expiry = (exp_date - today).days
    is_expired = days_to_expiry < 0
    is_near_expiry = (not is_expired) and (days_to_expiry <= threshold_days)
    is_out_of_stock = quantity <= 0
    is_low_stock = quantity <= min_stock_level

    # Expired medicines must be clearly flagged and excluded from usable stock calculations
    usable_quantity = 0 if is_expired else max(0, quantity)

    return {
        'days_to_expiry': days_to_expiry,
        'is_expired': is_expired,
        'is_near_expiry': is_near_expiry,
        'is_low_stock': is_low_stock,
        'is_out_of_stock': is_out_of_stock,
        'usable_quantity': usable_quantity
    }


@inventory_bp.route('/')
@login_required
def list_batches():
    """List medicine batches with filtering by centre, stock status, and search query."""
    centre_id = request.args.get('centre_id', type=int)
    status_filter = request.args.get('status', 'all')
    search_q = request.args.get('q', '').strip()

    # Session active centre preference fallback
    if centre_id is None and session.get('active_centre_id'):
        centre_id = session.get('active_centre_id')

    threshold_days = get_expiry_threshold_days()
    conn = get_db()
    cursor = conn.cursor()

    # Fetch centres for filter dropdown
    cursor.execute("SELECT id, name, code FROM health_centres ORDER BY name")
    centres = cursor.fetchall()

    query = """
        SELECT b.*, c.name AS centre_name, c.code AS centre_code
        FROM medicine_batches b
        JOIN health_centres c ON b.centre_id = c.id
        WHERE 1=1
    """
    params = []

    if centre_id and centre_id > 0:
        query += " AND b.centre_id = ?"
        params.append(centre_id)

    if search_q:
        query += " AND (b.medicine_name LIKE ? OR b.generic_name LIKE ? OR b.batch_id LIKE ? OR b.batch_number LIKE ?)"
        term = f"%{search_q}%"
        params.extend([term, term, term, term])

    query += " ORDER BY b.expiry_date ASC, b.medicine_name ASC"
    cursor.execute(query, params)
    raw_batches = cursor.fetchall()
    conn.close()

    batches = []
    total_usable_units = 0
    low_stock_count = 0
    near_expiry_count = 0
    expired_count = 0

    for row in raw_batches:
        item = dict(row)
        status_info = evaluate_batch_status(
            item['expiry_date'],
            item['quantity'],
            item['min_stock_level'],
            threshold_days
        )
        item.update(status_info)

        if item['is_expired']:
            expired_count += 1
        else:
            total_usable_units += item['quantity']

        if item['is_near_expiry']:
            near_expiry_count += 1
        if item['is_low_stock']:
            low_stock_count += 1

        # Apply frontend status filter
        if status_filter == 'low_stock' and not item['is_low_stock']:
            continue
        elif status_filter == 'near_expiry' and not item['is_near_expiry']:
            continue
        elif status_filter == 'expired' and not item['is_expired']:
            continue
        elif status_filter == 'usable' and item['is_expired']:
            continue

        batches.append(item)

    return render_template(
        'inventory/list.html',
        batches=batches,
        centres=centres,
        selected_centre_id=centre_id or 0,
        status_filter=status_filter,
        search_q=search_q,
        threshold_days=threshold_days,
        total_batches=len(raw_batches),
        low_stock_count=low_stock_count,
        near_expiry_count=near_expiry_count,
        expired_count=expired_count,
        total_usable_units=total_usable_units
    )


@inventory_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add_batch():
    """Add a new medicine batch."""
    conn = get_db()
    cursor = conn.cursor()

    if request.method == 'POST':
        validate_csrf()
        medicine_name = request.form.get('medicine_name', '').strip()
        generic_name = request.form.get('generic_name', '').strip()
        batch_number = request.form.get('batch_number', '').strip().upper()
        centre_id = request.form.get('centre_id', type=int)
        quantity = request.form.get('quantity', type=int)
        min_stock_level = request.form.get('min_stock_level', type=int)
        unit = request.form.get('unit', 'strips').strip()
        expiry_date = request.form.get('expiry_date', '').strip()
        storage_instructions = request.form.get('storage_instructions', '').strip()
        storage_location = request.form.get('storage_location', '').strip()

        # Validation
        if not medicine_name or not generic_name or not batch_number or not centre_id or not expiry_date:
            flash("Please fill in all mandatory medicine fields.", "danger")
        elif quantity is None or quantity < 0:
            flash("Initial quantity cannot be negative.", "danger")
        elif min_stock_level is None or min_stock_level < 0:
            flash("Minimum stock level cannot be negative.", "danger")
        else:
            # Generate unique Batch ID (e.g., BAT-<centre_id>-<timestamp>)
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("SELECT COUNT(*) FROM medicine_batches")
            count = cursor.fetchone()[0] + 1
            batch_id = f"BAT-{batch_number[:8]}-{count:03d}"

            try:
                cursor.execute("""
                    INSERT INTO medicine_batches (
                        batch_id, medicine_name, generic_name, batch_number, centre_id,
                        quantity, min_stock_level, unit, expiry_date, storage_instructions,
                        storage_location, last_updated
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    batch_id, medicine_name, generic_name, batch_number, centre_id,
                    quantity, min_stock_level, unit, expiry_date, storage_instructions,
                    storage_location, now_str
                ))

                # Log initial stock in audit history
                cursor.execute("""
                    INSERT INTO stock_audit_log (
                        batch_id, medicine_name, centre_id, previous_quantity, change_quantity,
                        updated_quantity, transaction_type, timestamp, staff_username, reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    batch_id, medicine_name, centre_id, 0, quantity,
                    quantity, "stock_received", now_str, session.get('username', 'system'),
                    "New batch recorded into inventory"
                ))

                conn.commit()
                flash(f"Medicine batch '{medicine_name}' ({batch_id}) added successfully!", "success")
                conn.close()
                return redirect(url_for('inventory.list_batches'))
            except Exception as e:
                conn.rollback()
                flash(f"Database error while creating batch: {str(e)}", "danger")

    cursor.execute("SELECT id, name, code FROM health_centres ORDER BY name")
    centres = cursor.fetchall()
    conn.close()
    return render_template('inventory/form.html', batch=None, centres=centres)


@inventory_bp.route('/edit/<batch_id>', methods=['GET', 'POST'])
@login_required
def edit_batch(batch_id):
    """Edit metadata for an existing medicine batch."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM medicine_batches WHERE batch_id = ?", (batch_id,))
    batch = cursor.fetchone()

    if not batch:
        conn.close()
        flash("Medicine batch not found.", "warning")
        return redirect(url_for('inventory.list_batches'))

    if request.method == 'POST':
        validate_csrf()
        medicine_name = request.form.get('medicine_name', '').strip()
        generic_name = request.form.get('generic_name', '').strip()
        batch_number = request.form.get('batch_number', '').strip().upper()
        min_stock_level = request.form.get('min_stock_level', type=int)
        unit = request.form.get('unit', 'strips').strip()
        expiry_date = request.form.get('expiry_date', '').strip()
        storage_instructions = request.form.get('storage_instructions', '').strip()
        storage_location = request.form.get('storage_location', '').strip()

        if not medicine_name or not generic_name or not batch_number or not expiry_date:
            flash("Required fields cannot be empty.", "danger")
        elif min_stock_level is None or min_stock_level < 0:
            flash("Minimum stock level cannot be negative.", "danger")
        else:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("""
                UPDATE medicine_batches
                SET medicine_name = ?, generic_name = ?, batch_number = ?,
                    min_stock_level = ?, unit = ?, expiry_date = ?,
                    storage_instructions = ?, storage_location = ?, last_updated = ?
                WHERE batch_id = ?
            """, (
                medicine_name, generic_name, batch_number,
                min_stock_level, unit, expiry_date,
                storage_instructions, storage_location, now_str,
                batch_id
            ))
            conn.commit()
            flash(f"Batch details for {batch_id} updated successfully.", "success")
            conn.close()
            return redirect(url_for('inventory.list_batches'))

    cursor.execute("SELECT id, name, code FROM health_centres ORDER BY name")
    centres = cursor.fetchall()
    conn.close()
    return render_template('inventory/form.html', batch=dict(batch), centres=centres)


@inventory_bp.route('/adjust-stock/<batch_id>', methods=['POST'])
@login_required
def adjust_stock(batch_id):
    """
    Handle stock adjustments:
    - stock_received (+): add stock
    - stock_used (-): record medicine usage
    - correction (+/-): manual inventory count audit correction
    - expired_removed (-): remove expired stock from usable shelf
    Prevents negative stock and logs every change into immutable audit log.
    """
    validate_csrf()
    tx_type = request.form.get('transaction_type', '').strip()
    qty_change = request.form.get('quantity', type=int)
    reason = request.form.get('reason', '').strip()

    if not qty_change or qty_change <= 0:
        flash("Stock adjustment quantity must be a positive integer greater than zero.", "danger")
        return redirect(request.referrer or url_for('inventory.list_batches'))

    valid_types = ['stock_received', 'stock_used', 'correction_add', 'correction_subtract', 'expired_removed']
    if tx_type not in valid_types:
        flash("Invalid transaction type specified.", "danger")
        return redirect(request.referrer or url_for('inventory.list_batches'))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM medicine_batches WHERE batch_id = ?", (batch_id,))
    batch = cursor.fetchone()

    if not batch:
        conn.close()
        flash("Medicine batch not found.", "warning")
        return redirect(url_for('inventory.list_batches'))

    current_qty = batch['quantity']
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Determine delta and new quantity
    if tx_type == 'stock_received' or tx_type == 'correction_add':
        delta = qty_change
        new_qty = current_qty + delta
        logged_tx = 'stock_received' if tx_type == 'stock_received' else 'correction'
    else:
        # Deductions
        delta = -qty_change
        if current_qty < qty_change:
            conn.close()
            flash(f"Cannot deduct {qty_change} units: only {current_qty} units available. Negative stock is strictly disallowed.", "danger")
            return redirect(request.referrer or url_for('inventory.list_batches'))
        new_qty = current_qty - qty_change
        logged_tx = 'stock_used' if tx_type == 'stock_used' else ('expired_removed' if tx_type == 'expired_removed' else 'correction')

    try:
        # Update batch quantity
        cursor.execute("""
            UPDATE medicine_batches
            SET quantity = ?, last_updated = ?
            WHERE batch_id = ?
        """, (new_qty, now_str, batch_id))

        # Record in stock audit log
        cursor.execute("""
            INSERT INTO stock_audit_log (
                batch_id, medicine_name, centre_id, previous_quantity, change_quantity,
                updated_quantity, transaction_type, timestamp, staff_username, reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            batch_id, batch['medicine_name'], batch['centre_id'], current_qty, delta,
            new_qty, logged_tx, now_str, session.get('username', 'staff'), reason
        ))

        conn.commit()
        flash(f"Stock for {batch['medicine_name']} updated ({current_qty} -> {new_qty} {batch['unit']}).", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error adjusting stock: {str(e)}", "danger")
    finally:
        conn.close()

    return redirect(request.referrer or url_for('inventory.list_batches'))


@inventory_bp.route('/batch/<batch_id>/qr.png')
def qr_code_image(batch_id):
    """
    Generate and serve a dynamic QR code PNG for the given medicine batch.
    Never encodes credentials or private patient info; encodes clean batch identifier.
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT batch_id, medicine_name, batch_number FROM medicine_batches WHERE batch_id = ?", (batch_id,))
    batch = cursor.fetchone()
    conn.close()

    if not batch:
        abort(404, description="Batch identifier not found")

    # Encode safe standardized payload
    qr_payload = f"SMARTHEALTH:BATCH:{batch['batch_id']}"

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=3,
    )
    qr.add_data(qr_payload)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    return send_file(buffer, mimetype='image/png')


@inventory_bp.route('/batch/<batch_id>/print-label')
@login_required
def print_label(batch_id):
    """Render a dedicated, printable medicine shelf label with QR code and batch metadata."""
    threshold_days = get_expiry_threshold_days()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT b.*, c.name AS centre_name, c.code AS centre_code, c.contact_number
        FROM medicine_batches b
        JOIN health_centres c ON b.centre_id = c.id
        WHERE b.batch_id = ?
    """, (batch_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        flash("Medicine batch not found.", "warning")
        return redirect(url_for('inventory.list_batches'))

    batch = dict(row)
    batch.update(evaluate_batch_status(
        batch['expiry_date'],
        batch['quantity'],
        batch['min_stock_level'],
        threshold_days
    ))

    return render_template('inventory/qr_label.html', batch=batch)


@inventory_bp.route('/scan')
@login_required
def scan_page():
    """Render the QR scanning page with device camera support and manual batch ID lookup fallback."""
    return render_template('inventory/scan.html')


@inventory_bp.route('/api/batch/<batch_id>')
@login_required
def api_get_batch(batch_id):
    """
    JSON API endpoint for QR scanner and lookup.
    Returns clean batch information, stock levels, and alert flags.
    """
    # Clean possible prefix from QR scanner (e.g. SMARTHEALTH:BATCH:BAT-001 or URL)
    clean_id = batch_id.strip()
    if clean_id.startswith("SMARTHEALTH:BATCH:"):
        clean_id = clean_id.replace("SMARTHEALTH:BATCH:", "").strip()

    threshold_days = get_expiry_threshold_days()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT b.*, c.name AS centre_name, c.code AS centre_code
        FROM medicine_batches b
        JOIN health_centres c ON b.centre_id = c.id
        WHERE b.batch_id = ? OR b.batch_number = ?
    """, (clean_id, clean_id))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return jsonify({
            'success': False,
            'message': f"No medicine batch found matching identifier '{clean_id}'."
        }), 404

    data = dict(row)
    data.update(evaluate_batch_status(
        data['expiry_date'],
        data['quantity'],
        data['min_stock_level'],
        threshold_days
    ))

    return jsonify({
        'success': True,
        'batch': data
    })
