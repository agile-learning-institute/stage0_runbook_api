#!/usr/bin/env python3
"""
End-to-end (E2E) tests for stage0_runbook_api.

These are true black-box tests that assume the API server is already running
on the default port (8083). They make HTTP requests to test complete workflows
from API calls through runbook execution, including authentication, authorization,
error handling, and concurrent scenarios.

Tests use SimpleRunbook.md, ParentRunbook.md, and CreatePackage.md and restore them to original state after completion.

To run these tests:
1. Start the API server: pipenv run dev
2. In another terminal: pipenv run e2e
"""
import os
import json
import time
import threading
from pathlib import Path

import pytest
import requests

# Import test utilities for runbook cleanup
from test.test_utils import save_all_test_runbooks, restore_all_test_runbooks

# Default API base URL (assumes server is running on default port)
API_BASE_URL = os.getenv('API_BASE_URL', 'http://localhost:8083')


@pytest.fixture(scope='session', autouse=True)
def setup_and_teardown():
    """Save original runbooks before tests and restore after all tests."""
    save_all_test_runbooks()
    yield
    restore_all_test_runbooks()


@pytest.fixture(scope='session')
def api_base_url():
    """Get the API base URL (defaults to http://localhost:8083)."""
    return API_BASE_URL


@pytest.fixture(scope='session')
def check_server_running(api_base_url):
    """Check if the API server is running and accessible."""
    max_attempts = 10
    for attempt in range(max_attempts):
        try:
            response = requests.get(f'{api_base_url}/metrics', timeout=2)
            if response.status_code == 200:
                return True
        except requests.exceptions.RequestException:
            pass
        
        if attempt < max_attempts - 1:
            time.sleep(0.5)
    
    pytest.skip(f"API server is not running at {api_base_url}. Please start the server first with 'pipenv run dev'")


@pytest.fixture
def dev_token(api_base_url, check_server_running):
    """Get a dev token with sre, api, data, and ux roles to match sample runbooks."""
    # Runbooks require: SimpleRunbook (sre, api), CreatePackage (sre, api), 
    # ParentRunbook (sre), Runbook (sre, data, api, ux)
    # So we need: sre, api, data, ux to cover all runbooks
    for endpoint in ['/dev-login', '/api/dev-login']:
        try:
            response = requests.post(
                f'{api_base_url}{endpoint}',
                json={'subject': 'e2e-test-user', 'roles': ['sre', 'api', 'data', 'ux']},
                headers={'Content-Type': 'application/json'},
                timeout=2
            )
            if response.status_code == 200:
                data = response.json()
                return data.get('access_token') or data.get('token')
        except requests.exceptions.RequestException:
            continue
    
    pytest.fail(f"Could not get dev token from {api_base_url}. Is ENABLE_LOGIN=true?")


@pytest.fixture
def viewer_token(api_base_url, check_server_running):
    """Get a dev token with viewer role only."""
    # Try dev-login endpoint (may be at root or /dev-login)
    for endpoint in ['/dev-login', '/api/dev-login']:
        try:
            response = requests.post(
                f'{api_base_url}{endpoint}',
                json={'subject': 'e2e-viewer-user', 'roles': ['viewer']},
                headers={'Content-Type': 'application/json'},
                timeout=2
            )
            if response.status_code == 200:
                data = response.json()
                return data.get('access_token') or data.get('token')
        except requests.exceptions.RequestException:
            continue
    
    pytest.fail(f"Could not get viewer token from {api_base_url}. Is ENABLE_LOGIN=true?")


# ============================================================================
# E2E Test: Complete Runbook Workflow
# ============================================================================

