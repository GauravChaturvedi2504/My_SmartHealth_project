"""
app.py - Main Flask Application Factory and Server Entry Point
for the SmartHealth Health Centre Management System.

Configured for local development as well as Google Cloud Run deployment:
- Binds to 0.0.0.0
- Respects PORT environment variable
- Exposes /health health-check endpoint
"""

import os
from datetime import datetime
from flask import Flask, jsonify, render_template, session
from database import init_db, get_db
from auth import auth_bp, get_current_user, generate_csrf_token
from dashboard import dashboard_bp
from inventory import inventory_bp
from forecasting import forecasting_bp
from audit import audit_bp
from alerts import alerts_bp
from doctors import doctors_bp
from beds import beds_bp
from footfall import footfall_bp
from cleaning import cleaning_bp
from reports import reports_bp
from equipment import equipment_bp
from ambulances import ambulances_bp
from assets import assets_bp


def create_app(test_config=None):
    """Create and configure the Flask application instance."""
    app = Flask(__name__, instance_relative_config=True)

    # Core configuration
    app.config.from_mapping(
        SECRET_KEY=os.environ.get('SECRET_KEY', 'smarthealth-secure-dev-key-2026-hack2skill'),
        DATABASE=os.environ.get('SMARTHEALTH_DB', 'smarthealth.db'),
    )

    if test_config is not None:
        app.config.update(test_config)

    # Initialize database tables and seed data if needed
    init_db(app.config.get('DATABASE'))

    # Context processors for global template variables
    @app.context_processor
    def inject_global_template_vars():
        user = get_current_user()
        active_c_id = session.get('active_centre_id', 0)
        c_name = "All Health Centres (Consolidated)"

        # Fetch active centre name if selected
        if active_c_id and active_c_id > 0:
            try:
                conn = get_db(app.config.get('DATABASE'))
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM health_centres WHERE id = ?", (active_c_id,))
                row = cursor.fetchone()
                conn.close()
                if row:
                    c_name = row['name']
            except Exception:
                pass

        return {
            'current_user': user,
            'csrf_token': generate_csrf_token,
            'active_centre_id': active_c_id,
            'active_centre_name': c_name,
            'app_version': '1.0.0',
            'current_year': datetime.now().year
        }

    # Health check endpoint for Google Cloud Run / Container orchestrators
    @app.route('/health')
    def health_check():
        """Health check endpoint returning 200 OK with operational metadata."""
        try:
            conn = get_db(app.config.get('DATABASE'))
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            conn.close()
            db_status = "healthy"
        except Exception as e:
            db_status = f"unhealthy: {str(e)}"

        return jsonify({
            "status": "healthy" if db_status == "healthy" else "degraded",
            "service": "SmartHealth",
            "database": db_status,
            "timestamp": datetime.now().isoformat(),
            "environment": os.environ.get("FLASK_ENV", "production")
        }), 200 if db_status == "healthy" else 503

    # Register Blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(forecasting_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(alerts_bp)
    app.register_blueprint(doctors_bp)
    app.register_blueprint(beds_bp)
    app.register_blueprint(footfall_bp)
    app.register_blueprint(cleaning_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(equipment_bp)
    app.register_blueprint(ambulances_bp)
    app.register_blueprint(assets_bp)

    # Standard error handlers
    @app.errorhandler(400)
    def bad_request(error):
        return render_template('error.html', code=400, title="Bad Request", message=str(error.description)), 400

    @app.errorhandler(403)
    def forbidden(error):
        return render_template('error.html', code=403, title="Forbidden", message="You do not have permission to perform this action."), 403

    @app.errorhandler(404)
    def not_found(error):
        return render_template('error.html', code=404, title="Page Not Found", message="The requested resource was not found on this server."), 404

    @app.errorhandler(500)
    def internal_error(error):
        return render_template('error.html', code=500, title="Internal Server Error", message="An unexpected error occurred. Please contact technical administration."), 500

    return app


if __name__ == '__main__':
    # Cloud Run passes PORT environment variable (default 8080)
    port = int(os.environ.get('PORT', 8080))
    app = create_app()
    print(f"Starting SmartHealth Server on http://0.0.0.0:{port}")
    app.run(host='0.0.0.0', port=port, debug=False)
