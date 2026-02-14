#!/usr/bin/env python3
"""
Integration tests for stage0_runbook_api Flask endpoints.

Tests all API endpoints end-to-end with authentication flows,
error handling, and concurrent execution scenarios.

Tests use SimpleRunbook.md and ParentRunbook.md and restore them to original state after completion.
"""
import os
import sys
import json
import time
import threading
from pathlib import Path
from unittest.mock import patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'src'))

import pytest
from flask import Flask
from src.server import create_app
from src.config.config import Config
from src.flask_utils.token import Token

# Import test utilities for runbook cleanup
from test.test_utils import save_all_test_runbooks, restore_all_test_runbooks


@pytest.fixture(scope='session', autouse=True)
def setup_and_teardown():
    """Save original runbooks before tests and restore after all tests."""
    save_all_test_runbooks()
    yield
    restore_all_test_runbooks()


# Test fixtures
@pytest.fixture
def flask_app():
    """Create Flask app for testing."""
    # Reset Config singleton to pick up new environment variables
    from src.config.config import Config
    Config._instance = None
    
    # Set test environment
    os.environ['ENABLE_LOGIN'] = 'true'
    os.environ['RUNBOOKS_DIR'] = str(Path(__file__).parent.parent.parent / 'samples' / 'runbooks')
    os.environ['SCRIPT_TIMEOUT_SECONDS'] = '60'
    os.environ['JWT_SECRET'] = 'test-secret-for-integration-tests'
    os.environ['MAX_OUTPUT_SIZE_BYTES'] = '10485760'
    
    app = create_app()
    app.config['TESTING'] = True
    return app


@pytest.fixture
def client(flask_app):
    """Create Flask test client."""
    return flask_app.test_client()


@pytest.fixture
def dev_token(client):
    """Get a dev token for testing with sre and api roles to match sample runbooks."""
    response = client.post(
        '/dev-login',
        json={'subject': 'test-user', 'roles': ['sre', 'api']},
        content_type='application/json'
    )
    assert response.status_code == 200
    data = json.loads(response.data)
    return data['access_token']


@pytest.fixture
def viewer_token(client):
    """Get a token with viewer role only."""
    response = client.post(
        '/dev-login',
        json={'subject': 'viewer-user', 'roles': ['viewer']},
        content_type='application/json'
    )
    assert response.status_code == 200
    data = json.loads(response.data)
    return data['access_token']


# ============================================================================
# Integration Tests: All API Endpoints End-to-End
# ============================================================================

def test_list_runbooks_endpoint(client, dev_token):
    """Test GET /api/runbooks endpoint end-to-end."""
    response = client.get(
        '/api/runbooks',
        headers={'Authorization': f'Bearer {dev_token}'}
    )
    
    assert response.status_code == 200
    data = json.loads(response.data)
    assert 'success' in data
    assert data['success'] is True
    assert 'runbooks' in data
    assert isinstance(data['runbooks'], list)
    
    # Verify runbook structure
    if len(data['runbooks']) > 0:
        runbook = data['runbooks'][0]
        assert 'filename' in runbook
        assert 'name' in runbook
        assert 'path' in runbook


def test_get_runbook_endpoint(client, dev_token):
    """Test GET /api/runbooks/<filename> endpoint end-to-end."""
    response = client.get(
        '/api/runbooks/SimpleRunbook.md',
        headers={'Authorization': f'Bearer {dev_token}'}
    )
    
    assert response.status_code == 200
    data = json.loads(response.data)
    assert 'success' in data
    assert data['success'] is True
    assert 'filename' in data
    assert 'name' in data
    assert 'content' in data
    assert 'SimpleRunbook' in data['name']


def test_get_runbook_not_found(client, dev_token):
    """Test GET /api/runbooks/<filename> with non-existent runbook."""
    response = client.get(
        '/api/runbooks/NonExistentRunbook.md',
        headers={'Authorization': f'Bearer {dev_token}'}
    )
    
    assert response.status_code == 404
    data = json.loads(response.data)
    assert 'error' in data
    assert 'not found' in data['error'].lower() or 'NonExistent' in data['error']


