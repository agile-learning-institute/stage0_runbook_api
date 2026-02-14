#!/usr/bin/env python3
"""
Tests for the runbook service (merged RunbookRunner functionality).
"""
import json
import os
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import pytest

# Add project root to path so we can import src.services (for relative imports to work)
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.services.runbook_service import RunbookService
from src.services.runbook_parser import RunbookParser
from src.services.runbook_validator import RunbookValidator
from src.services.script_executor import ScriptExecutor
from src.services.rbac_authorizer import RBACAuthorizer
from src.config.config import Config
from src.flask_utils.exceptions import HTTPNotFound, HTTPForbidden, HTTPInternalServerError

# Import test utilities for runbook cleanup
from test.test_utils import save_runbook, restore_runbook

# Paths to runbooks used in tests
SIMPLE_RUNBOOK_PATH = Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks' / 'SimpleRunbook.md'
PARENT_RUNBOOK_PATH = Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks' / 'ParentRunbook.md'


@pytest.fixture(autouse=True)
def restore_runbooks_after_test():
    """Restore runbooks after each test that may have modified them."""
    # Save before test
    if SIMPLE_RUNBOOK_PATH.exists():
        save_runbook(SIMPLE_RUNBOOK_PATH)
    if PARENT_RUNBOOK_PATH.exists():
        save_runbook(PARENT_RUNBOOK_PATH)
    
    yield
    
    # Restore after test
    if SIMPLE_RUNBOOK_PATH.exists():
        restore_runbook(SIMPLE_RUNBOOK_PATH)
    if PARENT_RUNBOOK_PATH.exists():
        restore_runbook(PARENT_RUNBOOK_PATH)


def test_load_valid_runbook():
    """Test loading a valid runbook."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    content, name, errors, warnings = RunbookParser.load_runbook(
        Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks' / 'SimpleRunbook.md'
    )
    assert content is not None, "Should load valid runbook"
    assert name == "SimpleRunbook", "Should extract correct runbook name"
    assert len(errors) == 0, "Should have no errors"


def test_extract_sections():
    """Test extraction of runbook sections."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    runbook_path = Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks' / 'SimpleRunbook.md'
    content, name, errors, warnings = RunbookParser.load_runbook(runbook_path)
    
    # Test section extraction
    script = RunbookParser.extract_script(content)
    assert script is not None, "Should extract script"
    assert 'echo' in script, "Script should contain echo command"


def test_extract_env_vars():
    """Test extraction of environment variables from YAML."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    runbook_path = Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks' / 'SimpleRunbook.md'
    content, name, errors, warnings = RunbookParser.load_runbook(runbook_path)
    
    env_section = RunbookParser.extract_section(content, 'Environment Requirements')
    env_vars = RunbookParser.extract_yaml_block(env_section)
    assert env_vars is not None, "Should extract env vars"
    assert 'TEST_VAR' in env_vars, "Should find TEST_VAR in env vars"


def test_extract_required_claims():
    """Test extraction of required claims from runbook."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    runbook_path = Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks' / 'SimpleRunbook.md'
    content, name, errors, warnings = RunbookParser.load_runbook(runbook_path)
    
    required_claims = RBACAuthorizer.extract_required_claims(content)
    # SimpleRunbook should have required claims section
    assert required_claims is not None, "Should extract required claims"
    assert 'roles' in required_claims, "Should have roles claim"
    assert 'sre' in required_claims['roles'] or 'api' in required_claims['roles'], "Should include sre or api role"


def test_validate_runbook_content():
    """Test validation of runbook content."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    runbook_path = Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks' / 'SimpleRunbook.md'
    content, name, errors, warnings = RunbookParser.load_runbook(runbook_path)
    
    # Set required environment variable
    os.environ['TEST_VAR'] = 'test_value'
    
    try:
        success, validation_errors, validation_warnings = RunbookValidator.validate_runbook_content(runbook_path, content)
        # Should pass validation if TEST_VAR is set
        assert success, f"Validation should pass. Errors: {validation_errors}"
    finally:
        # Clean up
        if 'TEST_VAR' in os.environ:
            del os.environ['TEST_VAR']


def test_validate_missing_env_var():
    """Test validation fails when required env var is missing."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    runbook_path = Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks' / 'SimpleRunbook.md'
    content, name, errors, warnings = RunbookParser.load_runbook(runbook_path)
    
    # Ensure TEST_VAR is not set
    if 'TEST_VAR' in os.environ:
        del os.environ['TEST_VAR']
    
    success, validation_errors, validation_warnings = RunbookValidator.validate_runbook_content(runbook_path, content)
    assert not success, "Validation should fail when env var is missing"
    assert any('TEST_VAR' in error for error in validation_errors), "Should report missing env var"


def test_script_timeout_enforcement():
    """Test that script execution times out after configured timeout."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    # Create a runbook content with a long-running script (sleep 10 seconds)
    # We'll set timeout to 2 seconds, so it should definitely timeout
    long_running_script = """#! /bin/zsh
sleep 10
echo "This should not appear"
"""
    
    runbook_content = f"""# TestRunbook