def test_e2e_complete_runbook_workflow(api_base_url, check_server_running, dev_token):
    """Test complete workflow: list -> get -> validate -> execute -> check history."""
    # Step 1: List runbooks
    response = requests.get(
        f'{api_base_url}/api/runbooks',
        headers={'Authorization': f'Bearer {dev_token}'}
    )
    assert response.status_code == 200
    data = response.json()
    assert data['success'] is True
    assert 'runbooks' in data
    assert any(rb['filename'] == 'SimpleRunbook.md' for rb in data['runbooks']), \
        "SimpleRunbook.md should be in the list"
    
    # Step 2: Get runbook content
    response = requests.get(
        f'{api_base_url}/api/runbooks/SimpleRunbook.md',
        headers={'Authorization': f'Bearer {dev_token}'}
    )
    assert response.status_code == 200
    data = response.json()
    assert data['success'] is True
    assert 'content' in data
    assert 'SimpleRunbook' in data['name']
    assert 'TEST_VAR' in data['content'], "Runbook should contain TEST_VAR requirement"
    
    # Step 3: Get required environment variables
    response = requests.get(
        f'{api_base_url}/api/runbooks/SimpleRunbook.md/required-env',
        headers={'Authorization': f'Bearer {dev_token}'}
    )
    assert response.status_code == 200
    data = response.json()
    assert data['success'] is True
    assert 'required' in data
    assert 'available' in data
    assert 'missing' in data
    assert any(env['name'] == 'TEST_VAR' for env in data['required'])
    
    # Step 4: Validate runbook (with env vars in request)
    response = requests.patch(
        f'{api_base_url}/api/runbooks/SimpleRunbook.md/validate',
        headers={'Authorization': f'Bearer {dev_token}'},
        json={'env_vars': {'TEST_VAR': 'e2e-test-value'}}
    )
    assert response.status_code in [200, 400]  # 200 if valid, 400 if invalid
    data = response.json()
    assert 'success' in data
    assert 'errors' in data
    assert 'warnings' in data
    
    # Step 5: Execute runbook
    response = requests.post(
        f'{api_base_url}/api/runbooks/SimpleRunbook.md/execute',
        headers={'Authorization': f'Bearer {dev_token}'},
        json={'env_vars': {'TEST_VAR': 'e2e-execution-test'}},
    )
    assert response.status_code in [200, 500]  # 200 if success, 500 if script fails
    data = response.json()
    assert 'success' in data
    assert 'return_code' in data
    assert 'stdout' in data
    assert 'stderr' in data
    assert 'runbook' in data
    assert data['runbook'] == 'SimpleRunbook.md'
    
    # Verify execution actually ran
    if data['success']:
        assert 'Running SimpleRunbook' in data['stdout'] or 'e2e-execution-test' in data['stdout']


def test_e2e_parent_runbook_sub_runbook_execution(api_base_url, check_server_running, dev_token):
    """Test ParentRunbook.md calling SimpleRunbook.md as a sub-runbook."""
    # Step 1: Verify ParentRunbook.md exists and can be loaded
    response = requests.get(
        f'{api_base_url}/api/runbooks/ParentRunbook.md',
        headers={'Authorization': f'Bearer {dev_token}'}
    )
    assert response.status_code == 200
    data = response.json()
    assert data['success'] is True
    assert 'ParentRunbook' in data['name']
    
    # Step 2: Validate ParentRunbook.md to ensure it's properly formatted
    response = requests.patch(
        f'{api_base_url}/api/runbooks/ParentRunbook.md/validate',
        headers={'Authorization': f'Bearer {dev_token}'},
        json={'env_vars': {'TEST_VAR': 'parent-e2e-test'}},
    )
    assert response.status_code == 200, f"Validation failed: {response.text}"
    data = response.json()
    assert data['success'] is True, f"Validation should succeed, got errors: {data.get('errors', [])}"
    assert len(data.get('errors', [])) == 0, f"Validation errors: {data.get('errors', [])}"
    
    # Step 3: Execute ParentRunbook.md (which should call SimpleRunbook.md)
    response = requests.post(
        f'{api_base_url}/api/runbooks/ParentRunbook.md/execute',
        headers={'Authorization': f'Bearer {dev_token}'},
        json={'env_vars': {'TEST_VAR': 'parent-e2e-test'}},
    )
    # Should return 200 (validation passed) even if script execution fails
    assert response.status_code == 200, f"Execution request failed: {response.text}"
    data = response.json()
    assert 'success' in data
    assert 'return_code' in data
    assert 'runbook' in data
    assert data['runbook'] == 'ParentRunbook.md'
    
    # Step 4: Verify parent runbook executed (check stdout for parent messages)
    # Note: success=False is OK if the script itself fails, but validation should pass
    assert len(data.get('errors', [])) == 0, f"Execution should not have validation errors: {data.get('errors', [])}"
    if data['success']:
        assert 'Parent runbook' in data['stdout'].lower() or 'parent' in data['stdout'].lower()
        # May also see child runbook output if sub-runbook execution worked