def test_get_required_env_endpoint(client, dev_token):
    """Test GET /api/runbooks/<filename>/required-env endpoint."""
    os.environ['TEST_VAR'] = 'test_value'
    
    try:
        response = client.get(
            '/api/runbooks/SimpleRunbook.md/required-env',
            headers={'Authorization': f'Bearer {dev_token}'}
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'success' in data
        assert data['success'] is True
        assert 'filename' in data
        assert 'required' in data
        assert 'available' in data
        assert 'missing' in data
        assert isinstance(data['required'], list)
    finally:
        if 'TEST_VAR' in os.environ:
            del os.environ['TEST_VAR']


def test_validate_runbook_endpoint(client, dev_token):
    """Test PATCH /api/runbooks/<filename>/validate endpoint."""
    os.environ['TEST_VAR'] = 'test_value'
    
    try:
        response = client.patch(
            '/api/runbooks/SimpleRunbook.md/validate',
            headers={'Authorization': f'Bearer {dev_token}'},
            json={}  # Send empty JSON body
        )
        
        assert response.status_code in [200, 400]  # 200 if valid, 400 if invalid
        data = json.loads(response.data)
        assert 'success' in data
        assert 'runbook' in data
        assert 'errors' in data
        assert 'warnings' in data
    finally:
        if 'TEST_VAR' in os.environ:
            del os.environ['TEST_VAR']


def _parse_sse_done(response_data: bytes) -> dict:
    """Parse SSE response and return the last 'done' event's data as dict."""
    text = response_data.decode('utf-8')
    events = [e.strip() for e in text.strip().split('\n\n') if e.strip()]
    for event in reversed(events):
        if event.startswith('event: done'):
            lines = event.split('\n')
            data_lines = [ln[6:] for ln in lines if ln.startswith('data: ')]
            if data_lines:
                return json.loads('\n'.join(data_lines))
    return {}


def test_execute_runbook_endpoint(client, dev_token):
    """Test POST /api/runbooks/<filename>/execute endpoint (streaming SSE)."""
    os.environ['TEST_VAR'] = 'test_value'
    
    try:
        response = client.post(
            '/api/runbooks/SimpleRunbook.md/execute',
            headers={'Authorization': f'Bearer {dev_token}'},
            json={'env_vars': {'TEST_VAR': 'test_value'}},
            content_type='application/json'
        )
        
        assert response.status_code == 200
        assert 'text/event-stream' in (response.content_type or '')
        data = _parse_sse_done(response.data)
        assert 'success' in data
        assert 'runbook' in data
        assert 'return_code' in data
        assert 'stdout' in data
        assert 'stderr' in data
    finally:
        if 'TEST_VAR' in os.environ:
            del os.environ['TEST_VAR']


def test_execute_runbook_with_env_vars(client, dev_token):
    """Test POST /api/runbooks/<filename>/execute with environment variables."""
    response = client.post(
        '/api/runbooks/SimpleRunbook.md/execute',
        headers={'Authorization': f'Bearer {dev_token}'},
        json={'env_vars': {'TEST_VAR': 'custom_test_value'}},
        content_type='application/json'
    )
    
    assert response.status_code == 200
    data = _parse_sse_done(response.data)
    assert 'success' in data


def test_get_config_endpoint(client, dev_token):
    """Test GET /api/config endpoint."""
    response = client.get(
        '/api/config',
        headers={'Authorization': f'Bearer {dev_token}'}
    )
    
    assert response.status_code == 200
    data = json.loads(response.data)
    assert 'config_items' in data
    assert 'token' in data
    assert isinstance(data['config_items'], list)


# ============================================================================
# Authentication/Authorization Flow Tests
# ============================================================================

def test_unauthenticated_request_returns_401(client):
    """Test that requests without token return 401."""
    response = client.get('/api/runbooks')
    assert response.status_code == 401
    data = json.loads(response.data)
    assert 'error' in data
    assert 'authorization' in data['error'].lower() or 'token' in data['error'].lower()


def test_invalid_token_returns_401(client):
    """Test that requests with invalid token return 401."""
    response = client.get(
        '/api/runbooks',
        headers={'Authorization': 'Bearer invalid_token_here'}
    )
    assert response.status_code == 401
    data = json.loads(response.data)
    assert 'error' in data


def test_dev_login_endpoint(client):
    """Test POST /dev-login endpoint for token generation."""
    response = client.post(
        '/dev-login',
        json={'subject': 'test-user-2', 'roles': ['developer']},
        content_type='application/json'
    )
    
    assert response.status_code == 200
    data = json.loads(response.data)
    assert 'access_token' in data
    assert 'token_type' in data
    assert 'expires_at' in data
    assert data['token_type'] == 'bearer'
    
    # Verify token can be used
    token = data['access_token']
    response2 = client.get(
        '/api/runbooks',
        headers={'Authorization': f'Bearer {token}'}
    )
    assert response2.status_code == 200


def test_dev_login_with_custom_claims(client):
    """Test dev-login with custom roles."""
    response = client.post(
        '/dev-login',
        json={
            'subject': 'custom-user',
            'roles': ['admin', 'devops', 'engineer']
        },
        content_type='application/json'
    )
    
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['roles'] == ['admin', 'devops', 'engineer']
    
    # Verify token works
    token = data['access_token']
    response2 = client.get(
        '/api/config',
        headers={'Authorization': f'Bearer {token}'}
    )
    assert response2.status_code == 200


def test_rbac_enforcement_on_execute(client, viewer_token):
    """Test that RBAC is enforced on execute endpoint."""
    # Create a runbook that requires admin role
    runbook_content = """# TestRunbook
# Environment Requirements
```yaml
```
# File System Requirements
```yaml
Input:
```
# Required Claims
```yaml
roles: admin
```
# Script
```sh
#! /bin/zsh
echo "test"
```
# History
"""
    
    runbook_path = Path(__file__).parent.parent.parent / 'samples' / 'runbooks' / 'test_rbac_enforcement.md'
    with open(runbook_path, 'w') as f:
        f.write(runbook_content)
    
    try:
        response = client.post(
            '/api/runbooks/test_rbac_enforcement.md/execute',
            headers={'Authorization': f'Bearer {viewer_token}'},
            json={'env_vars': {}},
            content_type='application/json'
        )
        
        # Should return 403 Forbidden
        assert response.status_code == 403
        data = json.loads(response.data)
        assert 'error' in data
        assert 'forbidden' in data['error'].lower() or 'rbac' in data['error'].lower() or 'claim' in data['error'].lower()
    finally:
        if runbook_path.exists():
            runbook_path.unlink()


def test_rbac_enforcement_on_validate(client, viewer_token):
    """Test that RBAC is enforced on validate endpoint."""
    # Create a runbook that requires admin role
    runbook_content = """# TestRunbook
# Environment Requirements
```yaml
```
# File System Requirements
```yaml
Input:
```
# Required Claims
```yaml
roles: admin
```
# Script
```sh
#! /bin/zsh
echo "test"
```
# History
"""
    
    runbook_path = Path(__file__).parent.parent.parent / 'samples' / 'runbooks' / 'test_rbac_validate.md'
    with open(runbook_path, 'w') as f:
        f.write(runbook_content)
    
    try:
        response = client.patch(
            '/api/runbooks/test_rbac_validate.md/validate',
            headers={'Authorization': f'Bearer {viewer_token}'},
            json={}  # Send empty JSON body
        )
        
        # Should return 403 Forbidden
        assert response.status_code == 403
        data = json.loads(response.data)
        assert 'error' in data
    finally:
        if runbook_path.exists():
            runbook_path.unlink()


# ============================================================================
# Concurrent Execution Tests
# ============================================================================

def test_concurrent_list_runbooks(client, dev_token):
    """Test concurrent requests to list runbooks."""
    results = []
    errors = []
    
    def make_request():
        try:
            response = client.get(
                '/api/runbooks',
                headers={'Authorization': f'Bearer {dev_token}'}
            )
            results.append(response.status_code)
        except Exception as e:
            errors.append(str(e))
    
    # Create 10 concurrent requests
    threads = []
    for _ in range(10):
        thread = threading.Thread(target=make_request)
        threads.append(thread)
        thread.start()
    
    # Wait for all threads to complete
    for thread in threads:
        thread.join()
    
    # All requests should succeed
    assert len(errors) == 0, f"Concurrent requests failed with errors: {errors}"
    assert len(results) == 10, f"Expected 10 results, got {len(results)}"
    assert all(status == 200 for status in results), f"Not all requests succeeded: {results}"


def test_concurrent_execute_runbooks(client, dev_token):
    """Test concurrent execution of runbooks."""
    os.environ['TEST_VAR'] = 'test_value'
    
    results = []
    errors = []
    
    def execute_runbook(index):
        try:
            response = client.post(
                '/api/runbooks/SimpleRunbook.md/execute',
                headers={'Authorization': f'Bearer {dev_token}'},
                json={'env_vars': {'TEST_VAR': f'test_value_{index}'}},
                content_type='application/json'
            )
            results.append((index, response.status_code))
        except Exception as e:
            errors.append((index, str(e)))
    
    try:
        # Create 5 concurrent executions
        threads = []
        for i in range(5):
            thread = threading.Thread(target=execute_runbook, args=(i,))
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join(timeout=120)  # 2 minute timeout per thread
        
        # All requests should complete (may succeed or fail based on script)
        assert len(errors) == 0, f"Concurrent executions failed with errors: {errors}"
        assert len(results) == 5, f"Expected 5 results, got {len(results)}"
        
        # Streaming always returns 200 (success/failure is in the done event)
        status_codes = [status for _, status in results]
        assert all(status == 200 for status in status_codes), \
            f"Unexpected status codes: {status_codes}"
    finally:
        if 'TEST_VAR' in os.environ:
            del os.environ['TEST_VAR']


# ============================================================================
# Error Response Format Tests
# ============================================================================

def test_error_response_format_401(client):
    """Test that 401 errors return proper format."""
    response = client.get('/api/runbooks')
    assert response.status_code == 401
    
    data = json.loads(response.data)
    assert 'error' in data
    assert isinstance(data['error'], str)
    assert len(data['error']) > 0


def test_error_response_format_403(client, viewer_token):
    """Test that 403 errors return proper format."""
    # Use a runbook that requires admin (viewer doesn't have)
    runbook_content = """# TestRunbook
# Environment Requirements
```yaml
```
# File System Requirements
```yaml
Input:
```
# Required Claims
```yaml
roles: admin
```
# Script
```sh
#! /bin/zsh
echo "test"
```
# History
"""
    
    runbook_path = Path(__file__).parent.parent.parent / 'samples' / 'runbooks' / 'test_error_format.md'
    with open(runbook_path, 'w') as f:
        f.write(runbook_content)
    
    try:
        response = client.post(
            '/api/runbooks/test_error_format.md/execute',
            headers={'Authorization': f'Bearer {viewer_token}'},
            json={'env_vars': {}},
            content_type='application/json'
        )
        
        assert response.status_code == 403
        data = json.loads(response.data)
        assert 'error' in data
        assert isinstance(data['error'], str)
    finally:
        if runbook_path.exists():
            runbook_path.unlink()


def test_error_response_format_404(client, dev_token):
    """Test that 404 errors return proper format."""
    response = client.get(
        '/api/runbooks/NonExistentRunbook.md',
        headers={'Authorization': f'Bearer {dev_token}'}
    )
    
    assert response.status_code == 404
    data = json.loads(response.data)
    assert 'error' in data
    assert isinstance(data['error'], str)
    assert 'not found' in data['error'].lower() or 'NonExistent' in data['error']


def test_error_response_format_500(client, dev_token):
    """Test that 500 errors return proper format (when script fails)."""
    # Create a runbook that will fail
    runbook_content = """# TestRunbook
# Environment Requirements
```yaml
```
# File System Requirements
```yaml
Input:
```
# Script
```sh
#! /bin/zsh
exit 1
```
# History
"""
    
    runbook_path = Path(__file__).parent.parent.parent / 'samples' / 'runbooks' / 'test_500_error.md'
    with open(runbook_path, 'w') as f:
        f.write(runbook_content)
    
    try:
        response = client.post(
            '/api/runbooks/test_500_error.md/execute',
            headers={'Authorization': f'Bearer {dev_token}'},
            json={'env_vars': {}},
            content_type='application/json'
        )
        
        # Streaming always returns 200; script failure is in the done event
        assert response.status_code == 200
        data = _parse_sse_done(response.data)
        assert 'success' in data
        assert data['success'] is False
    finally:
        if runbook_path.exists():
            runbook_path.unlink()


def test_metrics_endpoint_public(client):
    """Test that /metrics endpoint is publicly accessible."""
    response = client.get('/metrics')
    assert response.status_code == 200
    # Prometheus metrics should be in the response
    assert 'flask' in response.data.decode('utf-8').lower() or \
           'http' in response.data.decode('utf-8').lower()


def test_docs_endpoint_public(client):
    """Test that /docs endpoint is publicly accessible."""
    response = client.get('/docs/openapi.yaml')
    assert response.status_code == 200
    assert 'openapi' in response.data.decode('utf-8').lower()


def test_shutdown_endpoint(client, dev_token):
    """Test POST /api/shutdown endpoint."""
    # Note: In test environment, shutdown may raise SystemExit
    # but we can verify the endpoint exists and requires auth
    try:
        response = client.post(
            '/api/shutdown',
            headers={'Authorization': f'Bearer {dev_token}'},
            json={}
        )
        
        # Should return 200 (shutdown initiated) or handle gracefully
        assert response.status_code in [200, 500]  # 500 if shutdown not available in test
        if response.status_code == 200:
            data = json.loads(response.data)
            assert 'message' in data
            assert 'shutdown' in data['message'].lower()
    except SystemExit:
        # SystemExit is expected when shutdown signal is sent
        pass


def test_shutdown_endpoint_requires_auth(client):
    """Test that shutdown endpoint requires authentication."""
    response = client.post(
        '/api/shutdown',
        content_type='application/json'
    )
    
    assert response.status_code == 401
    data = json.loads(response.data)
    assert 'error' in data


# Run tests
if __name__ == '__main__':
    pytest.main([__file__, '-v'])

