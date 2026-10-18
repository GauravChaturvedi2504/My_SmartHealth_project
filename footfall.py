"""
footfall.py - Patient Footfall & Capacity Analytics.

Allows authorized health centre staff to record and track aggregate daily patient volumes:
- Outpatient (OPD) counts
- Emergency triage admissions
- Inter-facility specialist referrals

Preserves patient privacy by tracking aggregate counts without personal identifiers.
"""

from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from database import get_db
from auth import login_required, validate_csrf

footfall_bp = Blueprint('footfall', __name__, url_prefix='/footfall')


@footfall_bp.route('/', methods=['GET', 'POST'])
@login_required
def index():
    """Display footfall dashboard, recording form, and 7-day aggregate trends."""
    centre_id = request.args.get('centre_id', type=int)

    if centre_id is None and session.get('active_centre_id'):
        centre_id = session.get('active_centre_id')

    conn = get_db()
    cursor = conn.cursor()

    # Handle Footfall Entry Form submission
    if request.method == 'POST':
        validate_csrf()
        post_centre_id = request.form.get('centre_id', type=int)
        record_date = request.form.get('record_date', '').strip()
        op_count = request.form.get('outpatient_count', type=int)
        em_count = request.form.get('emergency_count', type=int)
        ref_count = request.form.get('referral_count', type=int)
        notes = request.form.get('notes', '').strip()

        # Validation
        if not post_centre_id or not record_date:
            flash("Centre and record date are mandatory.", "danger")
        elif op_count is None or op_count < 0 or em_count is None or em_count < 0 or ref_count is None or ref_count < 0:
            flash("Patient counts must be non-negative numbers (0 or higher).", "danger")
        else:
            total = op_count + em_count + ref_count
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            username = session.get('username', 'staff')

            try:
                cursor.execute("""
                    INSERT INTO patient_footfall (
                        centre_id, record_date, outpatient_count, emergency_count, referral_count,
                        total_count, recorded_by, notes, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(centre_id, record_date) DO UPDATE SET
                        outpatient_count = excluded.outpatient_count,
                        emergency_count = excluded.emergency_count,
                        referral_count = excluded.referral_count,
                        total_count = excluded.total_count,
                        recorded_by = excluded.recorded_by,
                        notes = excluded.notes
                """, (post_centre_id, record_date, op_count, em_count, ref_count, total, username, notes, now_str))
                conn.commit()
                flash(f"Patient footfall for {record_date} saved successfully (Total: {total}).", "success")
                conn.close()
                return redirect(url_for('footfall.index', centre_id=post_centre_id))
            except Exception as e:
                conn.rollback()
                flash(f"Error saving footfall record: {str(e)}", "danger")

    cursor.execute("SELECT id, name, code FROM health_centres ORDER BY name")
    centres = cursor.fetchall()

    query = """
        SELECT f.*, c.name AS centre_name, c.code AS centre_code
        FROM patient_footfall f
        JOIN health_centres c ON f.centre_id = c.id
        WHERE 1=1
    """
    params = []
    if centre_id and centre_id > 0:
        query += " AND f.centre_id = ?"
        params.append(centre_id)

    query += " ORDER BY f.record_date DESC, c.name ASC LIMIT 30"
    cursor.execute(query, params)
    records = cursor.fetchall()

    # Calculate trends over the past 7 days
    today_str = datetime.now().strftime("%Y-%m-%d")
    today_total = 0
    weekly_total = 0
    weekly_op = 0
    weekly_em = 0
    weekly_ref = 0

    for r in records[:7]:
        weekly_total += r['total_count']
        weekly_op += r['outpatient_count']
        weekly_em += r['emergency_count']
        weekly_ref += r['referral_count']
        if r['record_date'] == today_str:
            today_total += r['total_count']

    days_logged = min(len(records), 7)
    daily_average = round(weekly_total / days_logged, 1) if days_logged > 0 else 0

    conn.close()

    return render_template(
        'footfall/index.html',
        records=records,
        centres=centres,
        selected_centre_id=centre_id or 0,
        today_date=today_str,
        today_total=today_total,
        weekly_total=weekly_total,
        weekly_op=weekly_op,
        weekly_em=weekly_em,
        weekly_ref=weekly_ref,
        daily_average=daily_average
    )