def test_e2e_createpackage_input_files_and_folders(api_base_url, check_server_running, dev_token):
    """Test CreatePackage.md with input files and folders."""
    # Step 1: Verify CreatePackage.md exists and can be loaded
    response = requests.get(
        f'{api_base_url}/api/runbooks/CreatePackage.md',
        headers={'Authorization': f'Bearer {dev_token}'}
    )
    assert response.status_code == 200
    data = response.json()
    assert data['success'] is True
    # Runbook name might be "CreatePackage" or "Create Package" (with space)
    assert 'CreatePackage' in data['name'] or 'Create Package' in data['name']
    
    # Step 2: Validate CreatePackage.md
    # Note: CreatePackage.md may require ORG and REPO env vars in addition to GITHUB_TOKEN
    response = requests.patch(
        f'{api_base_url}/api/runbooks/CreatePackage.md/validate',
        headers={'Authorization': f'Bearer {dev_token}'},
        json={'env_vars': {'GITHUB_TOKEN': 'test-token', 'ORG': 'test-org', 'REPO': 'test-repo'}},
    )
    assert response.status_code == 200, f"Validation failed: {response.text}"
    data = response.json()
    assert data['success'] is True, f"Validation should succeed, got errors: {data.get('errors', [])}"
    assert len(data.get('errors', [])) == 0, f"Validation errors: {data.get('errors', [])}"
    
    # Step 3: Execute CreatePackage.md (which uses input files/folders)
    response = requests.post(
        f'{api_base_url}/api/runbooks/CreatePackage.md/execute',
        headers={'Authorization': f'Bearer {dev_token}'},
        json={'env_vars': {'GITHUB_TOKEN': 'test-token', 'ORG': 'test-org', 'REPO': 'test-repo'}},
    )
    assert response.status_code == 200, f"Execution request failed: {response.text}"
    data = response.json()
    assert 'success' in data
    assert 'return_code' in data
    assert 'runbook' in data
    assert data['runbook'] == 'CreatePackage.md'
    
    # Step 4: Verify input files/folders were accessible
    assert len(data.get('errors', [])) == 0, f"Execution should not have validation errors: {data.get('errors', [])}"
    if data['success']:
        # Verify input folder contents were accessed (CreatePackage/input.txt)
        assert 'Input Folder Contents' in data['stdout'], "Script should display input folder contents"
        assert 'sample input file' in data['stdout'].lower() or 'input file access' in data['stdout'].lower(), \
            "Script should read from input folder"
        # Verify dockerfile reference (CreatePackage.dockerfile)
        assert 'docker build' in data['stdout'].lower() or 'CreatePackage.dockerfile' in data['stdout'], \
            "Script should reference dockerfile"
        assert 'Create Package Completed' in data['stdout'], "Script should complete successfully"


# ============================================================================
# E2E Test: Authentication and Authorization Flows
# ============================================================================

def test_e2e_authentication_flow(api_base_url, check_server_running):
    """Test complete authentication flow: dev-login -> use token -> verify access."""
    # Step 1: Get token via dev-login (try both possible endpoints)
    token = None
    for endpoint in ['/dev-login', '/api/dev-login']:
        try:
            response = requests.post(
                f'{api_base_url}{endpoint}',
                json={'subject': 'auth-test-user', 'roles': ['sre', 'api']},
                headers={'Content-Type': 'application/json'},
                timeout=2
            )
            if response.status_code == 200:
                data = response.json()
                token = data.get('access_token') or data.get('token')
                if token:
                    assert 'token_type' in data
                    assert data['token_type'] == 'bearer'
                    break
        except requests.exceptions.RequestException:
            continue
    
    if not token:
        pytest.skip(f"Could not get dev token from {api_base_url}. Is ENABLE_LOGIN=true?")
    
    # Step 2: Use token to access protected endpoint
    response = requests.get(
        f'{api_base_url}/api/runbooks',
        headers={'Authorization': f'Bearer {token}'}
    )
    assert response.status_code == 200
    data = response.json()
    assert data['success'] is True
    
    # Step 3: Verify token is required (unauthorized access)
    response = requests.get(f'{api_base_url}/api/runbooks')
    assert response.status_code == 401
    data = response.json()
    assert 'error' in data
    
    # Step 4: Verify invalid token is rejected
    response = requests.get(
        f'{api_base_url}/api/runbooks',
        headers={'Authorization': 'Bearer invalid-token-here'}
    )
    assert response.status_code == 401