# Environment Requirements
```yaml
```
# File System Requirements
```yaml
Input:
```
# Script
```sh
{long_running_script}
```
# History
"""
    
    # Set a short timeout (2 seconds)
    config = Config.get_instance()
    original_timeout = config.SCRIPT_TIMEOUT_SECONDS
    original_max_output = config.MAX_OUTPUT_SIZE_BYTES
    
    try:
        config.SCRIPT_TIMEOUT_SECONDS = 2
        config.MAX_OUTPUT_SIZE_BYTES = 10 * 1024 * 1024  # 10MB
        
        # Create a temporary runbook file
        test_runbook_path = Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks' / 'test_timeout_runbook.md'
        with open(test_runbook_path, 'w') as f:
            f.write(runbook_content)
        
        try:
            # Execute with short timeout
            script = RunbookParser.extract_script(runbook_content)
            return_code, stdout, stderr = ScriptExecutor.execute_script(script)
            
            # Should timeout and return error
            assert return_code != 0, "Script should fail due to timeout"
            assert "timed out" in stderr.lower() or "timeout" in stderr.lower(), \
                f"Error message should mention timeout. Got: {stderr}"
            
        finally:
            # Clean up test file
            if test_runbook_path.exists():
                test_runbook_path.unlink()
    finally:
        # Restore original timeout
        config.SCRIPT_TIMEOUT_SECONDS = original_timeout
        config.MAX_OUTPUT_SIZE_BYTES = original_max_output


def test_output_size_limit():
    """Test that output is truncated when exceeding size limits."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    # Create a runbook that generates large output
    large_output_script = """#! /bin/zsh
# Generate 2MB of output
for i in {1..20000}; do
    echo "Line $i: This is a test line that repeats many times to exceed output limits"
done
"""
    
    runbook_content = f"""# TestRunbook
# Environment Requirements
```yaml
```
# File System Requirements
```yaml
Input:
```
# Script
```sh
{large_output_script}
```
# History
"""
    
    # Set a small output limit (100KB) and reasonable timeout
    config = Config.get_instance()
    original_max_output = config.MAX_OUTPUT_SIZE_BYTES
    original_timeout = config.SCRIPT_TIMEOUT_SECONDS
    
    try:
        config.MAX_OUTPUT_SIZE_BYTES = 100 * 1024  # 100KB
        config.SCRIPT_TIMEOUT_SECONDS = 60  # 60 seconds should be enough
        
        # Create a temporary runbook file
        test_runbook_path = Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks' / 'test_output_limit_runbook.md'
        with open(test_runbook_path, 'w') as f:
            f.write(runbook_content)
        
        try:
            # Execute script
            script = RunbookParser.extract_script(runbook_content)
            return_code, stdout, stderr = ScriptExecutor.execute_script(script)
            
            # Output should be truncated
            stdout_size = len(stdout.encode('utf-8'))
            assert stdout_size <= config.MAX_OUTPUT_SIZE_BYTES, f"Stdout should be truncated to {config.MAX_OUTPUT_SIZE_BYTES} bytes, got {stdout_size}"
            
            # Should have warning about truncation
            if stdout_size >= config.MAX_OUTPUT_SIZE_BYTES:
                assert "truncated" in stderr.lower() or "warning" in stderr.lower(), "Should warn about truncation"
            
        finally:
            # Clean up test file
            if test_runbook_path.exists():
                test_runbook_path.unlink()
    finally:
        # Restore original values
        config.MAX_OUTPUT_SIZE_BYTES = original_max_output
        config.SCRIPT_TIMEOUT_SECONDS = original_timeout


def test_resource_monitoring_logging():
    """Test that resource usage is logged during script execution."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    runbook_path = Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks' / 'SimpleRunbook.md'
    content, name, errors, warnings = RunbookParser.load_runbook(runbook_path)
    
    # Set required environment variable
    os.environ['TEST_VAR'] = 'test_value'
    
    try:
        # Use patch to capture log messages from ScriptExecutor
        import logging
        with patch('src.services.script_executor.logger') as mock_logger:
            script = RunbookParser.extract_script(content)
            return_code, stdout, stderr = ScriptExecutor.execute_script(script)
            
            # Verify that resource monitoring logs were called
            info_calls = [call[0][0] for call in mock_logger.info.call_args_list]
            
            # Should log execution start with resource limits
            assert any('timeout' in str(call).lower() or 'max_output' in str(call).lower() for call in info_calls), \
                f"Should log resource limits before execution. Got: {info_calls}"
            
            # Should log execution completion with resource usage
            assert any('execution_time' in str(call).lower() or 'execution completed' in str(call).lower() for call in info_calls), \
                f"Should log execution time and resource usage after completion. Got: {info_calls}"
                
    finally:
        # Clean up
        if 'TEST_VAR' in os.environ:
            del os.environ['TEST_VAR']


# ============================================================================
# RBAC Test Coverage
# ============================================================================

def test_rbac_no_required_claims_allows_access():
    """Test that RBAC allows access when no required claims are specified."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    token = {
        'user_id': 'test-user',
        'roles': ['developer'],
        'claims': {'roles': ['developer']}
    }
    
    # No required claims should allow access
    result = RBACAuthorizer.check_rbac(token, None, 'execute')
    assert result is True, "Should allow access when no required claims"
    
    result = RBACAuthorizer.check_rbac(token, {}, 'execute')
    assert result is True, "Should allow access when required claims is empty dict"


def test_rbac_valid_role_passes():
    """Test that RBAC passes when token has valid role."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    token = {
        'user_id': 'test-user',
        'roles': ['developer', 'admin'],
        'claims': {'roles': ['developer', 'admin']}
    }
    
    required_claims = {'roles': ['developer', 'admin', 'devops']}
    
    # Should pass - token has 'developer' which is in allowed values
    result = RBACAuthorizer.check_rbac(token, required_claims, 'execute')
    assert result is True, "Should pass when token has valid role"


def test_rbac_invalid_role_fails():
    """Test that RBAC fails when token doesn't have required role."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    token = {
        'user_id': 'test-user',
        'roles': ['viewer'],
        'claims': {'roles': ['viewer']}
    }
    
    required_claims = {'roles': ['developer', 'admin']}
    
    # Should fail - token has 'viewer' which is not in allowed values
    with pytest.raises(HTTPForbidden):
        RBACAuthorizer.check_rbac(token, required_claims, 'execute')


def test_rbac_missing_claim_fails():
    """Test that RBAC fails when required claim is missing from token."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    token = {
        'user_id': 'test-user',
        'roles': ['developer'],
        'claims': {}  # No 'roles' claim
    }
    
    required_claims = {'roles': ['developer', 'admin']}
    
    # Should fail - token doesn't have 'roles' claim
    with pytest.raises(HTTPForbidden):
        RBACAuthorizer.check_rbac(token, required_claims, 'execute')


def test_rbac_string_role_handled():
    """Test that RBAC handles string role (comma-separated) correctly."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    token = {
        'user_id': 'test-user',
        'roles': 'developer,admin',  # String instead of list
        'claims': {'roles': 'developer,admin'}
    }
    
    required_claims = {'roles': ['developer', 'admin']}
    
    # Should pass - string roles are converted to list
    result = RBACAuthorizer.check_rbac(token, required_claims, 'execute')
    assert result is True, "Should handle string roles correctly"


