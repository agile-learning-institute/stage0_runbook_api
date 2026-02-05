"""
Dev Login routes for Flask services.

Provides a /dev-login endpoint that issues signed JWTs for local / dev environments.
This endpoint is only enabled when Config.ENABLE_LOGIN is True.
"""
from flask import Blueprint, jsonify, request
from ..config.config import Config
from ..flask_utils.route_wrapper import handle_route_exceptions
from ..flask_utils.exceptions import HTTPNotFound, HTTPForbidden
from datetime import datetime, timedelta, timezone
import jwt

import logging
logger = logging.getLogger(__name__)


def create_dev_login_routes():
    """
    Create a Flask Blueprint for dev-login endpoint.
    
    Returns:
        Blueprint: Flask Blueprint with dev-login route (always returned)
    """
    dev_login_routes = Blueprint('dev_login_routes', __name__)
    config = Config.get_instance()
    
    @dev_login_routes.route('', methods=['POST'])
    @handle_route_exceptions
    def dev_login():
        """
        POST /dev-login - Issue a signed JWT for development.
        
        Request body (JSON, all fields optional):
        {
            "subject": "dev-user-1",
            "roles": ["developer", "admin"]
        }
        """
        # Check if dev login is enabled
        config = Config.get_instance()
        if not config.ENABLE_LOGIN:
            raise HTTPNotFound("Not found")
        
        # Get request data
        data = request.get_json() or {}
        subject = data.get('subject', 'dev-user-1')
        roles = data.get('roles', ['developer'])
        
        # Build JWT claims
        now = datetime.now(timezone.utc)
        exp = now + timedelta(minutes=config.JWT_TTL_MINUTES)
        
        claims = {
            "iss": config.JWT_ISSUER,
            "aud": config.JWT_AUDIENCE,
            "sub": subject,
            "iat": int(now.timestamp()),
            "exp": int(exp.timestamp()),
            "roles": roles
        }
        
        # Generate JWT
        try:
            token = jwt.encode(
                claims,
                config.JWT_SECRET,
                algorithm=config.JWT_ALGORITHM
            )
        except Exception as e:
            logger.error(f"Error encoding JWT: {str(e)}")
            raise HTTPForbidden(f"Error generating token: {str(e)}")
        
        response = {
            "access_token": token,
            "token_type": "bearer",
            "expires_at": exp.isoformat(),
            "subject": subject,
            "roles": roles
        }
        logger.info(f"Dev login successful for subject: {subject}")
        return jsonify(response), 200
    
    logger.info("Dev Login Flask Routes Registered")
    return dev_login_routes