def test_e2e_rbac_authorization_flow(api_base_url, check_server_running, dev_token, viewer_token):
    """Test RBAC authorization flow: viewer cannot execute runbook requiring specific roles."""
    # SimpleRunbook requires 'sre' and 'api' roles
    # viewer_token only has 'viewer' role (not in runbook requirements)
    
    # Step 1: Viewer can list runbooks (no RBAC required)
    response = requests.get(
        f'{api_base_url}/api/runbooks',
        headers={'Authorization': f'Bearer {viewer_token}'}
    )
    assert response.status_code == 200
    
    # Step 2: Viewer can get runbook content (no RBAC required)
    response = requests.get(
        f'{api_base_url}/api/runbooks/SimpleRunbook.md',
        headers={'Authorization': f'Bearer {viewer_token}'}
    )
    assert response.status_code == 200
    
    # Step 3: Viewer cannot validate runbook (RBAC required)
    response = requests.patch(
        f'{api_base_url}/api/runbooks/SimpleRunbook.md/validate',
        headers={'Authorization': f'Bearer {viewer_token}'},
        json={'env_vars': {'TEST_VAR': 'test'}}
    )
    assert response.status_code == 403
    data = response.json()
    assert 'error' in data
    assert 'forbidden' in data['error'].lower() or 'rbac' in data['error'].lower() or 'claim' in data['error'].lower()
    
    # Step 4: Viewer cannot execute runbook (RBAC required)
    response = requests.post(
        f'{api_base_url}/api/runbooks/SimpleRunbook.md/execute',
        headers={'Authorization': f'Bearer {viewer_token}'},
        json={'env_vars': {'TEST_VAR': 'test'}},
    )
    assert response.status_code == 403
    data = response.json()
    assert 'error' in data
    
    # Step 5: User with proper roles (sre, api) can execute
    response = requests.post(
        f'{api_base_url}/api/runbooks/SimpleRunbook.md/execute',
        headers={'Authorization': f'Bearer {dev_token}'},
        json={'env_vars': {'TEST_VAR': 'test'}},
    )
    assert response.status_code in [200, 500]  # May succeed or fail based on script


# ============================================================================
# E2E Test: Concurrent Execution Scenarios
# ============================================================================

def test_e2e_concurrent_list_requests(api_base_url, check_server_running, dev_token):
    """Test concurrent requests to list runbooks."""
    results = []
    errors = []
    
    def make_request(index):
        try:
            response = requests.get(
                f'{api_base_url}/api/runbooks',
                headers={'Authorization': f'Bearer {dev_token}'},
                timeout=10
            )
            results.append((index, response.status_code))
        except Exception as e:
            errors.append((index, str(e)))
    
    # Create 10 concurrent requests
    threads = []
    for i in range(10):
        thread = threading.Thread(target=make_request, args=(i,))
        threads.append(thread)
        thread.start()
    
    # Wait for all threads
    for thread in threads:
        thread.join(timeout=30)
    
    # Verify all requests succeeded
    assert len(errors) == 0, f"Concurrent requests failed: {errors}"
    assert len(results) == 10, f"Expected 10 results, got {len(results)}"
    assert all(status == 200 for _, status in results), \
        f"Not all requests succeeded: {results}"


def test_e2e_concurrent_executions(api_base_url, check_server_running, dev_token):
    """Test concurrent runbook executions."""
    results = []
    errors = []
    
    def execute_runbook(index):
        try:
            response = requests.post(
                f'{api_base_url}/api/runbooks/SimpleRunbook.md/execute',
                headers={'Authorization': f'Bearer {dev_token}'},
                json={'env_vars': {'TEST_VAR': f'concurrent-test-{index}'}},
                timeout=120
            )
            results.append((index, response.status_code))
        except Exception as e:
            errors.append((index, str(e)))
    
    # Create 5 concurrent executions
    threads = []
    for i in range(5):
        thread = threading.Thread(target=execute_runbook, args=(i,))
        threads.append(thread)
        thread.start()
    
    # Wait for all threads
    for thread in threads:
        thread.join(timeout=120)  # 2 minute timeout
    
    # All requests should complete
    assert len(errors) == 0, f"Concurrent executions failed: {errors}"
    assert len(results) == 5, f"Expected 5 results, got {len(results)}"
    
    # Streaming always returns 200 (success/failure is in the done event)
    status_codes = [status for _, status in results]
    assert all(status == 200 for status in status_codes), \
        f"Unexpected status codes: {status_codes}"