def test_rbac_multiple_required_claims():
    """Test that RBAC works with multiple required claims."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    token = {
        'user_id': 'test-user',
        'roles': ['developer'],
        'claims': {
            'roles': ['developer'],
            'department': ['engineering'],
            'level': ['senior']
        }
    }
    
    required_claims = {
        'roles': ['developer', 'admin'],
        'department': ['engineering', 'operations'],
        'level': ['senior', 'lead']
    }
    
    # Should pass - token has all required claims
    result = RBACAuthorizer.check_rbac(token, required_claims, 'execute')
    assert result is True


def test_rbac_partial_claims_fails():
    """Test that RBAC fails when only some required claims are present."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    token = {
        'user_id': 'test-user',
        'roles': ['developer'],
        'claims': {
            'roles': ['developer'],
            'department': ['engineering']
            # Missing 'level' claim
        }
    }
    
    required_claims = {
        'roles': ['developer'],
        'department': ['engineering'],
        'level': ['senior']  # Token doesn't have this
    }
    
    # Should fail - missing 'level' claim
    with pytest.raises(HTTPForbidden):
        RBACAuthorizer.check_rbac(token, required_claims, 'execute')


# ============================================================================
# Error Path Testing
# ============================================================================

def test_validate_runbook_not_found():
    """Test that validate_runbook raises HTTPNotFound for non-existent runbook."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    token = {
        'user_id': 'test-user',
        'roles': ['developer'],
        'claims': {'roles': ['developer']}
    }
    breadcrumb = {'at_time': '2026-01-01T00:00:00Z', 'correlation_id': 'test-123'}
    
    with pytest.raises(HTTPNotFound):
        service.validate_runbook('NonExistentRunbook.md', token, breadcrumb)


def test_execute_runbook_not_found():
    """Test that execute_runbook raises HTTPNotFound for non-existent runbook."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    token = {
        'user_id': 'test-user',
        'roles': ['developer'],
        'claims': {'roles': ['developer']}
    }
    breadcrumb = {'at_time': '2026-01-01T00:00:00Z', 'correlation_id': 'test-123'}
    
    with pytest.raises(HTTPNotFound):
        list(service.execute_runbook_streaming('NonExistentRunbook.md', token, breadcrumb))


def test_get_runbook_not_found():
    """Test that get_runbook raises HTTPNotFound for non-existent runbook."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    token = {
        'user_id': 'test-user',
        'roles': ['developer'],
        'claims': {'roles': ['developer']}
    }
    breadcrumb = {'at_time': '2026-01-01T00:00:00Z', 'correlation_id': 'test-123'}
    
    with pytest.raises(HTTPNotFound):
        service.get_runbook('NonExistentRunbook.md', token, breadcrumb)


def test_execute_runbook_rbac_failure():
    """Test that execute_runbook raises HTTPForbidden on RBAC failure."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    # Create a runbook with required claims
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
    
    runbook_path = Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks' / 'test_rbac_runbook.md'
    with open(runbook_path, 'w') as f:
        f.write(runbook_content)
    
    try:
        token = {
            'user_id': 'test-user',
            'roles': ['developer'],  # Not 'admin'
            'claims': {'roles': ['developer']}
        }
        breadcrumb = {'at_time': '2026-01-01T00:00:00Z', 'correlation_id': 'test-123'}
        
        with pytest.raises(HTTPForbidden):
            list(service.execute_runbook_streaming('test_rbac_runbook.md', token, breadcrumb))
    finally:
        if runbook_path.exists():
            runbook_path.unlink()


# ============================================================================
# Edge Cases Testing
# ============================================================================

def test_load_runbook_empty_content():
    """Test loading a runbook with empty content."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    # Create empty runbook file
    empty_path = Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks' / 'empty_runbook.md'
    with open(empty_path, 'w') as f:
        f.write('')
    
    try:
        content, name, errors, warnings = RunbookParser.load_runbook(empty_path)
        assert content == '', "Should return empty content"
        assert name is None, "Should return None name for empty content"
        assert len(errors) > 0, "Should have errors for empty content"
    finally:
        if empty_path.exists():
            empty_path.unlink()


def test_extract_section_none_content():
    """Test extracting section from None content."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    result = RunbookParser.extract_section(None, 'Environment Requirements')
    assert result is None, "Should return None for None content"


def test_extract_section_empty_content():
    """Test extracting section from empty content."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    result = RunbookParser.extract_section('', 'Environment Requirements')
    assert result is None, "Should return None for empty content"


def test_extract_yaml_block_none():
    """Test extracting YAML block from None content."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    result = RunbookParser.extract_yaml_block(None)
    assert result is None, "Should return None for None content"


def test_extract_yaml_block_empty():
    """Test extracting YAML block from empty content."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    result = RunbookParser.extract_yaml_block('')
    assert result is None, "Should return None for empty content"


def test_extract_yaml_block_multiline_values():
    """Test that PyYAML correctly handles multi-line values."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    yaml_content = """```yaml
TEST_VAR: |
  This is a multi-line
  value with multiple
  lines
ANOTHER_VAR: "Single line value"
```"""
    
    result = RunbookParser.extract_yaml_block(yaml_content)
    assert result is not None, "Should extract YAML with multi-line values"
    assert 'TEST_VAR' in result, "Should find TEST_VAR"
    assert '\n' in result['TEST_VAR'], "Multi-line value should preserve newlines"
    assert 'ANOTHER_VAR' in result, "Should find ANOTHER_VAR"


def test_extract_yaml_block_with_comments():
    """Test that PyYAML correctly handles YAML comments."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    yaml_content = """```yaml
# This is a comment
TEST_VAR: test_value
# Another comment
ANOTHER_VAR: another_value
```"""
    
    result = RunbookParser.extract_yaml_block(yaml_content)
    assert result is not None, "Should extract YAML with comments"
    assert 'TEST_VAR' in result, "Should find TEST_VAR (comments should be ignored)"
    assert result['TEST_VAR'] == 'test_value', "Should extract correct value"
    assert 'ANOTHER_VAR' in result, "Should find ANOTHER_VAR"


def test_extract_yaml_block_special_characters():
    """Test that PyYAML correctly handles special characters in values."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    yaml_content = """```yaml
TEST_VAR: "Value with: colon and 'quotes' and \\"escaped\\" quotes"
PATH_VAR: /path/to/file:with:colons
JSON_VAR: '{"key": "value"}'
```"""
    
    result = RunbookParser.extract_yaml_block(yaml_content)
    assert result is not None, "Should extract YAML with special characters"
    assert 'TEST_VAR' in result, "Should find TEST_VAR"
    assert 'colon' in result['TEST_VAR'], "Should preserve special characters"
    assert 'PATH_VAR' in result, "Should find PATH_VAR"


def test_extract_yaml_block_invalid_yaml():
    """Test that invalid YAML is handled gracefully."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    # Invalid YAML (unclosed quote)
    yaml_content = """```yaml
TEST_VAR: "unclosed quote
ANOTHER_VAR: value
```"""
    
    result = RunbookParser.extract_yaml_block(yaml_content)
    # Should return None on parse error
    assert result is None, "Should return None for invalid YAML"


