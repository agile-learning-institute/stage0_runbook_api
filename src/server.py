#!/usr/bin/env python3
"""
Flask API server for Stage0 Runbook Runner

Provides REST API endpoints for runbook operations.
Designed to be consumed by a separate SPA frontend.

This server follows the template_flask_mongo architecture pattern:
- Config singleton initialization
- Flask route registration with service layer
- Prometheus metrics integration
- JWT token authentication and authorization
- Graceful shutdown handling
"""
import sys
import signal
from pathlib import Path
from flask import Flask

import logging

def create_app():
    """
    Create and configure Flask application.
    
    This function is used by Gunicorn.
    
    Returns:
        Flask application instance
    """
    # Initialize Config Singleton (this configures logging in __init__)
    from src.config.config import Config
    config = Config.get_instance()
    
    logger = logging.getLogger(__name__)
    logger.info("============= Starting Stage0 Runbook API Server ===============")

    # Initialize Flask App
    from prometheus_flask_exporter import PrometheusMetrics
    
    app = Flask(__name__)
    
    # Apply Prometheus monitoring middleware - exposes /metrics endpoint (default)
    metrics = PrometheusMetrics(app)
    
    # Register Routes
    logger.info("Registering Routes")
    
    # Config routes
    from src.routes.config_routes import create_config_routes
    app.register_blueprint(create_config_routes(), url_prefix='/api/config')
    logger.info("  /api/config")
    
    # Dev login routes (if enabled)
    if config.ENABLE_LOGIN:
        from src.routes.dev_login_routes import create_dev_login_routes
        app.register_blueprint(create_dev_login_routes(), url_prefix='/dev-login')
        logger.info("  /dev-login")
    
    # Explorer routes (API documentation)
    from src.routes.explorer_routes import create_explorer_routes
    app.register_blueprint(create_explorer_routes(), url_prefix='/docs')
    logger.info("  /docs/<path>")
    
    # Runbook routes
    from src.routes.runbook_routes import create_runbook_routes
    app.register_blueprint(create_runbook_routes(config.RUNBOOKS_DIR), url_prefix='/api/runbooks')
    logger.info("  /api/runbooks")
    
    # Shutdown routes
    from src.routes.shutdown_routes import create_shutdown_routes
    app.register_blueprint(create_shutdown_routes(), url_prefix='/api/shutdown')
    logger.info("  /api/shutdown")
    
    logger.info("  /metrics")
    logger.info("Routes Registered")
    
    return app


# Define a signal handler for SIGTERM and SIGINT
def handle_exit(signum, frame):
    """Handle graceful shutdown on SIGTERM/SIGINT."""
    logger = logging.getLogger(__name__)
    logger.info(f"Received signal {signum}. Initiating shutdown...")
    logger.info("Shutdown complete.")
    sys.exit(0)

# Register the signal handler
signal.signal(signal.SIGTERM, handle_exit)
signal.signal(signal.SIGINT, handle_exit)

# Create default app instance for Gunicorn (uses RUNBOOKS_DIR from config or env)
# This allows Gunicorn to use: gunicorn src.server:app
# Note: When running as __main__, we create a fresh app to ensure environment variables are respected
app = None
if __name__ != "__main__":
    app = create_app()

# Expose app for direct execution
if __name__ == "__main__":
    from src.config.config import Config
    # Create app here to ensure environment variables (like ENABLE_LOGIN) are set
    app = create_app()
    config = Config.get_instance()
    
    api_port = config.API_PORT
    logger = logging.getLogger(__name__)
    logger.info(f"Starting Flask server on port {api_port}")
    logger.info(f"Runbooks directory: {Path(config.RUNBOOKS_DIR).resolve()}")
    
    # Start Flask development server
    # Note: use_reloader=False prevents Werkzeug from reconfiguring logging in a reloader process.
    # Logging is already configured in Config.__init__() with force=True, which handles
    # any handlers that Werkzeug might add. Werkzeug's request logs are suppressed to WARNING
    # level in configure_logging(), so only our application logs appear.
    app.run(host="0.0.0.0", port=api_port, debug=False, use_reloader=False)
