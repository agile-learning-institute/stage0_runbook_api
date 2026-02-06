#!/usr/bin/env python3
"""
Unit tests for Config singleton.
"""
import os
import sys
import logging
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.config.config import Config


class TestConfigSingleton:
    """Test singleton pattern."""
    
    def test_singleton_prevents_multiple_instances(self):
        """Test that Config enforces singleton pattern."""
        # Reset singleton
        Config._instance = None
        # Set JWT_SECRET to avoid fail-fast
        os.environ['JWT_SECRET'] = 'test-secret-for-unit-tests'
        
        # Create first instance
        config1 = Config.get_instance()
        
        # Try to create second instance directly - should raise exception
        with pytest.raises(Exception, match="This class is a singleton!"):
            Config()
        
        # get_instance should return same instance
        config2 = Config.get_instance()
        assert config1 is config2
    
    def test_get_instance_creates_if_none(self):
        """Test that get_instance creates instance if none exists."""
        # Reset singleton
        Config._instance = None
        # Set JWT_SECRET to avoid fail-fast
        os.environ['JWT_SECRET'] = 'test-secret-for-unit-tests'
        
        config = Config.get_instance()
        assert config is not None
        assert isinstance(config, Config)


class TestConfigDefaults:
    """Test default configuration values."""
    
    def setup_method(self):
        """Reset config before each test."""
        Config._instance = None
        # Clear relevant env vars
        for key in ['API_PORT', 'RUNBOOKS_DIR', 'ENABLE_LOGIN']:
            if key in os.environ:
                del os.environ[key]
        # Do not clear EXECUTION_DIR/MOUNT_DIR; conftest sets them so Config validation passes
        # Always set JWT_SECRET to a non-default value to avoid fail-fast
        os.environ['JWT_SECRET'] = 'test-secret-for-unit-tests'
    
    def test_string_defaults(self):
        """Test default string values."""
        config = Config.get_instance()
        assert config.BUILT_AT == "LOCAL"
        # LOGGING_LEVEL is converted to int by configure_logging(), check default instead
        assert config.get_default('LOGGING_LEVEL') == "INFO"
        assert config.RUNBOOKS_DIR == "/runbooks"
    
    def test_int_defaults(self):
        """Test default integer values."""
        config = Config.get_instance()
        assert config.API_PORT == 8083
        assert config.JWT_TTL_MINUTES == 480
        assert config.SCRIPT_TIMEOUT_SECONDS == 600
        assert config.MAX_OUTPUT_SIZE_BYTES == 10485760
    
    def test_boolean_defaults(self):
        """Test default boolean values."""
        config = Config.get_instance()
        assert config.ENABLE_LOGIN is False
    
    def test_jwt_defaults(self):
        """Test JWT-related defaults."""
        config = Config.get_instance()
        assert config.JWT_ALGORITHM == "HS256"
        assert config.JWT_ISSUER == "dev-idp"
        assert config.JWT_AUDIENCE == "dev-api"
    
    def test_secret_defaults(self):
        """Test secret default values - should use provided value, fail-fast if default is used."""
        config = Config.get_instance()
        # Should use the test secret set in setup_method
        assert config.JWT_SECRET == 'test-secret-for-unit-tests'
        assert len(config.JWT_SECRET) > 0
        # Check that it's marked as from environment in config_items
        jwt_item = next((item for item in config.config_items if item['name'] == 'JWT_SECRET'), None)
        assert jwt_item is not None
        assert jwt_item['from'] == 'environment'


class TestConfigEnvironmentVariables:
    """Test environment variable overrides."""
    
    def setup_method(self):
        """Reset config before each test."""
        Config._instance = None
        # Always set JWT_SECRET to a non-default value to avoid fail-fast
        os.environ['JWT_SECRET'] = 'test-secret-for-unit-tests'
    
    def teardown_method(self):
        """Clean up environment variables."""
        for key in ['API_PORT', 'RUNBOOKS_DIR', 'ENABLE_LOGIN', 'JWT_SECRET', 'LOGGING_LEVEL']:
            if key in os.environ:
                del os.environ[key]
    
    def test_env_var_overrides_string_default(self):
        """Test that environment variables override string defaults."""
        os.environ['RUNBOOKS_DIR'] = '/custom/path'
        config = Config.get_instance()
        assert config.RUNBOOKS_DIR == '/custom/path'
    
    def test_env_var_overrides_int_default(self):
        """Test that environment variables override integer defaults."""
        os.environ['API_PORT'] = '9000'
        config = Config.get_instance()
        assert config.API_PORT == 9000
        assert isinstance(config.API_PORT, int)
    
    def test_env_var_overrides_boolean_default(self):
        """Test that environment variables override boolean defaults."""
        os.environ['ENABLE_LOGIN'] = 'true'
        config = Config.get_instance()
        assert config.ENABLE_LOGIN is True
        
        Config._instance = None
        os.environ['ENABLE_LOGIN'] = 'false'
        config = Config.get_instance()
        assert config.ENABLE_LOGIN is False
    
    def test_env_var_overrides_secret_default(self):
        """Test that environment variables override secret defaults."""
        os.environ['JWT_SECRET'] = 'production-secret'
        config = Config.get_instance()
        assert config.JWT_SECRET == 'production-secret'
    
    def test_boolean_case_insensitive(self):
        """Test that boolean values are case-insensitive."""
        Config._instance = None
        os.environ['ENABLE_LOGIN'] = 'TRUE'
        config = Config.get_instance()
        assert config.ENABLE_LOGIN is True
        
        Config._instance = None
        os.environ['ENABLE_LOGIN'] = 'False'
        config = Config.get_instance()
        assert config.ENABLE_LOGIN is False