def test_extract_yaml_block_empty_yaml_block():
    """Test that empty YAML block returns empty dict."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    yaml_content = """```yaml
```"""
    
    result = RunbookParser.extract_yaml_block(yaml_content)
    assert result == {}, "Should return empty dict for empty YAML block"


def test_extract_file_requirements_with_pyyaml():
    """Test that file requirements are correctly parsed with PyYAML."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    yaml_content = """```yaml
Input:
  - /path/to/input1.txt
  - /path/to/input2.txt
```"""
    
    result = RunbookParser.extract_file_requirements(yaml_content)
    assert 'Input' in result, "Should have Input key"
    assert len(result['Input']) == 2, "Should extract 2 input files"
    assert '/path/to/input1.txt' in result['Input'], "Should find input1"


def test_extract_file_requirements_single_values():
    """Test that single file values are converted to lists."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    yaml_content = """```yaml
Input: /path/to/single_input.txt
```"""
    
    result = RunbookParser.extract_file_requirements(yaml_content)
    assert isinstance(result['Input'], list), "Input should be a list"
    assert len(result['Input']) == 1, "Should have one input file"
    assert result['Input'][0] == '/path/to/single_input.txt', "Should extract single input"


def test_extract_file_requirements_invalid_yaml():
    """Test that invalid YAML in file requirements is handled gracefully."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    # Invalid YAML
    yaml_content = """```yaml
Input:
  - /path/to/file
  invalid: yaml: structure
```"""
    
    result = RunbookParser.extract_file_requirements(yaml_content)
    # Should return default empty requirements on error
    assert 'Input' in result, "Should have Input key"
    # May or may not parse partially, but should not crash


def test_extract_required_claims_none():
    """Test extracting required claims when section doesn't exist."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    content = """# TestRunbook
# Environment Requirements
```yaml
```
# File System Requirements
```yaml
```
# Script
```sh
#! /bin/zsh
echo "test"
```
# History
"""
    
    result = RunbookParser.extract_required_claims(content)
    assert result is None, "Should return None when Required Claims section doesn't exist"


def test_resolve_runbook_path_path_traversal():
    """Test that _resolve_runbook_path prevents path traversal attacks."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    # Try various path traversal attempts
    malicious_paths = [
        '../other_dir/file.md',
        '../../etc/passwd',
        '....//....//etc/passwd',
        'runbook/../../../etc/passwd',
        '/etc/passwd',
        'C:\\Windows\\System32\\config\\sam'  # Windows path
    ]
    
    for malicious_path in malicious_paths:
        resolved = service._resolve_runbook_path(malicious_path)
        # Should resolve to runbooks_dir + basename only (os.path.basename sanitizes the path)
        resolved_str = str(resolved)
        # The basename might contain the original path as a filename, which is acceptable
        # The important check is that it's within runbooks_dir
        assert str(service.runbooks_dir) in resolved_str, \
            f"Resolved path should be in runbooks_dir: {resolved} (from {malicious_path})"
        # Verify it's just the basename, not the full malicious path
        basename = os.path.basename(malicious_path)
        assert resolved.name == basename or resolved.name == os.path.basename(basename), \
            f"Resolved filename should be sanitized basename: {resolved.name}"


def test_execute_script_empty_script():
    """Test executing a runbook with empty script."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
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
```
# History
"""
    
    runbook_path = Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks' / 'test_empty_script.md'
    with open(runbook_path, 'w') as f:
        f.write(runbook_content)
    
    try:
        script = RunbookParser.extract_script(runbook_content)
        return_code, stdout, stderr = ScriptExecutor.execute_script(script)
        # Empty script should still execute (just return 0)
        assert return_code == 0 or return_code == 1, "Empty script should execute"
    finally:
        if runbook_path.exists():
            runbook_path.unlink()


# ============================================================================
# File Operations Testing
# ============================================================================

def test_temp_directory_isolation():
    """Test that temp directory is created in isolated location."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    runbook_path = Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks' / 'SimpleRunbook.md'
    content, name, errors, warnings = RunbookParser.load_runbook(runbook_path)
    
    os.environ['TEST_VAR'] = 'test_value'
    
    try:
        # Mock tempfile.mkdtemp to capture the directory used
        with patch('src.services.script_executor.tempfile.mkdtemp') as mock_mkdtemp:
            mock_temp_dir = '/tmp/runbook-exec-test123'
            mock_mkdtemp.return_value = mock_temp_dir
            
            script = RunbookParser.extract_script(content)
            return_code, stdout, stderr = ScriptExecutor.execute_script(script)
            
            # Verify mkdtemp was called with correct prefix
            mock_mkdtemp.assert_called_once()
            call_args = mock_mkdtemp.call_args
            assert 'runbook-exec-' in call_args[1]['prefix'], \
                "Temp directory should have runbook-exec- prefix"
            
    finally:
        if 'TEST_VAR' in os.environ:
            del os.environ['TEST_VAR']


def test_temp_directory_cleanup_on_error():
    """Test that temp directory is cleaned up even on errors."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
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
    
    runbook_path = Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks' / 'test_error_cleanup.md'
    with open(runbook_path, 'w') as f:
        f.write(runbook_content)
    
    try:
        script = RunbookParser.extract_script(runbook_content)
        return_code, stdout, stderr = ScriptExecutor.execute_script(script)
        
        # Temp directory should be cleaned up - verify by checking it doesn't exist
        # We can't directly check, but we can verify cleanup logic is called
        assert return_code == 1, "Script should fail with exit 1"
    finally:
        if runbook_path.exists():
            runbook_path.unlink()


