"""
Runbook routes for Flask API.

Provides endpoints for Runbook domain:
- GET /api/runbooks - List all runbooks
- GET /api/runbooks/<filename> - Get a specific runbook
- GET /api/runbooks/<filename>/required-env - Get required environment variables
- POST /api/runbooks/<filename>/execute - Execute a runbook
- PATCH /api/runbooks/<filename>/validate - Validate a runbook
"""
from flask import Blueprint, Response, jsonify, request, stream_with_context

from ..flask_utils.exceptions import HTTPForbidden, HTTPNotFound, HTTPInternalServerError
from ..flask_utils.token import create_flask_token
from ..flask_utils.breadcrumb import create_flask_breadcrumb
from ..flask_utils.route_wrapper import handle_route_exceptions
from ..services.runbook_service import RunbookService
from ..config.config import Config

import logging
logger = logging.getLogger(__name__)


def _extract_env_vars_from_request() -> dict:
    """
    Extract environment variables from request body.
    Returns empty dict if no request body or env_vars not present.
    """
    if request.is_json and request.json:
        return request.json.get('env_vars', {})
    return {}


def create_runbook_routes(runbooks_dir: str):
    """
    Create a Flask Blueprint exposing runbook endpoints.
    
    Args:
        runbooks_dir: Path to directory containing runbooks
    
    Returns:
        Blueprint: Flask Blueprint with runbook routes
    """
    runbook_routes = Blueprint('runbook_routes', __name__)
    runbook_service = RunbookService(runbooks_dir)
    
    @runbook_routes.route('', methods=['GET'])
    @handle_route_exceptions
    def list_runbooks():
        """
        GET /api/runbooks - List all available runbooks.
        
        Returns:
            JSON response with list of runbooks
        """
        token = create_flask_token()
        breadcrumb = create_flask_breadcrumb(token)
        
        result = runbook_service.list_runbooks(token, breadcrumb)
        logger.info(f"list_runbooks Success {str(breadcrumb['at_time'])}, {breadcrumb['correlation_id']}")
        return jsonify(result), 200
    
    @runbook_routes.route('/<filename>', methods=['GET'])
    @handle_route_exceptions
    def get_runbook(filename: str):
        """
        GET /api/runbooks/<filename> - Get runbook content.
        
        Args:
            filename: The runbook filename
            
        Returns:
            JSON response with runbook content and metadata
        """
        token = create_flask_token()
        breadcrumb = create_flask_breadcrumb(token)
        
        result = runbook_service.get_runbook(filename, token, breadcrumb)
        logger.info(f"get_runbook Success {str(breadcrumb['at_time'])}, {breadcrumb['correlation_id']}")
        return jsonify(result), 200
    
    @runbook_routes.route('/<filename>/required-env', methods=['GET'])
    @handle_route_exceptions
    def get_required_env(filename: str):
        """
        GET /api/runbooks/<filename>/required-env - Get required environment variables.
        
        Args:
            filename: The runbook filename
            
        Returns:
            JSON response with required, available, and missing environment variables
        """
        token = create_flask_token()
        breadcrumb = create_flask_breadcrumb(token)
        
        result = runbook_service.get_required_env(filename, token, breadcrumb)
        logger.info(f"get_required_env Success {str(breadcrumb['at_time'])}, {breadcrumb['correlation_id']}")
        return jsonify(result), 200
    
    @runbook_routes.route('/<filename>/validate', methods=['PATCH'])
    @handle_route_exceptions
    def validate_runbook(filename: str):
        """
        PATCH /api/runbooks/<filename>/validate - Validate a runbook.
        
        Args:
            filename: The runbook filename
            
        Request body (optional):
            {
                "env_vars": {
                    "VAR_NAME": "value"
                }
            }
            
        Returns:
            JSON response with validation result
        """
        token = create_flask_token()
        breadcrumb = create_flask_breadcrumb(token)
        env_vars = _extract_env_vars_from_request()
        
        result = runbook_service.validate_runbook(filename, token, breadcrumb, env_vars)
        logger.info(f"validate_runbook Success {str(breadcrumb['at_time'])}, {breadcrumb['correlation_id']}")
        
        status_code = 200 if result['success'] else 400
        return jsonify(result), status_code
    
    @runbook_routes.route('/<filename>/execute', methods=['POST'])
    @handle_route_exceptions
    def execute_runbook(filename: str):
        """
        POST /api/runbooks/<filename>/execute - Execute a runbook.
        
        Streams stdout/stderr as Server-Sent Events. Final event is "done" with
        full execution result (success, return_code, stdout, stderr, errors, warnings).
        
        Request body (optional):
            {
                "env_vars": {
                    "VAR_NAME": "value"
                }
            }
            
        Returns:
            text/event-stream with events: stdout, stderr, done
        """
        token = create_flask_token()
        breadcrumb = create_flask_breadcrumb(token)
        env_vars = _extract_env_vars_from_request()
        
        auth_header = request.headers.get('Authorization', '')
        token_string = auth_header[7:].strip() if auth_header.startswith('Bearer ') else None
        
        stream = runbook_service.execute_runbook_streaming(
            filename, token, breadcrumb, env_vars, token_string=token_string
        )
        try:
            first_chunk = next(stream)
        except HTTPNotFound as e:
            return jsonify({"success": False, "error": str(e)}), 404
        except HTTPForbidden as e:
            return jsonify({"success": False, "error": str(e)}), 403
        except HTTPInternalServerError as e:
            return jsonify({"success": False, "error": str(e)}), 500
        
        def generate():
            yield first_chunk
            for chunk in stream:
                yield chunk
        
        logger.info(f"execute_runbook streaming {str(breadcrumb['at_time'])}, {breadcrumb['correlation_id']}")
        return Response(
            stream_with_context(generate()),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no',
            },
        )
    
    logger.info("Runbook Flask Routes Registered")
    return runbook_routes