class TestConfigItems:
    """Test config_items tracking."""
    
    def setup_method(self):
        """Reset config before each test."""
        Config._instance = None
        if 'RUNBOOKS_DIR' in os.environ:
            del os.environ['RUNBOOKS_DIR']
        # Always set JWT_SECRET to a non-default value to avoid fail-fast
        os.environ['JWT_SECRET'] = 'test-secret-for-unit-tests'
    
    def test_config_items_tracks_defaults(self):
        """Test that config_items tracks default values."""
        config = Config.get_instance()
        
        # Find RUNBOOKS_DIR in config_items
        runbooks_item = next((item for item in config.config_items if item['name'] == 'RUNBOOKS_DIR'), None)
        assert runbooks_item is not None
        assert runbooks_item['from'] == 'default'
        assert runbooks_item['value'] == '/runbooks'
    
    def test_config_items_tracks_env_vars(self):
        """Test that config_items tracks environment variable values."""
        os.environ['RUNBOOKS_DIR'] = '/env/path'
        config = Config.get_instance()
        
        runbooks_item = next((item for item in config.config_items if item['name'] == 'RUNBOOKS_DIR'), None)
        assert runbooks_item is not None
        assert runbooks_item['from'] == 'environment'
        assert runbooks_item['value'] == '/env/path'
    
    def test_config_items_masks_secrets(self):
        """Test that config_items masks secret values."""
        os.environ['JWT_SECRET'] = 'my-secret-key'
        config = Config.get_instance()
        
        jwt_item = next((item for item in config.config_items if item['name'] == 'JWT_SECRET'), None)
        assert jwt_item is not None
        assert jwt_item['value'] == 'secret'  # Masked
        assert jwt_item['from'] in ['default', 'environment']


class TestConfigMethods:
    """Test Config class methods."""
    
    def setup_method(self):
        """Reset config before each test."""
        Config._instance = None
        # Always set JWT_SECRET to a non-default value to avoid fail-fast
        os.environ['JWT_SECRET'] = 'test-secret-for-unit-tests'
    
    def teardown_method(self):
        """Clean up environment variables."""
        if 'TEST_VAR' in os.environ:
            del os.environ['TEST_VAR']
    
    def test_get_default_string(self):
        """Test get_default for string config."""
        config = Config.get_instance()
        assert config.get_default('RUNBOOKS_DIR') == '/runbooks'
        assert config.get_default('BUILT_AT') == 'LOCAL'
    
    def test_get_default_int(self):
        """Test get_default for integer config."""
        config = Config.get_instance()
        assert config.get_default('API_PORT') == 8083
        assert config.get_default('SCRIPT_TIMEOUT_SECONDS') == 600
    
    def test_get_default_boolean(self):
        """Test get_default for boolean config."""
        config = Config.get_instance()
        assert config.get_default('ENABLE_LOGIN') is False
    
    def test_get_default_secret(self):
        """Test get_default for secret config."""
        config = Config.get_instance()
        assert config.get_default('JWT_SECRET') == 'dev-secret-change-me'
    
    def test_get_default_jwt_hardcoded(self):
        """Test get_default for hardcoded JWT defaults."""
        config = Config.get_instance()
        assert config.get_default('JWT_ALGORITHM') == 'HS256'
        assert config.get_default('JWT_ISSUER') == 'dev-idp'
        assert config.get_default('JWT_AUDIENCE') == 'dev-api'
    
    def test_get_default_nonexistent(self):
        """Test get_default for nonexistent config."""
        config = Config.get_instance()
        assert config.get_default('NONEXISTENT_KEY') is None
    
    def test_check_var_required_set(self):
        """Test check_var with required=True and variable set."""
        os.environ['TEST_VAR'] = 'test_value'
        config = Config.get_instance()
        assert config.check_var('TEST_VAR', required=True) == 'test_value'
    
    def test_check_var_required_not_set(self):
        """Test check_var with required=True and variable not set."""
        if 'TEST_VAR' in os.environ:
            del os.environ['TEST_VAR']
        config = Config.get_instance()
        with pytest.raises(ValueError, match="Required environment variable TEST_VAR is not set"):
            config.check_var('TEST_VAR', required=True)
    
    def test_check_var_not_required_set(self):
        """Test check_var with required=False and variable set."""
        os.environ['TEST_VAR'] = 'test_value'
        config = Config.get_instance()
        assert config.check_var('TEST_VAR', required=False) == 'test_value'
    
    def test_check_var_not_required_not_set(self):
        """Test check_var with required=False and variable not set."""
        if 'TEST_VAR' in os.environ:
            del os.environ['TEST_VAR']
        config = Config.get_instance()
        assert config.check_var('TEST_VAR', required=False) == ''
    
    def test_to_dict(self):
        """Test to_dict method."""
        config = Config.get_instance()
        token = {'user_id': 'test_user', 'roles': ['admin']}
        
        result = config.to_dict(token)
        assert 'config_items' in result
        assert 'token' in result
        assert result['token'] == token
        assert isinstance(result['config_items'], list)
        assert len(result['config_items']) > 0
    
    def test_initialize_resets_config_items(self):
        """Test that initialize resets config_items."""
        config = Config.get_instance()
        initial_count = len(config.config_items)
        
        config.initialize()
        # Should have same number of items (all re-added)
        assert len(config.config_items) == initial_count


