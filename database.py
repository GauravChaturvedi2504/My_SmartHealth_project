"""
database.py - Database connection, schema setup, and demo data seeding
for the SmartHealth Health Centre Management System.

Uses standard Python sqlite3 with parameterized queries to prevent SQL injection.
Separates database logic cleanly from web routes.
"""

import sqlite3
import os
import json
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash

# Default database filename in current directory or configured via environment
DEFAULT_DB_PATH = os.environ.get("SMARTHEALTH_DB", "smarthealth.db")


def get_db_path(custom_path=None):
    """
    Return the absolute path to the SQLite database file.
    If running within a Flask application context, uses current_app.config['DATABASE'].
    Otherwise falls back to SMARTHEALTH_DB env var or default smarthealth.db.
    """
    if custom_path:
        return custom_path
    try:
        from flask import current_app, has_app_context
        if has_app_context() and current_app and current_app.config.get('DATABASE'):
            return os.path.abspath(current_app.config['DATABASE'])
    except Exception:
        pass

    env_db = os.environ.get("SMARTHEALTH_DB")
    if env_db:
        return os.path.abspath(env_db)
    return os.path.abspath("smarthealth.db")


def get_db(db_path=None):
    """
    Open and return a SQLite database connection with row access by column name.
    Callers are responsible for closing the connection or using it as a context manager.
    """
    path = get_db_path(db_path)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    # Enable foreign key constraint support in SQLite
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path=None):
    """
    Create all database tables if they do not exist and seed initial demo data
    if tables are empty. Safe to call multiple times.
    """
    conn = get_db(db_path)
    cursor = conn.cursor()

    # 1. Health Centres table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS health_centres (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            code TEXT NOT NULL UNIQUE,
            centre_type TEXT NOT NULL,
            location TEXT NOT NULL,
            contact_number TEXT
        )
    """)

    # 2. Users table (Hashed passwords, roles: 'admin' or 'staff')
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            role TEXT NOT NULL,
            centre_id INTEGER,
            created_at TEXT NOT NULL,
            FOREIGN KEY (centre_id) REFERENCES health_centres(id)
        )
    """)

    # 3. Medicine Batches table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS medicine_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id TEXT NOT NULL UNIQUE,
            medicine_name TEXT NOT NULL,
            generic_name TEXT NOT NULL,
            batch_number TEXT NOT NULL,
            centre_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 0,
            min_stock_level INTEGER NOT NULL DEFAULT 10,
            unit TEXT NOT NULL DEFAULT 'strips',
            expiry_date TEXT NOT NULL,
            storage_instructions TEXT,
            storage_location TEXT,
            last_updated TEXT NOT NULL,
            FOREIGN KEY (centre_id) REFERENCES health_centres(id)
        )
    """)

    # 4. Stock Audit History table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id TEXT NOT NULL,
            medicine_name TEXT NOT NULL,
            centre_id INTEGER NOT NULL,
            previous_quantity INTEGER NOT NULL,
            change_quantity INTEGER NOT NULL,
            updated_quantity INTEGER NOT NULL,
            transaction_type TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            staff_username TEXT NOT NULL,
            reason TEXT,
            FOREIGN KEY (centre_id) REFERENCES health_centres(id)
        )
    """)

    # 5. Priority Alerts table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_key TEXT NOT NULL UNIQUE,
            centre_id INTEGER,
            severity TEXT NOT NULL,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL,
            is_acknowledged INTEGER DEFAULT 0,
            acknowledged_by TEXT,
            acknowledged_at TEXT,
            FOREIGN KEY (centre_id) REFERENCES health_centres(id)
        )
    """)

    # 6. Doctors table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS doctors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            specialty TEXT NOT NULL,
            centre_id INTEGER NOT NULL,
            contact_phone TEXT,
            duty_start_time TEXT NOT NULL,
            duty_end_time TEXT NOT NULL,
            scheduled_days TEXT NOT NULL,
            current_status TEXT NOT NULL DEFAULT 'Available',
            leave_start_date TEXT,
            leave_end_date TEXT,
            leave_reason TEXT,
            last_status_update TEXT NOT NULL,
            updated_by TEXT,
            FOREIGN KEY (centre_id) REFERENCES health_centres(id)
        )
    """)

    # 7. Beds table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS beds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bed_number TEXT NOT NULL,
            centre_id INTEGER NOT NULL,
            ward TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Available',
            patient_identifier TEXT,
            last_updated TEXT NOT NULL,
            notes TEXT,
            UNIQUE(centre_id, bed_number),
            FOREIGN KEY (centre_id) REFERENCES health_centres(id)
        )
    """)

    # 8. Patient Footfall table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS patient_footfall (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            centre_id INTEGER NOT NULL,
            record_date TEXT NOT NULL,
            outpatient_count INTEGER NOT NULL DEFAULT 0,
            emergency_count INTEGER NOT NULL DEFAULT 0,
            referral_count INTEGER NOT NULL DEFAULT 0,
            total_count INTEGER NOT NULL DEFAULT 0,
            recorded_by TEXT NOT NULL,
            notes TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(centre_id, record_date),
            FOREIGN KEY (centre_id) REFERENCES health_centres(id)
        )
    """)

    # 9. Housekeeping Staff table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cleaning_staff (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            centre_id INTEGER NOT NULL,
            assigned_area TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            phone TEXT,
            FOREIGN KEY (centre_id) REFERENCES health_centres(id)
        )
    """)

    # 10. Cleaning Tasks table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cleaning_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            centre_id INTEGER NOT NULL,
            area TEXT NOT NULL,
            staff_id INTEGER,
            scheduled_time TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pending',
            last_completed_time TEXT,
            checklist_json TEXT NOT NULL,
            completed_checklist_json TEXT NOT NULL DEFAULT '[]',
            notes TEXT,
            FOREIGN KEY (centre_id) REFERENCES health_centres(id),
            FOREIGN KEY (staff_id) REFERENCES cleaning_staff(id)
        )
    """)

    # 11. Settings table (e.g. expiry threshold days)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    # 12. Equipment Items (Wheelchairs, stretchers, reusable transport items)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS equipment_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            equipment_code TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            centre_id INTEGER NOT NULL,
            current_ward TEXT NOT NULL,
            current_status TEXT NOT NULL DEFAULT 'Available',
            last_sanitized_time TEXT,
            notes TEXT,
            FOREIGN KEY (centre_id) REFERENCES health_centres(id)
        )
    """)

    # 13. Equipment Allotments & Returns Ledger
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS equipment_allotments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            equipment_id INTEGER NOT NULL,
            centre_id INTEGER NOT NULL,
            patient_visit_id TEXT NOT NULL,
            patient_name TEXT,
            ward TEXT NOT NULL,
            issue_time TEXT NOT NULL,
            expected_return_time TEXT NOT NULL,
            issuing_staff TEXT NOT NULL,
            actual_return_time TEXT,
            receiving_staff TEXT,
            return_condition TEXT,
            status TEXT NOT NULL DEFAULT 'Active',
            return_notes TEXT,
            FOREIGN KEY (equipment_id) REFERENCES equipment_items(id),
            FOREIGN KEY (centre_id) REFERENCES health_centres(id)
        )
    """)

    # 14. Equipment Maintenance & Sanitization Log
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS equipment_maintenance_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            equipment_id INTEGER NOT NULL,
            centre_id INTEGER NOT NULL,
            action_type TEXT NOT NULL,
            performed_by TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            details TEXT,
            FOREIGN KEY (equipment_id) REFERENCES equipment_items(id),
            FOREIGN KEY (centre_id) REFERENCES health_centres(id)
        )
    """)

    # 15. Ambulances Fleet
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ambulances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vehicle_code TEXT NOT NULL UNIQUE,
            registration_number TEXT NOT NULL UNIQUE,
            centre_id INTEGER NOT NULL,
            ambulance_type TEXT NOT NULL,
            primary_driver_name TEXT NOT NULL,
            driver_contact TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Available',
            fitness_cert_expiry TEXT NOT NULL,
            insurance_expiry TEXT NOT NULL,
            last_service_date TEXT,
            next_service_due TEXT NOT NULL,
            equipment_specs TEXT,
            last_status_update TEXT NOT NULL,
            updated_by TEXT,
            FOREIGN KEY (centre_id) REFERENCES health_centres(id)
        )
    """)

    # 16. Ambulance Trip / Dispatch Records
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ambulance_trips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ambulance_id INTEGER NOT NULL,
            centre_id INTEGER NOT NULL,
            trip_purpose TEXT NOT NULL,
            patient_identifier TEXT,
            destination TEXT NOT NULL,
            departure_time TEXT NOT NULL,
            expected_return_time TEXT,
            actual_return_time TEXT,
            driver_name TEXT NOT NULL,
            paramedic_staff TEXT,
            status TEXT NOT NULL DEFAULT 'In Transit',
            notes TEXT,
            FOREIGN KEY (ambulance_id) REFERENCES ambulances(id),
            FOREIGN KEY (centre_id) REFERENCES health_centres(id)
        )
    """)

    # 17. Facility Assets (AC, Generators, Refrigerators, Oxygen Plants)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS facility_assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_tag TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            centre_id INTEGER NOT NULL,
            location TEXT NOT NULL,
            condition_status TEXT NOT NULL DEFAULT 'Operational',
            installation_date TEXT,
            last_service_date TEXT,
            next_service_due TEXT NOT NULL,
            model_serial TEXT,
            vendor_support TEXT,
            FOREIGN KEY (centre_id) REFERENCES health_centres(id)
        )
    """)

    # 18. Maintenance Work Orders
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS maintenance_work_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            work_order_code TEXT NOT NULL UNIQUE,
            asset_id INTEGER NOT NULL,
            centre_id INTEGER NOT NULL,
            priority TEXT NOT NULL,
            issue_description TEXT NOT NULL,
            reported_by TEXT NOT NULL,
            reported_at TEXT NOT NULL,
            assigned_technician TEXT,
            status TEXT NOT NULL DEFAULT 'Open',
            estimated_cost REAL DEFAULT 0.0,
            actual_cost REAL DEFAULT 0.0,
            resolution_notes TEXT,
            resolved_at TEXT,
            resolved_by TEXT,
            FOREIGN KEY (asset_id) REFERENCES facility_assets(id),
            FOREIGN KEY (centre_id) REFERENCES health_centres(id)
        )
    """)

    conn.commit()

    # Seed initial demo data if database is fresh
    cursor.execute("SELECT COUNT(*) FROM health_centres")
    if cursor.fetchone()[0] == 0:
        seed_demo_data(conn)
    else:
        # Check and seed equipment if newly created table is empty
        cursor.execute("SELECT COUNT(*) FROM equipment_items")
        if cursor.fetchone()[0] == 0:
            seed_additional_modules(conn)

    conn.close()


def seed_demo_data(conn):
    """
    Seed realistic, beginner-friendly demo data for multiple health centres.
    Includes normal medicines, low-stock batches, nearing-expiry stock, expired stock,
    multi-day audit log records for forecasting, doctors, beds, and cleaning tasks.
    """
    cursor = conn.cursor()
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    # Default settings
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('expiry_threshold_days', '30')")

    # 1. Health Centres
    centres = [
        ("Green Valley Primary Health Centre", "PHC-GV", "Primary Health Centre (PHC)", "Sector 4, Green Valley Rural Block", "+91-98765-43210"),
        ("Sunrise Community Health Centre", "CHC-SR", "Community Health Centre (CHC)", "Main Highway Road, Sunrise District", "+91-98765-43211"),
        ("Riverside Sub-Centre", "SC-RS", "Sub-Centre (SC)", "Post Office Lane, Riverside Village", "+91-98765-43212")
    ]
    cursor.executemany("""
        INSERT INTO health_centres (name, code, centre_type, location, contact_number)
        VALUES (?, ?, ?, ?, ?)
    """, centres)

    # 2. Users (Admin and Staff with hashed passwords)
    # Passwords:
    # admin -> Admin@123
    # staff -> Staff@123
    # sunrise_staff -> Staff@123
    users = [
        ("admin", generate_password_hash("Admin@123"), "Dr. Rajesh Sharma (Administrator)", "admin", None, now_str),
        ("staff", generate_password_hash("Staff@123"), "Priya Patel (PHC Pharmacist & Nurse)", "staff", 1, now_str),
        ("sunrise_staff", generate_password_hash("Staff@123"), "Vikram Singh (CHC Store Manager)", "staff", 2, now_str)
    ]
    cursor.executemany("""
        INSERT INTO users (username, password_hash, full_name, role, centre_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, users)

    # Calculate dates for expiry scenarios
    expired_date = (now - timedelta(days=15)).strftime("%Y-%m-%d")
    near_expiry_date = (now + timedelta(days=12)).strftime("%Y-%m-%d")
    normal_expiry_date = (now + timedelta(days=280)).strftime("%Y-%m-%d")
    long_expiry_date = (now + timedelta(days=450)).strftime("%Y-%m-%d")

    # 3. Medicine Batches
    # Includes:
    # - BAT-001: Paracetamol (GV, healthy stock)
    # - BAT-002: Amoxicillin 500mg (GV, LOW STOCK: 8 available, min 25)
    # - BAT-003: Oral Rehydration Salts (GV, NEARING EXPIRY in 12 days)
    # - BAT-004: Ciprofloxacin Eye Drops (GV, EXPIRED 15 days ago)
    # - BAT-005: Metformin 500mg (GV, good stock)
    # - BAT-006: Cetirizine 10mg (GV, healthy stock)
    # - BAT-007: Amoxicillin 500mg (SR, healthy stock)
    # - BAT-008: Insulin Glargine (SR, Cold storage, near expiry)
    # - BAT-009: Paracetamol Syrup (RS, low stock)
    batches = [
        ("BAT-001", "Paracetamol 500mg", "Paracetamol", "PCM-2026-A1", 1, 140, 30, "strips (10 tablets)", normal_expiry_date, "Store below 25°C in a dry place", "Shelf A1 - Main Pharmacy", now_str),
        ("BAT-002", "Amoxicillin 500mg", "Amoxicillin Trihydrate", "AMX-2025-C2", 1, 8, 25, "strips (10 capsules)", normal_expiry_date, "Keep away from direct sunlight", "Shelf B2 - Antibiotics", now_str),
        ("BAT-003", "Oral Rehydration Salts (ORS)", "Oral Rehydration Salts IP", "ORS-2024-X9", 1, 65, 20, "sachets", near_expiry_date, "Store in a cool and dry location", "Shelf D1 - Hydration", now_str),
        ("BAT-004", "Ciprofloxacin Eye Drops 0.3%", "Ciprofloxacin", "CIP-2024-Z4", 1, 15, 10, "vials (5ml)", expired_date, "Discard 30 days after opening", "Shelf C3 - Ophthalmic", now_str),
        ("BAT-005", "Metformin 500mg", "Metformin Hydrochloride", "MET-2026-M3", 1, 210, 50, "strips (10 tablets)", long_expiry_date, "Store below 30°C", "Shelf A3 - Chronic Care", now_str),
        ("BAT-006", "Cetirizine 10mg", "Cetirizine Dihydrochloride", "CET-2026-T7", 1, 95, 25, "strips (10 tablets)", normal_expiry_date, "Protect from moisture", "Shelf A2 - Antihistamines", now_str),
        ("BAT-007", "Amoxicillin 500mg", "Amoxicillin Trihydrate", "AMX-2026-D4", 2, 85, 30, "strips (10 capsules)", normal_expiry_date, "Store below 25°C", "Pharmacy Room 1, Cabinet 4", now_str),
        ("BAT-008", "Insulin Glargine 100 IU/ml", "Insulin Glargine", "INS-2025-V1", 2, 12, 15, "vials (10ml)", near_expiry_date, "Refrigerate between 2°C to 8°C. Do not freeze", "Cold Chain Refrigerator #2", now_str),
        ("BAT-009", "Paracetamol Paediatric Oral Suspension", "Paracetamol 120mg/5ml", "PED-2025-P2", 3, 4, 15, "bottles (60ml)", normal_expiry_date, "Shake well before use. Store below 25°C", "Front Counter Rack 1", now_str)
    ]

    cursor.executemany("""
        INSERT INTO medicine_batches (
            batch_id, medicine_name, generic_name, batch_number, centre_id,
            quantity, min_stock_level, unit, expiry_date, storage_instructions,
            storage_location, last_updated
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, batches)

    # 4. Stock Audit History (spanning past 14 days to provide historical usage for forecasting)
    # We log historical transactions for BAT-001 (Paracetamol) and BAT-002 (Amoxicillin)
    audit_records = [
        # BAT-001: started with 200, used on various days
        ("BAT-001", "Paracetamol 500mg", 1, 0, 200, 200, "stock_received", (now - timedelta(days=14)).strftime("%Y-%m-%d 09:30:00"), "staff", "Initial bulk batch arrival from district medical depot"),
        ("BAT-001", "Paracetamol 500mg", 1, 200, -12, 188, "stock_used", (now - timedelta(days=12)).strftime("%Y-%m-%d 14:10:00"), "staff", "Dispensed to OPD fever patients"),
        ("BAT-001", "Paracetamol 500mg", 1, 188, -15, 173, "stock_used", (now - timedelta(days=9)).strftime("%Y-%m-%d 16:45:00"), "staff", "Dispensed to outpatient clinic"),
        ("BAT-001", "Paracetamol 500mg", 1, 173, -18, 155, "stock_used", (now - timedelta(days=6)).strftime("%Y-%m-%d 11:20:00"), "staff", "Dispensed to seasonal viral flu patients"),
        ("BAT-001", "Paracetamol 500mg", 1, 155, -15, 140, "stock_used", (now - timedelta(days=2)).strftime("%Y-%m-%d 15:00:00"), "staff", "Dispensed to morning OPD"),
        # BAT-002: Amoxicillin - high usage, now running very low
        ("BAT-002", "Amoxicillin 500mg", 1, 0, 70, 70, "stock_received", (now - timedelta(days=10)).strftime("%Y-%m-%d 10:00:00"), "staff", "Received batch delivery"),
        ("BAT-002", "Amoxicillin 500mg", 1, 70, -20, 50, "stock_used", (now - timedelta(days=7)).strftime("%Y-%m-%d 13:30:00"), "staff", "Prescriptions filled for respiratory infections"),
        ("BAT-002", "Amoxicillin 500mg", 1, 50, -22, 28, "stock_used", (now - timedelta(days=4)).strftime("%Y-%m-%d 17:00:00"), "staff", "Prescriptions filled for bacterial infections"),
        ("BAT-002", "Amoxicillin 500mg", 1, 28, -20, 8, "stock_used", (now - timedelta(days=1)).strftime("%Y-%m-%d 12:15:00"), "staff", "Dispensed to emergency & OPD"),
        # BAT-004: expired removal record or warning
        ("BAT-004", "Ciprofloxacin Eye Drops 0.3%", 1, 20, -5, 15, "stock_used", (now - timedelta(days=20)).strftime("%Y-%m-%d 10:00:00"), "staff", "Routine OPD eye clinic usage")
    ]
    cursor.executemany("""
        INSERT INTO stock_audit_log (
            batch_id, medicine_name, centre_id, previous_quantity, change_quantity,
            updated_quantity, transaction_type, timestamp, staff_username, reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, audit_records)

    # 5. Doctors
    doctors = [
        ("Dr. Anita Deshmukh", "General Physician / Medical Officer", 1, "+91-98111-22331", "08:00", "14:00", "Mon, Tue, Wed, Thu, Fri, Sat", "On Duty", None, None, None, now_str, "admin"),
        ("Dr. Suresh Nair", "Paediatrician", 1, "+91-98111-22332", "09:00", "15:00", "Mon, Wed, Fri", "Available", None, None, None, now_str, "admin"),
        ("Dr. Kavita Joshi", "Gynaecologist & Obstetrician", 1, "+91-98111-22333", "10:00", "16:00", "Tue, Thu, Sat", "On Leave", (now - timedelta(days=1)).strftime("%Y-%m-%d"), (now + timedelta(days=3)).strftime("%Y-%m-%d"), "Attending State Maternal Health Workshop", now_str, "admin"),
        ("Dr. R. K. Verma", "Emergency Medical Officer", 1, "+91-98111-22334", "14:00", "20:00", "Mon, Tue, Wed, Thu, Fri, Sun", "Unavailable", None, None, "Off-shift until afternoon rotation", now_str, "admin"),
        ("Dr. Meera Swaminathan", "Chief Medical Officer", 2, "+91-98111-22335", "08:30", "16:30", "Mon, Tue, Wed, Thu, Fri", "On Duty", None, None, None, now_str, "admin"),
        ("Dr. Alok Sen", "Orthopaedist", 2, "+91-98111-22336", "09:00", "13:00", "Mon, Wed, Fri", "Available", None, None, None, now_str, "admin"),
        ("Dr. Sunita Rao", "Community Health Officer (CHO)", 3, "+91-98111-22337", "09:00", "17:00", "Mon, Tue, Wed, Thu, Fri, Sat", "On Duty", None, None, None, now_str, "admin")
    ]
    cursor.executemany("""
        INSERT INTO doctors (
            name, specialty, centre_id, contact_phone, duty_start_time, duty_end_time,
            scheduled_days, current_status, leave_start_date, leave_end_date,
            leave_reason, last_status_update, updated_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, doctors)

    # 6. Beds (Individual beds with ward, status, validation)
    # Green Valley PHC (10 beds)
    # Sunrise CHC (12 beds)
    # Riverside SC (2 beds)
    beds = [
        # GV PHC
        ("GW-01", 1, "General Ward", "Occupied", "PT-GV-101", now_str, "Male post-operative recovery"),
        ("GW-02", 1, "General Ward", "Occupied", "PT-GV-104", now_str, "Dengue monitoring"),
        ("GW-03", 1, "General Ward", "Available", None, now_str, "Cleaned & sanitized"),
        ("GW-04", 1, "General Ward", "Available", None, now_str, "Cleaned & sanitized"),
        ("MW-01", 1, "Maternity Ward", "Occupied", "PT-GV-202", now_str, "Post-natal observation"),
        ("MW-02", 1, "Maternity Ward", "Available", None, now_str, "Prepared for admission"),
        ("EM-01", 1, "Emergency Ward", "Occupied", "PT-GV-305", now_str, "Trauma stabilisation"),
        ("EM-02", 1, "Emergency Ward", "Available", None, now_str, "Oxygen supply checked"),
        ("ISO-01", 1, "Isolation Ward", "Out of Service", None, now_str, "UV light sterilization equipment repair"),
        ("ISO-02", 1, "Isolation Ward", "Available", None, now_str, "Standby ready"),

        # Sunrise CHC
        ("GW-101", 2, "General Ward", "Occupied", "PT-SR-501", now_str, "Acute gastroenteritis"),
        ("GW-102", 2, "General Ward", "Occupied", "PT-SR-503", now_str, "Fracture traction"),
        ("GW-103", 2, "General Ward", "Available", None, now_str, "Ready"),
        ("GW-104", 2, "General Ward", "Available", None, now_str, "Ready"),
        ("ICU-01", 2, "Intensive Care Unit (ICU)", "Occupied", "PT-SR-901", now_str, "Cardiac monitor active"),
        ("ICU-02", 2, "Intensive Care Unit (ICU)", "Available", None, now_str, "Ventilator tested"),
        ("MW-101", 2, "Maternity Ward", "Occupied", "PT-SR-601", now_str, "Labour room transfer"),
        ("MW-102", 2, "Maternity Ward", "Occupied", "PT-SR-602", now_str, "Post-delivery observation"),

        # Riverside SC
        ("DAY-01", 3, "Day Care / Observation", "Available", None, now_str, "Primary triage cot"),
        ("DAY-02", 3, "Day Care / Observation", "Occupied", "PT-RS-011", now_str, "IV fluid hydration")
    ]
    cursor.executemany("""
        INSERT INTO beds (bed_number, centre_id, ward, status, patient_identifier, last_updated, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, beds)

    # 7. Patient Footfall (Past 7 days up to today)
    footfall_data = []
    base_counts = [
        (1, 42, 6, 3),  # 6 days ago
        (1, 48, 8, 4),  # 5 days ago
        (1, 39, 5, 2),  # 4 days ago
        (1, 55, 9, 5),  # 3 days ago
        (1, 62, 11, 6), # 2 days ago
        (1, 58, 8, 4),  # 1 day ago
        (1, 65, 12, 7), # Today

        # Sunrise CHC (higher capacity)
        (2, 85, 18, 9),
        (2, 92, 15, 8),
        (2, 88, 14, 7),
        (2, 104, 22, 12),
        (2, 110, 19, 11),
        (2, 98, 16, 9),
        (2, 105, 20, 14),

        # Riverside SC
        (3, 18, 2, 1),
        (3, 15, 1, 0),
        (3, 20, 3, 2),
        (3, 22, 2, 1),
        (3, 19, 2, 2),
        (3, 24, 3, 1),
        (3, 21, 2, 1)
    ]

    for cid, op, em, ref in base_counts:
        # Determine day offset based on position
        pass

    # Populate 7 days for each centre
    for cid in (1, 2, 3):
        scale = 1.0 if cid == 1 else (1.8 if cid == 2 else 0.35)
        for d in range(6, -1, -1):
            date_str = (now - timedelta(days=d)).strftime("%Y-%m-%d")
            op = int((45 + (d * 3 % 11)) * scale)
            em = int((8 + (d % 4)) * scale)
            ref = int((4 + (d % 3)) * scale)
            tot = op + em + ref
            notes = "Peak morning footfall recorded" if d == 0 else "Normal operational day"
            footfall_data.append((cid, date_str, op, em, ref, tot, "staff" if cid == 1 else "sunrise_staff", notes, now_str))

    cursor.executemany("""
        INSERT INTO patient_footfall (
            centre_id, record_date, outpatient_count, emergency_count, referral_count,
            total_count, recorded_by, notes, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, footfall_data)

    # 8. Housekeeping Staff
    cleaning_staff = [
        ("Ramesh Kumar", 1, "General Ward & Corridor", 1, "+91-97000-11111"),
        ("Sunita Devi", 1, "Maternity Ward & Emergency", 1, "+91-97000-11112"),
        ("Mahesh Yadav", 1, "Sanitary Blocks & Waste Disposal", 1, "+91-97000-11113"),
        ("Geeta Bai", 2, "Inpatient Wards & ICU", 1, "+91-97000-22221"),
        ("Santosh Lal", 2, "OPD Reception & Waiting Area", 1, "+91-97000-22222"),
        ("Babloo Singh", 3, "Entire Health Sub-Centre Facility", 1, "+91-97000-33331")
    ]
    cursor.executemany("""
        INSERT INTO cleaning_staff (name, centre_id, assigned_area, is_active, phone)
        VALUES (?, ?, ?, ?, ?)
    """, cleaning_staff)

    # 9. Cleaning Tasks (Checklists, overdue tasks, pending, completed)
    checklist_standard = json.dumps([
        "Floor swept and mopped with hospital-grade disinfectant",
        "Bio-medical waste bins cleared into designated color-coded bags",
        "High-touch surfaces (bed railings, door knobs, taps) sanitized",
        "Hand sanitizer stations refilled and verified",
        "Restrooms cleaned and odor neutralizer applied"
    ])
    completed_checklist_full = json.dumps([0, 1, 2, 3, 4])
    completed_checklist_partial = json.dumps([0, 1])

    cleaning_tasks = [
        # Completed morning task
        (1, "General Ward & Corridor", 1, (now - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M"), "Completed", (now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M"), checklist_standard, completed_checklist_full, "Morning shift sanitation completed thoroughly."),
        # In progress task
        (1, "Maternity Ward & Emergency", 2, (now - timedelta(minutes=45)).strftime("%Y-%m-%d %H:%M"), "In Progress", None, checklist_standard, completed_checklist_partial, "Sanitizing delivery bay after patient discharge."),
        # OVERDUE task (scheduled 2 hours ago, still pending)
        (1, "Sanitary Blocks & Public Restrooms", 3, (now - timedelta(hours=2, minutes=15)).strftime("%Y-%m-%d %H:%M"), "Pending", None, checklist_standard, "[]", "Urgent cleaning required after morning OPD rush."),
        # Pending afternoon task
        (1, "Pharmacy & Medicine Store", 1, (now + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M"), "Pending", None, checklist_standard, "[]", "Scheduled mid-day sweep and shelf dust-off."),
        # Sunrise CHC tasks
        (2, "Inpatient Wards & ICU", 4, (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M"), "Completed", (now - timedelta(minutes=20)).strftime("%Y-%m-%d %H:%M"), checklist_standard, completed_checklist_full, "ICU bio-cleaning protocol followed."),
        (2, "OPD Reception & Waiting Area", 5, (now - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M"), "Pending", None, checklist_standard, "[]", "Area heavily crowded; scheduled cleaning delayed.")
    ]
    cursor.executemany("""
        INSERT INTO cleaning_tasks (
            centre_id, area, staff_id, scheduled_time, status, last_completed_time,
            checklist_json, completed_checklist_json, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, cleaning_tasks)

    # 10. Sample Priority Alerts (Initial seed)
    alerts = [
        ("BAT-004-EXPIRED", 1, "CRITICAL", "inventory", "Expired Medicine Stock In Inventory", "Batch BAT-004 (Ciprofloxacin Eye Drops) expired 15 days ago. Immediate quarantine and disposal required.", (now - timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S")),
        ("BAT-002-SHORTAGE", 1, "HIGH", "inventory", "Low Medicine Stock Warning", "Amoxicillin 500mg (BAT-002) has only 8 strips remaining, below threshold of 25. Stock predicted to deplete in 1-2 days.", (now - timedelta(hours=4)).strftime("%Y-%m-%d %H:%M:%S")),
        ("BAT-003-EXPIRING", 1, "MEDIUM", "inventory", "Medicine Nearing Expiry", "ORS Sachets (BAT-003) expires within 12 days. Prioritize first-expiry-first-out (FEFO) dispensing.", (now - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")),
        ("TASK-OVERDUE-01", 1, "MEDIUM", "cleaning", "Housekeeping Task Overdue", "Sanitary Blocks & Public Restrooms cleaning was scheduled 2 hours ago and is still pending.", (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")),
        ("BED-ISO-REPAIR", 1, "INFO", "beds", "Bed Out Of Service", "Bed ISO-01 (Isolation Ward) marked Out of Service for equipment maintenance.", (now - timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S"))
    ]
    cursor.executemany("""
        INSERT INTO alerts (
            alert_key, centre_id, severity, category, title, message, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, alerts)

    conn.commit()

    # Seed equipment, ambulances, and assets
    seed_additional_modules(conn)


def seed_additional_modules(conn):
    """Seed demo records for Equipment, Ambulances, and Facility Assets."""
    cursor = conn.cursor()
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    # 1. Equipment Items
    equipment = [
        ("EQ-WC-01", "Standard Foldable Wheelchair", "Wheelchair", 1, "OPD Entrance", "Available", (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M"), "Fully functional and disinfected"),
        ("EQ-WC-02", "Bariatric Heavy-Duty Wheelchair", "Wheelchair", 1, "General Ward", "In Use", (now - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M"), "Allotted to patient in General Ward"),
        ("EQ-WC-03", "Pediatric Wheelchair", "Wheelchair", 1, "Emergency Triage", "Available", (now - timedelta(hours=5)).strftime("%Y-%m-%d %H:%M"), "Ready at triage entrance"),
        ("EQ-STR-01", "Emergency Trauma Stretcher", "Stretcher", 1, "Emergency Ward", "In Use", (now - timedelta(hours=6)).strftime("%Y-%m-%d %H:%M"), "Currently in use for trauma observation"),
        ("EQ-STR-02", "Hydraulic Patient Stretcher", "Stretcher", 1, "Casualty Corridor", "Available", (now - timedelta(days=2)).strftime("%Y-%m-%d %H:%M"), "Sterilized and prepared"),
        ("EQ-O2-01", "Mobile Oxygen Cylinder Trolley", "Oxygen Transport", 1, "General Ward", "Under Maintenance", (now - timedelta(days=3)).strftime("%Y-%m-%d %H:%M"), "Regulator pressure gauge valve inspection"),
        ("EQ-IV-01", "Adjustable Mobile IV Stand", "IV Stand", 1, "Maternity Ward", "Damaged", (now - timedelta(days=4)).strftime("%Y-%m-%d %H:%M"), "Caster wheel broken, blocked from allotment"),
        ("EQ-WC-101", "Standard Foldable Wheelchair", "Wheelchair", 2, "OPD Reception", "Available", (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M"), "CHC reception standby"),
        ("EQ-STR-101", "Emergency Stretcher", "Stretcher", 2, "Emergency Entrance", "Available", (now - timedelta(hours=12)).strftime("%Y-%m-%d %H:%M"), "CHC emergency bay ready")
    ]
    cursor.executemany("""
        INSERT INTO equipment_items (
            equipment_code, name, category, centre_id, current_ward, current_status, last_sanitized_time, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, equipment)

    # 2. Equipment Allotments
    allotments = [
        # Active normal allotment
        (2, 1, "PT-GV-101", "Ramesh Sen", "General Ward", (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"), (now + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"), "staff", None, None, None, "Active", "Post-op ward transfer"),
        # Active OVERDUE allotment (Expected return was 2 hours ago!)
        (4, 1, "PT-GV-305", "Aakash Varma", "Emergency Ward", (now - timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S"), (now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"), "staff", None, None, None, "Active", "Emergency trauma room transfer"),
        # Returned allotment
        (1, 1, "PT-GV-088", "Deepak Joshi", "OPD", (now - timedelta(days=1, hours=3)).strftime("%Y-%m-%d %H:%M:%S"), (now - timedelta(days=1, hours=1)).strftime("%Y-%m-%d %H:%M:%S"), "staff", (now - timedelta(days=1, hours=1)).strftime("%Y-%m-%d %H:%M:%S"), "staff", "Good", "Returned", "Returned promptly without damage")
    ]
    cursor.executemany("""
        INSERT INTO equipment_allotments (
            equipment_id, centre_id, patient_visit_id, patient_name, ward, issue_time,
            expected_return_time, issuing_staff, actual_return_time, receiving_staff,
            return_condition, status, return_notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, allotments)

    # 3. Equipment Maintenance / Sanitization Log
    eq_maintenance = [
        (6, 1, "Maintenance", "admin", (now - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"), "Replaced flow valve washer on oxygen trolley"),
        (1, 1, "Sanitization", "staff", (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"), "Thorough disinfectant washdown upon OPD return")
    ]
    cursor.executemany("""
        INSERT INTO equipment_maintenance_history (
            equipment_id, centre_id, action_type, performed_by, timestamp, details
        ) VALUES (?, ?, ?, ?, ?, ?)
    """, eq_maintenance)

    # 4. Ambulances Fleet
    ambulances = [
        ("AMB-GV-01", "DL-01-AB-1234", 1, "Basic Life Support (BLS)", "Rajesh Yadav", "+91-98765-11001", "Available", "2027-06-30", "2027-05-15", (now - timedelta(days=40)).strftime("%Y-%m-%d"), (now + timedelta(days=50)).strftime("%Y-%m-%d"), "Oxygen cylinder, folding stretcher, suction machine, primary first aid kit", now_str, "admin"),
        ("AMB-GV-02", "DL-01-AB-5678", 1, "Patient Transport", "Vikram Rathore", "+91-98765-11002", "Dispatched / On Trip", "2027-08-15", "2027-07-20", (now - timedelta(days=20)).strftime("%Y-%m-%d"), (now + timedelta(days=70)).strftime("%Y-%m-%d"), "Foldable transfer wheelchair, patient ramp, standard first aid box", now_str, "staff"),
        ("AMB-SR-01", "MH-12-EQ-5501", 2, "Advanced Life Support (ALS)", "Suresh Patil", "+91-98765-22001", "Available", "2027-09-10", "2027-08-15", (now - timedelta(days=15)).strftime("%Y-%m-%d"), (now + timedelta(days=75)).strftime("%Y-%m-%d"), "Transport ventilator, multi-para cardiac monitor, biphasic defibrillator, syringe pump", now_str, "admin"),
        ("AMB-SR-02", "MH-12-EQ-5502", 2, "Basic Life Support (BLS)", "Mukesh Shinde", "+91-98765-22002", "Under Maintenance", "2026-12-20", "2026-11-25", (now - timedelta(days=80)).strftime("%Y-%m-%d"), (now + timedelta(days=10)).strftime("%Y-%m-%d"), "Oxygen unit, emergency cot, basic medical kit", now_str, "admin")
    ]
    cursor.executemany("""
        INSERT INTO ambulances (
            vehicle_code, registration_number, centre_id, ambulance_type, primary_driver_name,
            driver_contact, status, fitness_cert_expiry, insurance_expiry, last_service_date,
            next_service_due, equipment_specs, last_status_update, updated_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, ambulances)

    # 5. Ambulance Trips
    ambulance_trips = [
        (2, 1, "Inter-Facility Hospital Transfer", "PT-GV-305", "District Civil Hospital Emergency", (now - timedelta(minutes=45)).strftime("%Y-%m-%d %H:%M"), (now + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M"), None, "Vikram Rathore", "Priya Patel", "In Transit", "Transfer of head injury trauma patient"),
        (1, 1, "Emergency Pickup", "PT-GV-201", "Green Valley Village Sector 2", (now - timedelta(days=1, hours=4)).strftime("%Y-%m-%d %H:%M"), (now - timedelta(days=1, hours=2)).strftime("%Y-%m-%d %H:%M"), (now - timedelta(days=1, hours=2)).strftime("%Y-%m-%d %H:%M"), "Rajesh Yadav", "Priya Patel", "Completed", "Emergency maternal delivery transport")
    ]
    cursor.executemany("""
        INSERT INTO ambulance_trips (
            ambulance_id, centre_id, trip_purpose, patient_identifier, destination,
            departure_time, expected_return_time, actual_return_time, driver_name,
            paramedic_staff, status, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, ambulance_trips)

    # 6. Facility Assets
    facility_assets = [
        ("AST-GV-GEN-01", "Main Backup Diesel Generator 15kVA", "Power & Electrical", 1, "Utility Shed Bay 1", "Operational", "2023-04-10", (now - timedelta(days=60)).strftime("%Y-%m-%d"), (now + timedelta(days=30)).strftime("%Y-%m-%d"), "Kirloskar KG15-Silent", "Apex Power Systems"),
        ("AST-GV-COLD-01", "Cold Chain Vaccine Deep Refrigerator", "Cold Chain & Refrigeration", 1, "Immunization Room", "Operational", "2024-01-15", (now - timedelta(days=30)).strftime("%Y-%m-%d"), (now + timedelta(days=60)).strftime("%Y-%m-%d"), "Vestfrost VLS-024", "National Cold Chain Care"),
        ("AST-GV-RO-01", "Hospital RO Water Purification Plant 500 LPH", "Water & Sanitation", 1, "Basement Water Facility", "Needs Attention", "2023-08-20", (now - timedelta(days=90)).strftime("%Y-%m-%d"), (now - timedelta(days=5)).strftime("%Y-%m-%d"), "Kent Industrial RO-500", "AquaTech Industrial"),
        ("AST-GV-AC-01", "Minor OT Split Air Conditioner 2.0 Ton", "HVAC & Climate", 1, "Minor Operation Theater", "Under Repair", "2023-06-12", (now - timedelta(days=45)).strftime("%Y-%m-%d"), (now + timedelta(days=45)).strftime("%Y-%m-%d"), "Voltas Inverter 243V", "CoolPoint Services"),
        ("AST-SR-XRAY-01", "Digital High-Frequency Radiography X-Ray", "Diagnostic & Imaging", 2, "Radiology Suite Room 4", "Operational", "2024-03-01", (now - timedelta(days=20)).strftime("%Y-%m-%d"), (now + timedelta(days=160)).strftime("%Y-%m-%d"), "Allengers HF-59", "Allengers Medical Tech"),
        ("AST-SR-GEN-01", "Heavy Standby Generator 30kVA", "Power & Electrical", 2, "Generator Enclosure Yard", "Operational", "2023-11-05", (now - timedelta(days=40)).strftime("%Y-%m-%d"), (now + timedelta(days=50)).strftime("%Y-%m-%d"), "Mahindra Powerol 30", "Apex Power Systems")
    ]
    cursor.executemany("""
        INSERT INTO facility_assets (
            asset_tag, name, category, centre_id, location, condition_status,
            installation_date, last_service_date, next_service_due, model_serial, vendor_support
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, facility_assets)

    # 7. Maintenance Work Orders
    work_orders = [
        ("WO-2026-001", 4, 1, "HIGH", "Minor OT Split AC cooling gas leak; operating room temperature exceeding clinical protocol threshold.", "staff", (now - timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S"), "Manoj Sharma (CoolPoint)", "Open", 3500.0, 0.0, None, None, None),
        ("WO-2026-002", 3, 1, "MEDIUM", "RO plant membrane differential pressure warning; filter cartridge replacement due.", "staff", (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"), "AquaTech Technician", "In Progress", 1800.0, 0.0, "Technician dispatched with replacement filters", None, None),
        ("WO-2026-003", 1, 1, "LOW", "Quarterly generator engine oil, air filter, and battery terminal routine service.", "admin", (now - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S"), "Apex Power Tech", "Resolved", 4200.0, 4200.0, "Oil changed, test load run successful for 30 minutes", (now - timedelta(days=8)).strftime("%Y-%m-%d %H:%M:%S"), "admin")
    ]
    cursor.executemany("""
        INSERT INTO maintenance_work_orders (
            work_order_code, asset_id, centre_id, priority, issue_description,
            reported_by, reported_at, assigned_technician, status, estimated_cost,
            actual_cost, resolution_notes, resolved_at, resolved_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, work_orders)

    conn.commit()


if __name__ == "__main__":
    print(f"Initializing database at: {get_db_path()}")
    init_db()
    print("Database schema created and demo data successfully seeded.")
