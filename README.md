# SmartHealth — Smart Health Centre Management System
### AI-Driven Health Center & Supply Chain Management • Hack2skill Challenge

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Flask 3.0+](https://img.shields.io/badge/framework-Flask%203.0-teal.svg)](https://flask.palletsprojects.com/)
[![Tests](https://img.shields.io/badge/tests-27%20passed-brightgreen.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**SmartHealth** is a responsive, beginner-friendly web application designed to empower **Primary Health Centres (PHCs)** and **Community Health Centres (CHCs)**. It addresses critical operational bottlenecks in rural and community healthcare: medicine inventory stockouts, expired drug hazards, bed occupancy crises, doctor availability tracking, patient footfall surges, and housekeeping hygiene.

---

## Table of Contents
1. [Key Features](#key-features)
2. [Technology Stack](#technology-stack)
3. [Project Directory Structure](#project-directory-structure)
4. [Quickstart: Local Installation & Running](#quickstart-local-installation--running)
5. [Demo User Accounts & Credentials](#demo-user-accounts--credentials)
6. [Feature Walkthrough & How to Test](#feature-walkthrough--how-to-test)
7. [Running Automated Tests](#running-automated-tests)
8. [Honest Architectural Notes & Demo Boundaries](#honest-architectural-notes--demo-boundaries)
9. [Deployment Guide: Google Cloud Run](#deployment-guide-google-cloud-run)
10. [Security & Privacy Practices](#security--privacy-practices)

---

## 1. Key Features

### 📊 Main Healthcare Executive Dashboard
- **7 Core Operational Cards:** Today's Patient Footfall (OPD, Emergency, Referrals), Available vs Occupied Beds, Total Medicine Batches, Low-Stock Alerts, Expiry Warnings, Doctors on Duty vs Leave, and Pending Housekeeping.
- **Facility-Wise Filtering:** View individual health centres or an overall consolidated summary across all centres.
- **Visual Footfall Trends:** 7-day chronological volume chart.
- **Recent Audit Activity Feed:** Real-time stream of latest dispensary and delivery events.

### 💊 Medicine Inventory & QR Codes
- **Batch Tracking:** Medicine brand, generic name, manufacturer batch number, unique system batch ID, available quantity, minimum stock threshold, packaging unit, expiry date, storage conditions, and shelf location.
- **Dynamic QR Code Generation:** Real-time PNG generation using Python's `qrcode` library. Encodes safe batch identifiers (`SMARTHEALTH:BATCH:<batch_id>`)—never user credentials or sensitive patient data.
- **Printable QR Shelf Labels:** Clean, high-contrast labels formatted with print CSS (`@media print`) for barcode/sticker printers.
- **Camera QR Scanner & Manual Lookup:** Scans via device camera (HTML5) with automatic fallback to manual batch/lot lookup. Displays live usable stock and flags immediately.
- **Expiry Protection:** Configurable 30-day threshold. Expired batches are clearly flagged in red and **strictly excluded from usable inventory calculations**.

### 📈 Explainable Stock Forecasting
- **Transparent Formula:** Calculates average daily usage from verified dispensary logs:
  $$\text{Average Daily Usage} = \frac{\text{Total Units Used}}{\text{Date Span (Days)}}$$
  $$\text{Days Remaining} = \frac{\text{Usable Stock}}{\text{Average Daily Usage}}$$
- **Depletion Urgency:** Flags medicines as Critical ($\le 3$ days), High Risk ($\le 7$ days), Moderate ($8\text{--}14$ days), or Healthy ($> 14$ days).
- **Insufficient History Warning:** Explicitly notifies staff when fewer than 2 usage records exist over separate days.
- **No False ML Claims:** Clearly labeled as an explainable moving-window arithmetic estimate, not an opaque AI model.

### 📜 Immutable Stock Audit Trail
- Every transaction (Stock Received, Stock Used, Expired Stock Removed, Correction) permanently logs previous quantity, delta, new balance, staff username, timestamp, and clinical notes.
- **Negative Stock Prevention:** Strictly blocks attempts to deduct more units than physically available.
- **No UI Modification:** Normal users and staff cannot silently alter or delete audit history entries.

### 🚨 Priority-Based Alert Engine
- **4 Severity Tiers:** `CRITICAL` (expired drugs, zero stock), `HIGH` (depletion in $\le 3$ days), `MEDIUM` (expiring in 30 days, overdue cleaning), `INFO` (bed out of service).
- **Non-Destructive Acknowledgment:** Staff can acknowledge alerts to record awareness without falsely removing the underlying facility issue.

### 🏥 Multi-Centre Facility Support
- Pre-seeded with 3 realistic facilities:
  1. *Green Valley Primary Health Centre (PHC)*
  2. *Sunrise Community Health Centre (CHC)*
  3. *Riverside Sub-Centre (SC)*
- Prevents accidental cross-centre record modifications.

### 👨‍⚕️ Doctor Duty Rosters & Attendance
- Tracks doctor specialty, scheduled clinic hours (e.g., 08:00–14:00, Mon–Fri), confirmed real-time presence (`On Duty`, `Available`, `Unavailable`, `On Leave`), approved leave dates, and leave reasons.
- **Scheduled vs Confirmed:** Clear distinction between rostered shifts and confirmed staff presence. No fake live GPS tracking claims.

### 🛏️ Bed Management & Single-State Validation
- Tracks beds by ward (General Ward, Maternity, ICU, Emergency, Day Care).
- **Single-State Integrity:** Strict validation ensures a bed cannot be marked both Available and Occupied. Marking Available automatically clears patient identifier tags.

### 👥 Aggregate Patient Footfall
- Records non-negative daily patient counts for Outpatient (OPD), Emergency Admissions, and Inter-facility Referrals.
- Protects patient privacy by storing aggregate numbers instead of collecting unnecessary personal health information (PHI).

### 🧹 Housekeeping & Sanitation Checklists
- Tracks cleaning tasks, assigned staff, scheduled times, overdue warnings, and completion timestamps.
- Interactive multi-point hygiene verification checklist.
- Clearly notes that active staff employment does not equate to automatic task completion.

### 📥 Downloadable CSV Reports & Formula Sanitization
- One-click exports for: Inventory, Low-Stock items, Audit Trail, Doctor Schedules, Beds, Patient Footfall, and Cleaning Tasks.
- **Formula Injection Sanitization:** Safely neutralizes cells starting with `=`, `+`, `-`, `@`, `\t`, or `\r` by prepending `'` to protect Excel users from CSV Injection.

### 📴 Offline-Friendly Shell & Local Drafts
- Service Worker caches application shell (CSS, JavaScript, icons, HTML shell).
- Real-time online/offline network badge and alert banner.
- Offline draft storage in `localStorage` clearly tagged as *Draft - Unsynced (Local Device Only)* with a reconnection notification.

---

## 2. Technology Stack

- **Backend:** Python 3.10+ / 3.11 / 3.12 / 3.14 with **Flask** (modular blueprints, clean separation of database and routes).
- **Database:** Standard library **SQLite** (`sqlite3`) with parameterized queries (`?`) to prevent SQL injection.
- **QR Code Engine:** Python `qrcode` library with `Pillow` image generation.
- **Frontend:** Pure HTML5, modern CSS3 (responsive grid, accessible contrast, `@media print`), vanilla JavaScript.
- **Testing:** `pytest` (27 comprehensive unit and integration tests).
- **Production Server:** `gunicorn` (WSGI server configured for Google Cloud Run).

---

## 3. Project Directory Structure

```
SmartHealth_project/
├── app.py                     # Flask application factory, error handlers, /health check
├── database.py                # SQLite schema setup, dynamic context DB resolver, demo seeding
├── auth.py                    # Login, logout, PBKDF2 hashing, session management, CSRF validation
├── inventory.py               # Medicine batches, stock receive/use, QR generation, lookup API
├── forecasting.py             # Explainable stock depletion calculations and disclaimers
├── audit.py                   # Immutable stock transaction audit trail
├── alerts.py                  # Priority alert engine (CRITICAL, HIGH, MEDIUM, INFO)
├── doctors.py                 # Doctor duty rosters, status updates, leave management
├── beds.py                    # Bed inventory, ward tracking, single-state validation
├── footfall.py                # Aggregate patient volume tracking and weekly trends
├── cleaning.py                # Housekeeping tasks, hygiene checklists, overdue tracking
├── reports.py                 # Downloadable CSV report generator with formula sanitization
├── requirements.txt           # Python package dependencies
├── Dockerfile                 # Google Cloud Run production container configuration
├── .dockerignore              # Files excluded from Docker builds
├── .gitignore                 # Files excluded from Git version control
├── pytest.ini                 # Pytest configuration
├── static/
│   ├── css/
│   │   └── style.css          # Healthcare design system, badges, responsive layout, print styles
│   ├── js/
│   │   ├── main.js            # Network detection, modals, toast alerts, offline draft queue
│   │   └── qr_scanner.js      # Camera scanner, fallback manual batch lookup
│   ├── sw.js                  # Service Worker for offline app shell caching
│   └── manifest.json          # PWA web manifest
├── templates/
│   ├── base.html              # Base layout with sidebar, navbar, flash banners, offline tray
│   ├── error.html             # Generic HTTP error handler (400, 403, 404, 500)
│   ├── login.html             # Secure login form with demo credentials guide
│   ├── dashboard.html         # Executive operational dashboard with 7 summary cards
│   ├── inventory/
│   │   ├── list.html          # Batch table, status badges, stock adjustment modal
│   │   ├── form.html          # Register / edit medicine batch form
│   │   ├── qr_label.html      # Printable QR shelf label
│   │   └── scan.html          # Camera QR scanner and manual lookup
│   ├── forecasting/
│   │   └── index.html         # Stock depletion forecasting dashboard
│   ├── audit/
│   │   └── index.html         # Searchable immutable audit trail
│   ├── alerts/
│   │   └── index.html         # Priority alerts with non-destructive acknowledgment
│   ├── doctors/
│   │   └── index.html         # Doctor rosters, presence tracking, leave modal
│   ├── beds/
│   │   └── index.html         # Ward occupancy grid and bed update modal
│   ├── footfall/
│   │   └── index.html         # Daily patient volume logger and weekly charts
│   ├── cleaning/
│   │   └── index.html         # Housekeeping checklists and overdue area monitors
│   └── reports/
│       └── index.html         # Central CSV report export hub
└── tests/
    ├── conftest.py            # Pytest test fixtures and isolated SQLite DB setup
    ├── test_auth.py           # Authentication, RBAC, session, CSRF tests
    ├── test_inventory.py      # Inventory additions, stock adjustments, negative stock block, QR
    ├── test_forecasting.py    # Forecasting calculation logic and disclaimers
    ├── test_audit.py          # Automatic immutable audit log creation
    ├── test_alerts.py         # Priority alerts and non-destructive acknowledgment
    ├── test_doctors.py        # Doctor roster updates and leave dates
    ├── test_beds.py           # Bed status update and single-state validation
    ├── test_footfall.py       # Patient footfall non-negative validation
    ├── test_cleaning.py       # Cleaning tasks and checklist updates
    ├── test_reports.py        # CSV downloads and formula injection sanitization
    └── test_health.py         # /health endpoint verification
```

---

## 4. Quickstart: Local Installation & Running

Follow these simple steps to run SmartHealth on your computer:

### Step 1: Open Terminal / PowerShell
Navigate to the project directory:
```powershell
cd c:\Users\Gaurav\Downloads\SmartHealth_project
```

### Step 2: Create and Activate Virtual Environment
```powershell
# Windows PowerShell:
python -m venv venv
.\venv\Scripts\Activate.ps1

# Linux / macOS:
# python3 -m venv venv
# source venv/bin/activate
```

### Step 3: Install Required Packages
```powershell
pip install -r requirements.txt
```

### Step 4: Initialize the Demo Database (Optional)
The application will automatically initialize and seed the database on first run, or you can run:
```powershell
python database.py
```

### Step 5: Start the Server
```powershell
python app.py
```
Output:
```
Starting SmartHealth Server on http://0.0.0.0:8080
```

### Step 6: Open in Web Browser
Open your browser and navigate to:
[http://127.0.0.1:8080](http://127.0.0.1:8080)

---

## 5. Demo User Accounts & Credentials

The system seeds three demo user accounts for evaluation:

| Role | Username | Password | Assigned Health Centre | Capabilities |
| :--- | :--- | :--- | :--- | :--- |
| **Administrator** | `admin` | `Admin@123` | All Facilities (Consolidated) | Full system access, multi-centre management, system configuration |
| **PHC Staff** | `staff` | `Staff@123` | Green Valley PHC | Inventory updates, doctor attendance, bed status, footfall logging |
| **CHC Staff** | `sunrise_staff` | `Staff@123` | Sunrise CHC | Inventory management, housekeeping verification, facility updates |

> 🔒 *Security Note:* Passwords in the database are hashed using PBKDF2 with SHA-256 salts. Plaintext passwords are never stored.

---

## 6. Feature Walkthrough & How to Test

### 1. Test Facility Switching
- In the top navigation bar, use the **Facility** dropdown.
- Select **Green Valley PHC** or **Sunrise CHC**. Notice how dashboard metrics, inventory counts, and bed occupancies dynamically update. Select **All Health Centres** for a consolidated view.

### 2. Test Medicine Inventory & Negative Stock Prevention
1. Go to **Medicine Inventory** (`/inventory/`).
2. Click **⚡ Stock** next to *Paracetamol 500mg* (`BAT-001`).
3. Select **Dispense / Stock Usage (-)** and enter quantity `20`. Click **Record Stock Update**. Notice stock decrements from 140 to 120, and a flash message appears.
4. Try to deduct `9999` units. Notice the system strictly rejects the transaction with: *"Negative stock is strictly disallowed."*
5. Notice *Batch BAT-004 (Ciprofloxacin Eye Drops)* is displayed with an **EXPIRED** badge and is clearly excluded from usable inventory calculations.

### 3. Test QR Codes & Shelf Labels
1. In the Inventory list, click **🖨️ QR** next to any batch.
2. A dedicated, high-resolution shelf label opens with a dynamic QR code. Click **Print Label Now** to trigger print formatting.
3. Visit the **QR Scanner** (`/inventory/scan`).
   - If a camera is connected, click **Start Camera**.
   - Or test the manual fallback: type `BAT-001` or click the quick demo pill. The system displays verified medicine details, stock balance, and expiry flags.

### 4. Test Stock Depletion Forecasting
1. Navigate to **Stock Forecasting** (`/forecasting/`).
2. Review the transparent calculation table:
   - *Amoxicillin 500mg* is flagged as **HIGH RISK** (approx. 1–2 days remaining).
   - Unused batches show a clear message: *"Insufficient usage history. At least 2 recorded stock usage transactions over separate days are required."*
   - Expired batches show **EXPIRED** with 0 usable stock.

### 5. Test Priority Alerts & Acknowledgment
1. Go to **Priority Alerts** (`/alerts/`).
2. Filter by **CRITICAL** to view expired medicine alerts.
3. Click **Acknowledge** on an alert.
4. The alert shows as acknowledged by your username with a timestamp, while the warning banner clearly reminds staff: *"Acknowledging registers awareness but does not resolve the physical condition."*

### 6. Test Bed Capacity & Single-State Validation
1. Go to **Bed Management** (`/beds/`).
2. Click **Update Status** on Bed `GW-01`.
3. Set status to **Occupied** and enter patient tag `PT-TEST-101`. Click Save.
4. Now update `GW-01` to **Available**. Notice that the patient tag input is disabled and cleared automatically, preventing a bed from being marked both Available and Occupied.

### 7. Test Doctor Roster & Attendance
1. Go to **Doctor Duty Roster** (`/doctors/`).
2. Click **Update Status** on any doctor.
3. Change status to **On Leave**, enter leave dates and a reason (e.g. *Maternal health conference*), and save.
4. The roster updates with leave details, current server timestamp, and updater username.

### 8. Test CSV Reports & Formula Sanitization
1. Go to **Download Reports (CSV)** (`/reports/`).
2. Download any of the 7 reports.
3. Open the file in a text editor or spreadsheet to verify clean formatting and note that spreadsheet formula triggers (`=`, `+`, `-`, `@`) are safely escaped.

### 9. Test Offline Mode
1. In your browser's Developer Tools (F12) -> **Network**, set throttling to **Offline**.
2. Notice the network badge immediately switches to **● Offline Mode** (red) and the top offline alert banner appears.
3. Re-enable network to see the status switch back to **● Online** (green).

---

## 7. Running Automated Tests

The project includes an automated test suite written with `pytest` covering 27 test cases across all critical functional workflows.

To run the test suite:
```powershell
# Run all tests with verbose output:
python -m pytest -v
```

### Actual Test Execution Output:
```
tests/test_audit.py::test_audit_log_created_on_stock_adjustment PASSED   [  3%]
tests/test_audit.py::test_audit_index_page PASSED                        [  7%]
tests/test_auth.py::test_login_page_renders PASSED                       [ 11%]
tests/test_auth.py::test_protected_route_requires_login PASSED           [ 14%]
tests/test_auth.py::test_successful_login_and_logout PASSED              [ 18%]
tests/test_auth.py::test_failed_login_invalid_password PASSED            [ 22%]
tests/test_auth.py::test_staff_login PASSED                              [ 25%]
tests/test_beds.py::test_bed_management_page PASSED                      [ 29%]
tests/test_beds.py::test_bed_status_update_and_single_state_validation PASSED [ 33%]
tests/test_cleaning.py::test_cleaning_index_page PASSED                  [ 37%]
tests/test_cleaning.py::test_add_and_update_cleaning_task PASSED         [ 40%]
tests/test_doctors.py::test_doctor_index_page PASSED                     [ 44%]
tests/test_doctors.py::test_update_doctor_attendance_and_leave PASSED    [ 48%]
tests/test_footfall.py::test_footfall_index_page PASSED                  [ 51%]
tests/test_footfall.py::test_record_footfall_valid_and_invalid PASSED    [ 55%]
tests/test_forecasting.py::test_forecast_with_insufficient_history PASSED [ 59%]
tests/test_forecasting.py::test_forecast_with_multiple_usage_records PASSED [ 62%]
tests/test_forecasting.py::test_forecast_dashboard_page PASSED           [ 66%]
tests/test_health.py::test_health_check_endpoint PASSED                  [ 70%]
tests/test_inventory.py::test_evaluate_batch_status_logic PASSED         [ 74%]
tests/test_inventory.py::test_inventory_list_page PASSED                 [ 77%]
tests/test_inventory.py::test_add_medicine_batch PASSED                  [ 81%]
tests/test_inventory.py::test_adjust_stock_received_and_used PASSED      [ 85%]
tests/test_inventory.py::test_qr_code_generation PASSED                  [ 88%]
tests/test_inventory.py::test_api_batch_lookup PASSED                    [ 92%]
tests/test_reports.py::test_formula_injection_sanitization PASSED        [ 96%]
tests/test_reports.py::test_csv_report_downloads PASSED                  [100%]

============================= 27 passed in 15.07s =============================
```

---

## 8. Honest Architectural Notes & Demo Boundaries

In keeping with engineering integrity:
1. **SQLite Local Storage Boundary:** SQLite is used for this self-contained demo. On serverless platforms like Google Cloud Run, container filesystems are ephemeral (erased on container restarts/scaling). For a multi-user production deployment, the database connection should be pointed to a persistent managed database like Google Cloud SQL (PostgreSQL or MySQL) or a mounted persistent volume.
2. **Explainable Forecasting vs Machine Learning:** The system uses verified, deterministic arithmetic moving-window averages. It does not use black-box neural networks or invent synthetic records.
3. **Doctor Attendance vs Location Tracking:** The application tracks verified manual roster confirmations by facility administrators. It does not simulate or pretend to have live GPS location tracking of personnel.
4. **Aggregate Patient Footfall:** For citizen privacy and data minimization, aggregate daily counts (OPD, Emergency, Referrals) are recorded rather than individual electronic health records (EHR).

---

## 9. Deployment Guide: Google Cloud Run

SmartHealth is packaged with a production-ready `Dockerfile` and configured to run seamlessly on Google Cloud Run.

### Container Configuration Details:
- Listens on `0.0.0.0`.
- Dynamically reads the port from the `$PORT` environment variable (defaults to 8080).
- Exposes health check endpoint `/health` for container probes.
- Runs using multi-threaded `gunicorn` workers.

### Step-by-Step Google Cloud Run Deployment:

#### Prerequisites:
- Google Cloud SDK (`gcloud`) installed and logged in: `gcloud auth login`
- Google Cloud project created and selected: `gcloud config set project YOUR_PROJECT_ID`
- Cloud Run and Artifact Registry APIs enabled.

#### Build and Deploy with Google Cloud Build:
```bash
# 1. Build container image in Google Cloud Artifact Registry
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/smarthealth:latest

# 2. Deploy to Google Cloud Run
gcloud run deploy smarthealth \
  --image gcr.io/YOUR_PROJECT_ID/smarthealth:latest \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --port 8080 \
  --set-env-vars SECRET_KEY="generate-a-strong-random-secret-here"
```

#### Health-Check Endpoint:
Once deployed, verify container health:
```bash
curl https://smarthealth-xxxx.a.run.app/health
```
Response:
```json
{
  "database": "healthy",
  "environment": "production",
  "service": "SmartHealth",
  "status": "healthy",
  "timestamp": "2026-10-18T11:30:00.000000"
}
```

---

## 10. Security & Privacy Practices

- **Password Security:** Salted PBKDF2 with SHA-256 password hashing via `werkzeug.security`.
- **CSRF Defense:** Cryptographic session tokens validated on all state-changing `POST` requests.
- **SQL Injection Prevention:** 100% parameterized SQL statements (`?`).
- **CSV Injection Prevention:** Strict formula sanitization against spreadsheet trigger characters (`=`, `+`, `-`, `@`).
- **QR Code Security:** Encodes public batch identifiers (`SMARTHEALTH:BATCH:BAT-001`) only. Credentials, secret tokens, and private patient data are strictly excluded.
- **Role-Based Access Control:** Server-side route decorators (`@login_required`, `@role_required`) protect data integrity.

---

*Developed for the Hack2skill Smart Health Challenge: AI-Driven Health Center & Supply Chain Management.*