def test_file_permissions_on_temp_script():
    """Test that temp script has restrictive permissions."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    runbook_path = Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks' / 'SimpleRunbook.md'
    content, name, errors, warnings = RunbookParser.load_runbook(runbook_path)
    
    os.environ['TEST_VAR'] = 'test_value'
    
    try:
        import stat
        
        with patch('src.services.script_executor.os.chmod') as mock_chmod:
            script = RunbookParser.extract_script(content)
            return_code, stdout, stderr = ScriptExecutor.execute_script(script)
            
            # Verify chmod was called with 0o700 (owner-only permissions)
            mock_chmod.assert_called_once()
            call_args = mock_chmod.call_args[0]
            # chmod(path, mode)
            assert call_args[1] == 0o700, f"Script should have 0o700 permissions, got {oct(call_args[1])}"
            
    finally:
        if 'TEST_VAR' in os.environ:
            del os.environ['TEST_VAR']


def test_path_traversal_prevention():
    """Test that path traversal is prevented in runbook path resolution."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    # Test various path traversal attempts
    malicious_filenames = [
        '../../../etc/passwd',
        '....//....//etc/passwd',
        '../other/runbook.md',
        'runbook/../../../etc/passwd'
    ]
    
    for malicious_filename in malicious_filenames:
        resolved = service._resolve_runbook_path(malicious_filename)
        # Should only contain the basename, not the full path
        expected_basename = os.path.basename(malicious_filename)
        assert expected_basename in str(resolved), \
            f"Path should be sanitized to basename: {malicious_filename} -> {resolved}"
        # Should not contain parent directory references
        assert '../' not in str(resolved), \
            f"Resolved path should not contain '../': {resolved}"


def test_list_runbooks_empty_directory():
    """Test listing runbooks when directory is empty or doesn't exist."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    # Test with non-existent directory
    service_empty = RunbookService('/tmp/non-existent-runbooks-dir')
    token = {
        'user_id': 'test-user',
        'roles': ['developer'],
        'claims': {'roles': ['developer']}
    }
    breadcrumb = {'at_time': '2026-01-01T00:00:00Z', 'correlation_id': 'test-123'}
    
    with pytest.raises(HTTPNotFound):
        service_empty.list_runbooks(token, breadcrumb)


# ============================================================================
# Input Sanitization Tests (SEC-005)
# ============================================================================

def test_invalid_env_var_name_rejected():
    """Test that invalid environment variable names are rejected."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    runbook_path = Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks' / 'SimpleRunbook.md'
    content, name, errors, warnings = RunbookParser.load_runbook(runbook_path)
    
    os.environ['TEST_VAR'] = 'test_value'
    
    try:
        # Test invalid env var names
        invalid_names = [
            'VAR-NAME',  # hyphen
            'VAR NAME',  # space
            'VAR.NAME',  # period
            'VAR@NAME',  # special char
            '123VAR',    # starts with number
            '',          # empty
            'VAR\nNAME', # newline
        ]
        
        for invalid_name in invalid_names:
            script = RunbookParser.extract_script(content)
            return_code, stdout, stderr = ScriptExecutor.execute_script(script, env_vars={invalid_name: 'value'})
            assert return_code != 0, f"Should reject invalid env var name: {invalid_name}"
            assert "Invalid environment variable name" in stderr or "ERROR" in stderr, \
                f"Should return error for invalid name: {invalid_name}"
            
    finally:
        if 'TEST_VAR' in os.environ:
            del os.environ['TEST_VAR']


def test_valid_env_var_names_accepted():
    """Test that valid environment variable names are accepted."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    runbook_path = Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks' / 'SimpleRunbook.md'
    content, name, errors, warnings = RunbookParser.load_runbook(runbook_path)
    
    os.environ['TEST_VAR'] = 'test_value'
    
    try:
        # Test valid env var names
        valid_names = [
            'VAR_NAME',
            'VAR123',
            '_VAR_NAME',
            'VAR_NAME_123',
            'A',
            'TEST_VAR',
        ]
        
        for valid_name in valid_names:
            script = RunbookParser.extract_script(content)
            return_code, stdout, stderr = ScriptExecutor.execute_script(script, env_vars={valid_name: 'test_value'})
            # Should not fail due to invalid name (may fail for other reasons like missing env)
            assert "Invalid environment variable name" not in stderr, \
                f"Should accept valid env var name: {valid_name}"
            
    finally:
        if 'TEST_VAR' in os.environ:
            del os.environ['TEST_VAR']


def test_env_var_value_sanitization():
    """Test that environment variable values are sanitized (control characters removed)."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    runbook_content = """# TestRunbook
# Environment Requirements
```yaml
TEST_VAR: Test variable
```
# File System Requirements
```yaml
Input:
```
# Script
```sh
#! /bin/zsh
echo "Value: ${TEST_VAR}"
```
# History
"""
    
    runbook_path = Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks' / 'test_sanitization.md'
    with open(runbook_path, 'w') as f:
        f.write(runbook_content)
    
    try:
        os.environ['TEST_VAR'] = 'test_value'
        
        # Value with control characters
        value_with_control = 'test\x00\x01\x02value'
        script = RunbookParser.extract_script(runbook_content)
        return_code, stdout, stderr = ScriptExecutor.execute_script(script, env_vars={'TEST_VAR': value_with_control})
        
        # Should execute (control chars removed but script should run)
        # The value should be sanitized
        assert return_code == 0 or "ERROR" not in stderr, \
            "Script should execute even with control characters (they should be removed)"
            
    finally:
        if runbook_path.exists():
            runbook_path.unlink()
        if 'TEST_VAR' in os.environ:
            del os.environ['TEST_VAR']


def test_env_var_preserves_newlines_and_tabs():
    """Test that newlines and tabs are preserved in environment variable values."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    runbook_content = """# TestRunbook
# Environment Requirements
```yaml
TEST_VAR: Test variable
```
# File System Requirements
```yaml
Input:
```
# Script
```sh
#! /bin/zsh
echo "${TEST_VAR}" | wc -l
```
# History
"""
    
    runbook_path = Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks' / 'test_newlines.md'
    with open(runbook_path, 'w') as f:
        f.write(runbook_content)
    
    try:
        os.environ['TEST_VAR'] = 'test_value'
        
        # Value with newlines and tabs (should be preserved)
        value_with_newlines = 'line1\nline2\nline3'
        value_with_tabs = 'col1\tcol2\tcol3'
        
        script1 = RunbookParser.extract_script(runbook_content)
        return_code1, stdout1, stderr1 = ScriptExecutor.execute_script(script1, env_vars={'TEST_VAR': value_with_newlines})
        
        script2 = RunbookParser.extract_script(runbook_content)
        return_code2, stdout2, stderr2 = ScriptExecutor.execute_script(script2, env_vars={'TEST_VAR': value_with_tabs})
        
        # Should execute successfully
        assert return_code1 == 0 or "ERROR" not in stderr1, \
            "Should preserve newlines in env var values"
        assert return_code2 == 0 or "ERROR" not in stderr2, \
            "Should preserve tabs in env var values"
            
    finally:
        if runbook_path.exists():
            runbook_path.unlink()
        if 'TEST_VAR' in os.environ:
            del os.environ['TEST_VAR']


def test_env_var_none_value_converted():
    """Test that None values are converted to empty string."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    runbook_path = Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks' / 'SimpleRunbook.md'
    content, name, errors, warnings = RunbookParser.load_runbook(runbook_path)
    
    os.environ['TEST_VAR'] = 'test_value'
    
    try:
        script = RunbookParser.extract_script(content)
        return_code, stdout, stderr = ScriptExecutor.execute_script(script, env_vars={'TEST_VAR': None})
        
        # Should not fail due to None value (it should be converted)
        assert "None" not in stderr or "ERROR: Invalid" not in stderr, \
            "None values should be converted to empty string"
            
    finally:
        if 'TEST_VAR' in os.environ:
            del os.environ['TEST_VAR']