class TestConfigLogging:
    """Test logging configuration."""
    
    def setup_method(self):
        """Reset config before each test."""
        Config._instance = None
        # Always set JWT_SECRET to a non-default value to avoid fail-fast
        os.environ['JWT_SECRET'] = 'test-secret-for-unit-tests'
    
    def test_configure_logging_sets_level(self):
        """Test that configure_logging sets logging level."""
        os.environ['LOGGING_LEVEL'] = 'DEBUG'
        config = Config.get_instance()
        # configure_logging is called in __init__, so level should be set
        # We can't easily test the actual level without more complex mocking
        assert hasattr(config, 'LOGGING_LEVEL')
    
    def test_configure_logging_with_invalid_level(self):
        """Test that configure_logging handles invalid level gracefully."""
        os.environ['LOGGING_LEVEL'] = 'INVALID_LEVEL'
        config = Config.get_instance()
        # Should default to INFO if invalid
        assert config.LOGGING_LEVEL == logging.INFO or hasattr(logging, config.LOGGING_LEVEL)


def _mock_exec_path(exists=True, is_dir=True):
    """Return a mock Path for EXECUTION_DIR with .resolve() returning self."""
    mock = MagicMock()
    mock.exists.return_value = exists
    mock.is_dir.return_value = is_dir
    mock.resolve.return_value = mock
    return mock


class TestConfigExecutionDir:
    """Test EXECUTION_DIR (container path) and MOUNT_DIR (host path) validation."""

    def setup_method(self):
        """Reset config and env before each test."""
        Config._instance = None
        os.environ['JWT_SECRET'] = 'test-secret-for-unit-tests'
        for key in ('EXECUTION_DIR', 'MOUNT_DIR'):
            if key in os.environ:
                del os.environ[key]

    def teardown_method(self):
        """Clean up."""
        for key in ('EXECUTION_DIR', 'MOUNT_DIR'):
            if key in os.environ:
                del os.environ[key]

    def test_execution_dir_when_mount_dir_default_raises(self):
        """When MOUNT_DIR is default (not set), raise."""
        with pytest.raises(ValueError, match="MOUNT_DIR is not set"):
            Config.get_instance()

    def test_execution_dir_when_path_missing_raises(self):
        """When EXECUTION_DIR path does not exist, raise."""
        os.environ['MOUNT_DIR'] = '/host/execution'
        mock_exec = _mock_exec_path(exists=False)
        with patch('src.config.config.Path', return_value=mock_exec):
            with pytest.raises(ValueError, match="does not exist"):
                Config.get_instance()

    def test_execution_dir_when_path_not_dir_raises(self):
        """When EXECUTION_DIR path exists but is not a directory, raise."""
        os.environ['MOUNT_DIR'] = '/host/execution'
        mock_exec = _mock_exec_path(exists=True, is_dir=False)
        with patch('src.config.config.Path', return_value=mock_exec):
            with pytest.raises(ValueError, match="is not a directory"):
                Config.get_instance()

    def test_execution_dir_when_path_not_writable_raises(self):
        """When EXECUTION_DIR path exists but is not writable, raise."""
        os.environ['MOUNT_DIR'] = '/host/execution'
        mock_exec = _mock_exec_path(exists=True, is_dir=True)
        with patch('src.config.config.Path', return_value=mock_exec):
            with patch('src.config.config.os.access', return_value=False):
                with pytest.raises(ValueError, match="is not writable"):
                    Config.get_instance()

    def test_execution_dir_when_all_valid_succeeds(self):
        """When MOUNT_DIR is set and EXECUTION_DIR path exists, is dir, and is writable, validation passes."""
        os.environ['MOUNT_DIR'] = '/host/execution'
        mock_exec = _mock_exec_path(exists=True, is_dir=True)
        with patch('src.config.config.Path', return_value=mock_exec):
            with patch('src.config.config.os.access', return_value=True):
                config = Config.get_instance()
        assert config.EXECUTION_DIR == '/execution'  # default
        assert config.MOUNT_DIR == '/host/execution'

