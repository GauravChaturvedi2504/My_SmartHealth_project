"""
forecasting.py - Explainable Stock Depletion Forecasting based on recorded usage.

Calculates:
- Average daily usage from verified audit records.
- Estimated days of remaining inventory.
- Flags medicines at immediate risk of depletion.
- Displays transparent messages when history is insufficient.
- Emphasizes estimates without falsely claiming machine-learning algorithms.
"""

from datetime import datetime
from flask import Blueprint, render_template, request, session
from database import get_db
from auth import login_required
from inventory import evaluate_batch_status, get_expiry_threshold_days

forecasting_bp = Blueprint('forecasting', __name__, url_prefix='/forecasting')


def calculate_batch_forecast(batch, audit_records, threshold_days=30):
    """
    Calculate an explainable stock forecast for a single medicine batch.

    Formula:
      usable_stock = 0 (if expired) else batch['quantity']
      usage_days_span = (latest_usage_date - earliest_usage_date).days + 1
      avg_daily_usage = total_units_used / usage_days_span
      days_remaining = usable_stock / avg_daily_usage

    Requires at least 2 usage records across at least 1 day interval for sufficient reliability.
    """
    status_info = evaluate_batch_status(
        batch['expiry_date'],
        batch['quantity'],
        batch['min_stock_level'],
        threshold_days
    )
    usable_stock = status_info['usable_quantity']

    # Filter audit logs for stock_used
    usage_entries = [r for r in audit_records if r['batch_id'] == batch['batch_id'] and r['transaction_type'] == 'stock_used']

    if status_info['is_expired']:
        return {
            'has_sufficient_history': True,
            'is_expired': True,
            'total_used': 0,
            'usage_records_count': len(usage_entries),
            'avg_daily_usage': 0.0,
            'usable_stock': 0,
            'days_remaining': 0.0,
            'urgency': 'EXPIRED',
            'explanation': "Batch has expired. Usable stock is zero; immediate restocking and batch disposal required."
        }

    if len(usage_entries) < 2:
        return {
            'has_sufficient_history': False,
            'is_expired': False,
            'total_used': sum(abs(r['change_quantity']) for r in usage_entries),
            'usage_records_count': len(usage_entries),
            'avg_daily_usage': None,
            'usable_stock': usable_stock,
            'days_remaining': None,
            'urgency': 'INSUFFICIENT_DATA',
            'explanation': "Insufficient usage history. At least 2 recorded stock usage transactions over separate days are required to calculate a reliable consumption rate."
        }

    # Calculate date span
    timestamps = []
    total_used = 0
    for entry in usage_entries:
        total_used += abs(entry['change_quantity'])
        try:
            dt = datetime.strptime(entry['timestamp'][:19], "%Y-%m-%d %H:%M:%S")
            timestamps.append(dt)
        except Exception:
            pass

    if not timestamps:
        return {
            'has_sufficient_history': False,
            'is_expired': False,
            'total_used': 0,
            'usage_records_count': 0,
            'avg_daily_usage': None,
            'usable_stock': usable_stock,
            'days_remaining': None,
            'urgency': 'INSUFFICIENT_DATA',
            'explanation': "No valid timestamps found for recorded usage."
        }

    earliest = min(timestamps)
    latest = max(timestamps)
    days_span = max(1, (latest.date() - earliest.date()).days + 1)

    if days_span < 1 or total_used == 0:
        return {
            'has_sufficient_history': False,
            'is_expired': False,
            'total_used': total_used,
            'usage_records_count': len(usage_entries),
            'avg_daily_usage': None,
            'usable_stock': usable_stock,
            'days_remaining': None,
            'urgency': 'INSUFFICIENT_DATA',
            'explanation': "Usage data is concentrated in a single instant. Additional operational days needed."
        }

    avg_daily_usage = round(total_used / days_span, 2)

    if avg_daily_usage <= 0:
        days_remaining = 999.0
        urgency = 'STABLE'
        explanation = "No ongoing stock usage detected in historical window."
    else:
        days_remaining = round(usable_stock / avg_daily_usage, 1)

        if usable_stock == 0:
            urgency = 'DEPLETED'
            explanation = "Stock is currently zero. Urgent replenishment needed."
        elif days_remaining <= 3.0:
            urgency = 'CRITICAL'
            explanation = f"High depletion risk! Stock is estimated to run out in {days_remaining} days based on average daily usage of {avg_daily_usage} {batch['unit']}/day."
        elif days_remaining <= 7.0:
            urgency = 'HIGH_RISK'
            explanation = f"Moderate depletion risk: stock estimated for {days_remaining} days ({avg_daily_usage} {batch['unit']}/day)."
        elif days_remaining <= 14.0:
            urgency = 'MODERATE'
            explanation = f"Estimated {days_remaining} days of supply remaining ({avg_daily_usage} {batch['unit']}/day)."
        else:
            urgency = 'STABLE'
            explanation = f"Healthy inventory buffer. Estimated {days_remaining} days remaining at current rate."

    return {
        'has_sufficient_history': True,
        'is_expired': False,
        'total_used': total_used,
        'usage_records_count': len(usage_entries),
        'days_span': days_span,
        'avg_daily_usage': avg_daily_usage,
        'usable_stock': usable_stock,
        'days_remaining': days_remaining,
        'urgency': urgency,
        'explanation': explanation
    }


@forecasting_bp.route('/')
@login_required
def index():
    """Render stock forecasting analysis dashboard."""
    centre_id = request.args.get('centre_id', type=int)
    urgency_filter = request.args.get('urgency', 'all')

    if centre_id is None and session.get('active_centre_id'):
        centre_id = session.get('active_centre_id')

    threshold_days = get_expiry_threshold_days()
    conn = get_db()
    cursor = conn.cursor()

    # Get centres
    cursor.execute("SELECT id, name, code FROM health_centres ORDER BY name")
    centres = cursor.fetchall()

    # Batches query
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

    query += " ORDER BY b.medicine_name ASC"
    cursor.execute(query, params)
    batches = cursor.fetchall()

    # Fetch audit log usage entries
    cursor.execute("""
        SELECT batch_id, change_quantity, transaction_type, timestamp
        FROM stock_audit_log
        WHERE transaction_type = 'stock_used'
        ORDER BY timestamp ASC
    """)
    audit_records = [dict(r) for r in cursor.fetchall()]
    conn.close()

    forecast_items = []
    critical_risk_count = 0
    high_risk_count = 0
    insufficient_data_count = 0

    for b in batches:
        batch_dict = dict(b)
        calc = calculate_batch_forecast(batch_dict, audit_records, threshold_days)
        batch_dict.update(calc)

        if batch_dict['urgency'] in ['CRITICAL', 'DEPLETED']:
            critical_risk_count += 1
        elif batch_dict['urgency'] == 'HIGH_RISK':
            high_risk_count += 1
        elif not batch_dict['has_sufficient_history']:
            insufficient_data_count += 1

        # Urgency filter
        if urgency_filter == 'critical' and batch_dict['urgency'] not in ['CRITICAL', 'DEPLETED']:
            continue
        elif urgency_filter == 'high_risk' and batch_dict['urgency'] != 'HIGH_RISK':
            continue
        elif urgency_filter == 'insufficient' and batch_dict['has_sufficient_history']:
            continue

        forecast_items.append(batch_dict)

    return render_template(
        'forecasting/index.html',
        forecasts=forecast_items,
        centres=centres,
        selected_centre_id=centre_id or 0,
        urgency_filter=urgency_filter,
        critical_risk_count=critical_risk_count,
        high_risk_count=high_risk_count,
        insufficient_data_count=insufficient_data_count
    )