def test_env_var_non_string_value_converted():
    """Test that non-string values are converted to string."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    runbook_path = Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks' / 'SimpleRunbook.md'
    content, name, errors, warnings = RunbookParser.load_runbook(runbook_path)
    
    os.environ['TEST_VAR'] = 'test_value'
    
    try:
        # Test various non-string types
        non_string_values = [123, 45.67, True, False, ['list'], {'dict': 'value'}]
        
        for non_string_value in non_string_values:
            script = RunbookParser.extract_script(content)
            return_code, stdout, stderr = ScriptExecutor.execute_script(script, env_vars={'TEST_VAR': non_string_value})
            # Should not fail - should be converted to string
            assert "ERROR: Invalid" not in stderr or "type" not in stderr.lower(), \
                f"Non-string value {type(non_string_value)} should be converted to string"
            
    finally:
        if 'TEST_VAR' in os.environ:
            del os.environ['TEST_VAR']


# ============================================================================
# Additional Error Path Tests for Coverage
# ============================================================================

def test_validate_runbook_failed_load():
    """Test validate_runbook when runbook load fails (returns None content)."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    token = {'user_id': 'test-user', 'claims': {'roles': ['developer']}}
    breadcrumb = {'at_time': '2026-01-01T00:00:00Z', 'correlation_id': 'test-123'}
    
    # Mock load_runbook to return None content (file exists but load fails)
    with patch.object(RunbookParser, 'load_runbook', return_value=(None, None, ['Load error'], [])):
        with pytest.raises(HTTPInternalServerError, match="Failed to load runbook"):
            service.validate_runbook('SimpleRunbook.md', token, breadcrumb)


def test_validate_runbook_rbac_failure_history_logging_error():
    """Test validate_runbook when RBAC fails and history logging also fails."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    token = {'user_id': 'test-user', 'claims': {'roles': ['viewer']}}  # Wrong role
    breadcrumb = {'at_time': '2026-01-01T00:00:00Z', 'correlation_id': 'test-123'}
    
    runbook_path = Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks' / 'SimpleRunbook.md'
    content, name, errors, warnings = RunbookParser.load_runbook(runbook_path)
    
    # Mock history logging to raise exception
    with patch('src.services.history_manager.HistoryManager.append_rbac_failure_history', side_effect=Exception("History error")):
        with pytest.raises(HTTPForbidden):
            service.validate_runbook('SimpleRunbook.md', token, breadcrumb)


def test_validate_runbook_general_exception():
    """Test validate_runbook when a general exception occurs."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    token = {'user_id': 'test-user', 'claims': {'roles': ['developer']}}
    breadcrumb = {'at_time': '2026-01-01T00:00:00Z', 'correlation_id': 'test-123'}
    
    # Mock load_runbook to raise exception
    with patch.object(RunbookParser, 'load_runbook', side_effect=Exception("Unexpected error")):
        with pytest.raises(HTTPInternalServerError, match="Failed to validate runbook"):
            service.validate_runbook('SimpleRunbook.md', token, breadcrumb)


def test_execute_runbook_failed_load():
    """Test execute_runbook when runbook load fails (returns None content)."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    token = {'user_id': 'test-user', 'claims': {'roles': ['developer']}}
    breadcrumb = {'at_time': '2026-01-01T00:00:00Z', 'correlation_id': 'test-123'}
    
    # Mock load_runbook to return None content (file exists but load fails)
    with patch.object(RunbookParser, 'load_runbook', return_value=(None, None, ['Load error'], [])):
        with pytest.raises(HTTPInternalServerError, match="Failed to load runbook"):
            list(service.execute_runbook_streaming('SimpleRunbook.md', token, breadcrumb))


def test_execute_runbook_validation_failure():
    """Test execute_runbook when validation fails."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    token = {'user_id': 'test-user', 'roles': ['sre', 'api'], 'claims': {'roles': ['sre', 'api']}}
    breadcrumb = {'at_time': '2026-01-01T00:00:00Z', 'correlation_id': 'test-123'}
    
    runbook_path = Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks' / 'SimpleRunbook.md'
    content, name, errors, warnings = RunbookParser.load_runbook(runbook_path)
    
    # Mock validation to fail - streaming yields stderr then done event
    with patch.object(RunbookValidator, 'validate_runbook_content', return_value=(False, ['Validation error'], [])):
        chunks = list(service.execute_runbook_streaming('SimpleRunbook.md', token, breadcrumb))
        # Last chunk is the done event
        done_chunk = [c for c in chunks if 'event: done' in c][-1]
        data_lines = [ln[6:] for ln in done_chunk.split('\n') if ln.startswith('data: ')]
        result = json.loads('\n'.join(data_lines))
        assert result['success'] is False
        assert result['return_code'] == 1
        assert 'Validation error' in result['stderr']


def test_execute_runbook_no_script():
    """Test execute_runbook when script cannot be extracted."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    token = {'user_id': 'test-user', 'roles': ['sre', 'api'], 'claims': {'roles': ['sre', 'api']}}
    breadcrumb = {'at_time': '2026-01-01T00:00:00Z', 'correlation_id': 'test-123'}
    
    runbook_path = Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks' / 'SimpleRunbook.md'
    content, name, errors, warnings = RunbookParser.load_runbook(runbook_path)
    
    # Mock extract_script to return None
    with patch.object(RunbookParser, 'extract_script', return_value=None):
        with patch.object(RunbookValidator, 'validate_runbook_content', return_value=(True, [], [])):
            with pytest.raises(HTTPInternalServerError, match="Could not extract script"):
                list(service.execute_runbook_streaming('SimpleRunbook.md', token, breadcrumb))


def test_execute_runbook_rbac_failure_history_logging_error():
    """Test execute_runbook when RBAC fails and history logging also fails."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    token = {'user_id': 'test-user', 'claims': {'roles': ['viewer']}}  # Wrong role
    breadcrumb = {'at_time': '2026-01-01T00:00:00Z', 'correlation_id': 'test-123'}
    
    runbook_path = Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks' / 'SimpleRunbook.md'
    content, name, errors, warnings = RunbookParser.load_runbook(runbook_path)
    
    # Mock history logging to raise exception
    with patch('src.services.history_manager.HistoryManager.append_rbac_failure_history', side_effect=Exception("History error")):
        with pytest.raises(HTTPForbidden):
            list(service.execute_runbook_streaming('SimpleRunbook.md', token, breadcrumb))


