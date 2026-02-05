#!/usr/bin/env python3
"""
Tests for dev_login_routes module.
"""
import os
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from flask import Flask
from src.routes.dev_login_routes import create_dev_login_routes
from src.config.config import Config
from src.flask_utils.exceptions import HTTPNotFound, HTTPForbidden


@pytest.fixture
def flask_app():
    """Create Flask app for testing."""
    # Reset Config singleton
    Config._instance = None
    
    # Enable dev login
    os.environ['ENABLE_LOGIN'] = 'true'
    os.environ['JWT_SECRET'] = 'test-secret-for-unit-tests'
    
    app = Flask(__name__)
    app.config['TESTING'] = True
    
    # Register dev login routes
    dev_login_bp = create_dev_login_routes()
    app.register_blueprint(dev_login_bp, url_prefix='/dev-login')
    
    return app


@pytest.fixture
def flask_app_login_disabled():
    """Create Flask app with dev login disabled."""
    # Reset Config singleton
    Config._instance = None
    
    # Disable dev login
    os.environ['ENABLE_LOGIN'] = 'false'
    os.environ['JWT_SECRET'] = 'test-secret-for-unit-tests'
    
    app = Flask(__name__)
    app.config['TESTING'] = True
    
    # Register dev login routes
    dev_login_bp = create_dev_login_routes()
    app.register_blueprint(dev_login_bp, url_prefix='/dev-login')
    
    return app


def test_dev_login_disabled_returns_404(flask_app_login_disabled):
    """Test that dev-login returns 404 when ENABLE_LOGIN is False."""
    client = flask_app_login_disabled.test_client()
    
    response = client.post('/dev-login', json={'subject': 'test-user'})
    
    assert response.status_code == 404


def test_dev_login_jwt_encoding_error(flask_app):
    """Test that dev-login handles JWT encoding errors."""
    with patch('src.routes.dev_login_routes.jwt.encode') as mock_encode:
        mock_encode.side_effect = Exception("JWT encoding failed")
        
        client = flask_app.test_client()
        response = client.post('/dev-login', json={'subject': 'test-user'})
        
        assert response.status_code == 403
        data = response.get_json()
        assert 'error' in data
        assert 'Error generating token' in data['error']