# ============================================================================
# E2E Test: Error Response Formats
# ============================================================================

def test_e2e_error_response_format_401(api_base_url, check_server_running):
    """Test that 401 errors return proper format."""
    response = requests.get(f'{api_base_url}/api/runbooks')
    assert response.status_code == 401
    data = response.json()
    assert 'error' in data
    assert isinstance(data['error'], str)
    assert len(data['error']) > 0


def test_e2e_error_response_format_404(api_base_url, check_server_running, dev_token):
    """Test that 404 errors return proper format."""
    response = requests.get(
        f'{api_base_url}/api/runbooks/NonExistentRunbook.md',
        headers={'Authorization': f'Bearer {dev_token}'}
    )
    assert response.status_code == 404
    data = response.json()
    assert 'error' in data
    assert isinstance(data['error'], str)
    assert 'not found' in data['error'].lower() or 'NonExistent' in data['error']


def test_e2e_error_response_format_403(api_base_url, check_server_running, viewer_token):
    """Test that 403 errors return proper format."""
    response = requests.post(
        f'{api_base_url}/api/runbooks/SimpleRunbook.md/execute',
        headers={'Authorization': f'Bearer {viewer_token}'},
        json={'env_vars': {'TEST_VAR': 'test'}},
    )
    assert response.status_code == 403
    data = response.json()
    assert 'error' in data
    assert isinstance(data['error'], str)


def test_e2e_error_response_format_400(api_base_url, check_server_running, dev_token):
    """Test that 400 errors return proper format (missing env var)."""
    # Try to validate without required env var (empty env_vars)
    response = requests.patch(
        f'{api_base_url}/api/runbooks/SimpleRunbook.md/validate',
        headers={'Authorization': f'Bearer {dev_token}'},
        json={'env_vars': {}}  # Send empty env_vars
    )
    # May return 200 with errors, or 400
    assert response.status_code in [200, 400]
    data = response.json()
    assert 'errors' in data or 'error' in data


# ============================================================================
# E2E Test: API Endpoints End-to-End
# ============================================================================

def test_e2e_all_endpoints_accessible(api_base_url, check_server_running, dev_token):
    """Test that all API endpoints are accessible and return expected formats."""
    # GET /api/runbooks
    response = requests.get(
        f'{api_base_url}/api/runbooks',
        headers={'Authorization': f'Bearer {dev_token}'}
    )
    assert response.status_code == 200
    data = response.json()
    assert 'success' in data
    assert 'runbooks' in data
    
    # GET /api/runbooks/<filename>
    response = requests.get(
        f'{api_base_url}/api/runbooks/SimpleRunbook.md',
        headers={'Authorization': f'Bearer {dev_token}'}
    )
    assert response.status_code == 200
    data = response.json()
    assert 'success' in data
    assert 'content' in data
    
    # GET /api/runbooks/<filename>/required-env
    response = requests.get(
        f'{api_base_url}/api/runbooks/SimpleRunbook.md/required-env',
        headers={'Authorization': f'Bearer {dev_token}'}
    )
    assert response.status_code == 200
    data = response.json()
    assert 'success' in data
    assert 'required' in data
    
    # GET /api/config
    response = requests.get(
        f'{api_base_url}/api/config',
        headers={'Authorization': f'Bearer {dev_token}'}
    )
    assert response.status_code == 200
    data = response.json()
    assert 'config_items' in data
    assert 'token' in data
    
    # GET /metrics (public endpoint)
    response = requests.get(f'{api_base_url}/metrics')
    assert response.status_code == 200
    
    # GET /docs/openapi.yaml (public endpoint)
    response = requests.get(f'{api_base_url}/docs/openapi.yaml')
    assert response.status_code == 200
    assert 'openapi' in response.text.lower()


# Run tests
if __name__ == '__main__':
    pytest.main([__file__, '-v'])