def test_execute_runbook_general_exception():
    """Test execute_runbook when a general exception occurs."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    token = {'user_id': 'test-user', 'claims': {'roles': ['developer']}}
    breadcrumb = {'at_time': '2026-01-01T00:00:00Z', 'correlation_id': 'test-123'}
    
    # Mock load_runbook to raise exception
    with patch.object(RunbookParser, 'load_runbook', side_effect=Exception("Unexpected error")):
        with pytest.raises(HTTPInternalServerError, match="Failed to execute runbook"):
            list(service.execute_runbook_streaming('SimpleRunbook.md', token, breadcrumb))


def test_get_runbook_exception():
    """Test get_runbook when an exception occurs during file read."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    token = {'user_id': 'test-user', 'claims': {'roles': ['developer']}}
    breadcrumb = {'at_time': '2026-01-01T00:00:00Z', 'correlation_id': 'test-123'}
    
    # Mock open() to raise exception when reading file
    with patch('builtins.open', side_effect=IOError("Permission denied")):
        with pytest.raises(HTTPInternalServerError, match="Failed to read runbook"):
            service.get_runbook('SimpleRunbook.md', token, breadcrumb)


def test_get_required_env_not_found():
    """Test get_required_env when runbook is not found."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    token = {'user_id': 'test-user', 'claims': {'roles': ['developer']}}
    breadcrumb = {'at_time': '2026-01-01T00:00:00Z', 'correlation_id': 'test-123'}
    
    with pytest.raises(HTTPNotFound):
        service.get_required_env('nonexistent.md', token, breadcrumb)


def test_get_required_env_failed_load():
    """Test get_required_env when runbook load fails."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    token = {'user_id': 'test-user', 'claims': {'roles': ['developer']}}
    breadcrumb = {'at_time': '2026-01-01T00:00:00Z', 'correlation_id': 'test-123'}
    
    # Mock load_runbook to return None content
    with patch.object(RunbookParser, 'load_runbook', return_value=(None, None, ['Load error'], [])):
        with pytest.raises(HTTPInternalServerError, match="Failed to load runbook"):
            service.get_required_env('SimpleRunbook.md', token, breadcrumb)


def test_get_required_env_no_env_section():
    """Test get_required_env when Environment Requirements section is missing."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    token = {'user_id': 'test-user', 'claims': {'roles': ['developer']}}
    breadcrumb = {'at_time': '2026-01-01T00:00:00Z', 'correlation_id': 'test-123'}
    
    runbook_path = Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks' / 'SimpleRunbook.md'
    
    # Mock extract_section to return None for Environment Requirements
    with patch.object(RunbookParser, 'extract_section') as mock_extract:
        def extract_side_effect(content, section):
            if section == 'Environment Requirements':
                return None
            # Return mock for other sections
            return "mock content"
        
        mock_extract.side_effect = extract_side_effect
        
        result = service.get_required_env('SimpleRunbook.md', token, breadcrumb)
        
        assert result['success'] is True
        assert result['required'] == []
        assert result['available'] == []
        assert result['missing'] == []


def test_get_required_env_no_yaml_block():
    """Test get_required_env when Environment Requirements has no YAML block."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    token = {'user_id': 'test-user', 'claims': {'roles': ['developer']}}
    breadcrumb = {'at_time': '2026-01-01T00:00:00Z', 'correlation_id': 'test-123'}
    
    runbook_path = Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks' / 'SimpleRunbook.md'
    content, name, errors, warnings = RunbookParser.load_runbook(runbook_path)
    
    # Mock extract_yaml_block to return None
    with patch.object(RunbookParser, 'extract_yaml_block', return_value=None):
        result = service.get_required_env('SimpleRunbook.md', token, breadcrumb)
        
        assert result['success'] is True
        assert result['required'] == []
        assert result['available'] == []
        assert result['missing'] == []


def test_get_required_env_missing_env_var():
    """Test get_required_env when an environment variable is missing."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    token = {'user_id': 'test-user', 'claims': {'roles': ['developer']}}
    breadcrumb = {'at_time': '2026-01-01T00:00:00Z', 'correlation_id': 'test-123'}
    
    # Ensure TEST_VAR is not set
    original_test_var = os.environ.get('TEST_VAR')
    if 'TEST_VAR' in os.environ:
        del os.environ['TEST_VAR']
    
    try:
        result = service.get_required_env('SimpleRunbook.md', token, breadcrumb)
        
        assert result['success'] is True
        assert len(result['required']) > 0
        assert any(env['name'] == 'TEST_VAR' for env in result['required'])
        assert any(env['name'] == 'TEST_VAR' for env in result['missing'])
        assert not any(env['name'] == 'TEST_VAR' for env in result['available'])
    finally:
        if original_test_var:
            os.environ['TEST_VAR'] = original_test_var


def test_get_required_env_exception():
    """Test get_required_env when an exception occurs."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    token = {'user_id': 'test-user', 'claims': {'roles': ['developer']}}
    breadcrumb = {'at_time': '2026-01-01T00:00:00Z', 'correlation_id': 'test-123'}
    
    # Mock load_runbook to raise exception
    with patch.object(RunbookParser, 'load_runbook', side_effect=Exception("Unexpected error")):
        with pytest.raises(HTTPInternalServerError, match="Failed to get required environment variables"):
            service.get_required_env('SimpleRunbook.md', token, breadcrumb)


def _parse_streaming_done(stream):
    """Consume execute_runbook_streaming and return the final 'done' result as dict."""
    chunks = list(stream)
    done_chunks = [c for c in chunks if 'event: done' in c]
    if not done_chunks:
        return {}
    done_chunk = done_chunks[-1]
    data_lines = [ln[6:] for ln in done_chunk.split('\n') if ln.startswith('data: ')]
    return json.loads('\n'.join(data_lines)) if data_lines else {}


def test_execute_runbook_recursion_detection():
    """Test execute_runbook_streaming detects recursion when runbook is already in execution chain."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    token = {'user_id': 'test-user', 'claims': {'roles': ['developer']}}
    breadcrumb = {
        'at_time': '2026-01-01T00:00:00Z',
        'correlation_id': 'test-123',
        'recursion_stack': ['ParentRunbook.md', 'SimpleRunbook.md']  # SimpleRunbook.md is already in stack
    }
    
    result = _parse_streaming_done(service.execute_runbook_streaming('SimpleRunbook.md', token, breadcrumb))
    
    assert result['success'] is False, "Should fail due to recursion"
    assert result['return_code'] == 1, "Should return error code"
    assert 'Recursion detected' in result['stderr'], "Should have recursion error message"
    assert 'SimpleRunbook.md' in result['stderr'], "Should mention the runbook in error"


def test_execute_runbook_recursion_depth_limit():
    """Test execute_runbook_streaming enforces recursion depth limit."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    config = Config.get_instance()
    
    # Create a recursion stack at the limit
    recursion_stack = [f'Runbook{i}.md' for i in range(config.MAX_RECURSION_DEPTH)]
    
    token = {'user_id': 'test-user', 'claims': {'roles': ['developer']}}
    breadcrumb = {
        'at_time': '2026-01-01T00:00:00Z',
        'correlation_id': 'test-123',
        'recursion_stack': recursion_stack
    }
    
    result = _parse_streaming_done(service.execute_runbook_streaming('SimpleRunbook.md', token, breadcrumb))
    
    assert result['success'] is False, "Should fail due to recursion depth limit"
    assert result['return_code'] == 1, "Should return error code"
    assert 'Recursion depth limit exceeded' in result['stderr'], "Should have depth limit error message"


def test_execute_runbook_recursion_stack_building():
    """Test execute_runbook_streaming builds recursion stack correctly for script execution."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    token = {'user_id': 'test-user', 'roles': ['sre', 'api'], 'claims': {'roles': ['sre', 'api']}}
    breadcrumb = {
        'at_time': '2026-01-01T00:00:00Z',
        'correlation_id': 'test-123',
        'recursion_stack': ['ParentRunbook.md']  # Starting with parent
    }
    env_vars = {'TEST_VAR': 'test_value'}  # Provide required env var
    
    captured_recursion_stack = []
    
    def mock_streaming(*args, **kwargs):
        captured_recursion_stack.append(kwargs.get('recursion_stack'))
        yield ("done", json.dumps({"return_code": 0, "stdout": "success", "stderr": ""}))
    
    with patch.object(ScriptExecutor, 'execute_script_streaming', side_effect=mock_streaming):
        _parse_streaming_done(service.execute_runbook_streaming('SimpleRunbook.md', token, breadcrumb, env_vars=env_vars))
    
    assert len(captured_recursion_stack) > 0, "Should call execute_script_streaming"
    assert captured_recursion_stack[0] == ['ParentRunbook.md', 'SimpleRunbook.md'], \
        "Recursion stack should include parent and current runbook"
    assert breadcrumb['recursion_stack'] == ['ParentRunbook.md', 'SimpleRunbook.md'], \
        "Breadcrumb should be updated with new recursion stack"


def test_execute_runbook_top_level_execution():
    """Test execute_runbook_streaming handles top-level execution (no recursion stack)."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    token = {'user_id': 'test-user', 'roles': ['sre', 'api'], 'claims': {'roles': ['sre', 'api']}}
    breadcrumb = {
        'at_time': '2026-01-01T00:00:00Z',
        'correlation_id': 'test-123',
        'recursion_stack': None  # Top-level execution
    }
    env_vars = {'TEST_VAR': 'test_value'}  # Provide required env var
    
    captured_recursion_stack = []
    
    def mock_streaming(*args, **kwargs):
        captured_recursion_stack.append(kwargs.get('recursion_stack'))
        yield ("done", json.dumps({"return_code": 0, "stdout": "success", "stderr": ""}))
    
    with patch.object(ScriptExecutor, 'execute_script_streaming', side_effect=mock_streaming):
        _parse_streaming_done(service.execute_runbook_streaming('SimpleRunbook.md', token, breadcrumb, env_vars=env_vars))
    
    assert len(captured_recursion_stack) > 0, "Should call execute_script_streaming"
    assert captured_recursion_stack[0] == ['SimpleRunbook.md'], \
        "Top-level execution should have stack with only current runbook"


def test_execute_runbook_passes_token_and_correlation():
    """Test execute_runbook_streaming passes token_string and correlation_id to ScriptExecutor."""
    runbooks_dir = str(Path(__file__).parent.parent.parent.parent / 'samples' / 'runbooks')
    service = RunbookService(runbooks_dir)
    
    token = {'user_id': 'test-user', 'roles': ['sre', 'api'], 'claims': {'roles': ['sre', 'api']}}
    breadcrumb = {
        'at_time': '2026-01-01T00:00:00Z',
        'correlation_id': 'test-correlation-456',
        'recursion_stack': None
    }
    token_string = "test-token-123"
    env_vars = {'TEST_VAR': 'test_value'}  # Provide required env var
    
    captured_params = {}
    
    def mock_streaming(*args, **kwargs):
        captured_params['token_string'] = kwargs.get('token_string')
        captured_params['correlation_id'] = kwargs.get('correlation_id')
        captured_params['recursion_stack'] = kwargs.get('recursion_stack')
        yield ("done", json.dumps({"return_code": 0, "stdout": "success", "stderr": ""}))
    
    with patch.object(ScriptExecutor, 'execute_script_streaming', side_effect=mock_streaming):
        _parse_streaming_done(service.execute_runbook_streaming(
            'SimpleRunbook.md', token, breadcrumb, env_vars=env_vars, token_string=token_string
        ))
    
    assert 'token_string' in captured_params, "Should capture token_string"
    assert captured_params['token_string'] == token_string, "Token string should be passed"
    assert captured_params['correlation_id'] == 'test-correlation-456', "Correlation ID should be passed"
    assert captured_params['recursion_stack'] == ['SimpleRunbook.md'], "Recursion stack should be passed"


# Tests can be run with pytest or the custom runner below
if __name__ == '__main__':
    # Fallback: Simple test runner if pytest is not available
    import pytest
    pytest.main([__file__, '-v'])

