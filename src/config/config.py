"""
Configuration management module for stage0_runbook_api.

This module provides a singleton Config class that manages application configuration
with support for configuration sources (environment variables, defaults).

This is a simplified version without MongoDB dependencies.
"""
import os
import json
from pathlib import Path

import logging
logger = logging.getLogger(__name__)

class Config:
    """
    Singleton configuration manager for the application.
    
    The Config class provides centralized configuration management with a priority
    system for configuration sources:
    1. Environment variables
    2. Default values (defined in class)
    
    Configuration values are automatically typed based on their category:
    - Strings: Plain text values
    - Integers: Numeric port numbers and similar values
    - Booleans: True/false flags
    
    Secret values are masked in the config_items tracking list to prevent
    accidental exposure in logs or API responses.
    
    Attributes:
        _instance (Config): The singleton instance of the Config class.
        config_items (list): List of dictionaries tracking each config value's
            source and value (secrets are masked).
    
    Example:
        >>> config = Config.get_instance()
        >>> print(config.API_PORT)
        8083
    """
    _instance = None  # Singleton instance

    def __init__(self):
        """
        Initialize the Config singleton instance.
        
        Raises:
            Exception: If an instance already exists (singleton pattern enforcement).
        
        Note:
            This constructor should not be called directly. Use get_instance() instead.
        """
        if Config._instance is not None:
            raise Exception("This class is a singleton!")
        else:
            Config._instance = self
            self.config_items = []
            
            # Declare instance variables to support IDE code assist
            self.BUILT_AT = ''
            self.LOGGING_LEVEL = ''
            self.ENABLE_LOGIN = False
            self.API_PORT = 0
            self.API_PROTOCOL = ''
            self.API_HOST = ''
            self.RUNBOOKS_DIR = ''
            self.EXECUTION_DIR = ''   # container path where per-run dirs are created (default /execution)
            self.MOUNT_DIR = ''       # host path mounted at EXECUTION_DIR (for docker run -v from scripts)
            self.MAX_RECURSION_DEPTH = 0

            # JWT Configuration
            self.JWT_SECRET = ''
            self.JWT_ALGORITHM = ''
            self.JWT_ISSUER = ''
            self.JWT_AUDIENCE = ''
            self.JWT_TTL_MINUTES = 0
            
            # Script Execution Resource Limits
            self.SCRIPT_TIMEOUT_SECONDS = 0
            self.MAX_OUTPUT_SIZE_BYTES = 0
    
            # Default Values grouped by value type            
            self.config_strings = {
                "BUILT_AT": "LOCAL",
                "LOGGING_LEVEL": "INFO",
                "RUNBOOKS_DIR": "./samples/runbooks",
                "EXECUTION_DIR": "/execution",  # container path for per-run dirs; image has read-only dir until overridden by mount
                "MOUNT_DIR": "",  # host path mounted at EXECUTION_DIR (set in container so RUNBOOK_EXEC_DIR_HOST is correct)
                "API_PROTOCOL": "http",  # http or https
                "API_HOST": "localhost",  # hostname for API base URL
                "UI_HEADER": "Stage0 Runbook Automation",  # title shown in SPA app bar
                "JWT_ALGORITHM": "HS256",
                "JWT_ISSUER": "dev-idp",
                "JWT_AUDIENCE": "dev-api",
            }
            self.config_ints = {
                "API_PORT": "8083",
                "JWT_TTL_MINUTES": "480",
                "SCRIPT_TIMEOUT_SECONDS": "600",  # 10 minutes default
                "MAX_OUTPUT_SIZE_BYTES": "10485760",  # 10MB default (10 * 1024 * 1024)
                "MAX_RECURSION_DEPTH": "50",  # Maximum recursion depth for nested runbook execution
            }

            self.config_booleans = {
                "ENABLE_LOGIN": "false"
            }            

            self.config_string_secrets = {  
                "JWT_SECRET": "dev-secret-change-me"
            }
            
            # Initialize configuration
            self.initialize()
            self.configure_logging()

    def initialize(self):
        """
        Initialize or re-initialize all configuration values.
        
        This method loads configuration values from environment variables
        or defaults and sets them as instance attributes.
        It also resets the config_items list.
        
        The method processes configuration in the following order:
        1. String configurations
        2. Integer configurations (converted to int)
        3. Boolean configurations (converted from "true"/"false" strings)
        4. String secret configurations
        
        Each configuration value is tracked in config_items with its source
        (environment, or default) and value (secrets are masked).
        """
        self.config_items = []

        # Initialize Config Strings
        for key, default in self.config_strings.items():
            value = self._get_config_value(key, default, False)
            setattr(self, key, value)
            
        # Initialize Config Integers
        for key, default in self.config_ints.items():
            value = int(self._get_config_value(key, default, False))
            setattr(self, key, value)
            
        # Initialize Config Booleans
        for key, default in self.config_booleans.items():
            value = (self._get_config_value(key, default, False)).lower() == "true"
            setattr(self, key, value)
            
        # Initialize String Secrets
        for key, default in self.config_string_secrets.items():
            value = self._get_config_value(key, default, True)
            setattr(self, key, value)

        # Config validation (required values, paths, etc.)
        self._validate_config()

        return

    def _validate_config(self):
        """Validate required config: JWT_SECRET must be set; MOUNT_DIR and EXECUTION_DIR must be valid."""
        default_jwt_secret = self.config_string_secrets.get("JWT_SECRET", "dev-secret-change-me")
        if self.JWT_SECRET == default_jwt_secret:
            error_msg = (
                "JWT_SECRET must be explicitly set. Using the default value is not allowed for security reasons. "
                "Please set JWT_SECRET environment variable to a secure random value."
            )
            logger.error(error_msg)
            raise ValueError(error_msg)

        # EXECUTION_DIR (container path) and MOUNT_DIR (host path). Image has read-only EXECUTION_DIR until mount.
        default_mount_dir = self.config_strings.get("MOUNT_DIR", "")
        if self.MOUNT_DIR == default_mount_dir:
            raise ValueError(
                "MOUNT_DIR is not set. Set MOUNT_DIR to the host path mounted at EXECUTION_DIR "
                f"(e.g. export MOUNT_DIR=$(pwd)/execution and -v \"$MOUNT_DIR:{self.EXECUTION_DIR}\")."
            )
        exec_path = Path(self.EXECUTION_DIR).resolve()
        if not exec_path.exists():
            raise ValueError(
                f"{self.EXECUTION_DIR} does not exist. Mount the host path at EXECUTION_DIR "
                f"(e.g. -v \"$MOUNT_DIR:{self.EXECUTION_DIR}\")."
            )
        if not exec_path.is_dir():
            raise ValueError(f"{self.EXECUTION_DIR} is not a directory.")
        if not os.access(exec_path, os.W_OK):
            raise ValueError(
                f"{self.EXECUTION_DIR} is not writable. Mount a volume over it "
                f"(e.g. -v \"$MOUNT_DIR:{self.EXECUTION_DIR}\")."
            )
        logger.info("Execution directory: MOUNT_DIR=%s mounted at EXECUTION_DIR=%s", self.MOUNT_DIR, self.EXECUTION_DIR)

    def configure_logging(self):
        """
        Configure Python logging based on the LOGGING_LEVEL configuration.
        
        This method is called once during Config singleton initialization to set up
        Python logging with the configured level and format. It uses force=True to
        ensure logging is properly configured even if handlers already exist.
        
        The logging format includes timestamp, level, logger name, and message.
        Werkzeug request logs are suppressed to WARNING level to reduce noise.
        """
        # Convert LOGGING_LEVEL string (from config) to logging constant
        logging_level = getattr(logging, (self.LOGGING_LEVEL).upper(), logging.INFO)
        self.LOGGING_LEVEL = logging_level
        
        # Configure logging with force=True to reconfigure even if handlers exist
        # (e.g., if Flask/Werkzeug has already configured handlers). Project requires Python 3.12+.
        logging.basicConfig(
            level=logging_level,
            format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            force=True
        )

        # Ensure root logger level is set (child loggers inherit this)
        logging.root.setLevel(logging_level)

        # Suppress noisy HTTP-related loggers
        logging.getLogger("httpcore").setLevel(logging.WARNING)  
        logging.getLogger("httpx").setLevel(logging.WARNING)  

        # Suppress Werkzeug request logs (set to WARNING to reduce noise)
        werkzeug_logger = logging.getLogger("werkzeug")
        werkzeug_logger.setLevel(logging.WARNING)
        werkzeug_logger.propagate = True
        
        # Configure Flask's logger
        flask_logger = logging.getLogger("flask.app")
        flask_logger.setLevel(logging_level)
        flask_logger.propagate = True

        # Log configuration initialization
        logger.info(f"Configuration Initialized: {self.config_items}")
        
        return
            
    def _get_config_value(self, name, default_value, is_secret):
        """
        Retrieve a configuration value using the priority system.
        
        Configuration sources are checked in this order:
        1. Environment variable: {name}
        2. Default value: {default_value}
        
        Args:
            name (str): The name of the configuration key.
            default_value (str): The default value to use if not found in env.
            is_secret (bool): If True, the value will be masked as "secret" in
                config_items tracking.
        
        Returns:
            str: The configuration value as a string (may need type conversion
                by the caller).
        
        Note:
            The source and value (masked if secret) are recorded in config_items
            for tracking and debugging purposes.
        """
        value = default_value
        from_source = "default"

        # Check for environment variable
        if os.getenv(name):
            value = os.getenv(name)
            from_source = "environment"

        # Record the source of the config value
        self.config_items.append({
            "name": name,
            "value": "secret" if is_secret else value,
            "from": from_source
        })
        return value
    
    def check_var(self, name: str, required: bool = True) -> str:
        """
        Check if an environment variable is set and optionally required.
        
        Args:
            name: The name of the environment variable
            required: If True, raises ValueError if variable is not set
        
        Returns:
            str: The value of the environment variable (empty string if not set and not required)
            
        Raises:
            ValueError: If required=True and variable is not set
        """
        value = os.getenv(name)
        if required and (value is None or value == ""):
            raise ValueError(f"Required environment variable {name} is not set")
        return value or ""
    
    def to_dict(self, token):
        """
        Convert the Config object to a dictionary for JSON serialization.
        
        This method is typically used to expose configuration via API endpoints.
        Secret values in config_items are already masked (showing "secret" instead
        of actual values).
        
        Args:
            token (dict): Authentication/authorization token to include in the response.
        
        Returns:
            dict: A dictionary containing:
                - config_items (list): List of configuration items with source tracking
                - token (dict): The provided token
        """
        return {
            "config_items": self.config_items,
            "token": token
        }    

    def get_default(self, name: str):
        """
        Get the default value for a configuration key.
        
        Args:
            name: The name of the configuration key
            
        Returns:
            The default value for the key, or None if not found
        """
        # Check config_ints
        if name in self.config_ints:
            return int(self.config_ints[name])
        # Check config_strings
        if name in self.config_strings:
            return self.config_strings[name]
        # Check config_booleans
        if name in self.config_booleans:
            return self.config_booleans[name].lower() == "true"
        # Check config_string_secrets
        if name in self.config_string_secrets:
            return self.config_string_secrets[name]
        return None

    @staticmethod
    def get_instance():
        """
        Get the singleton instance of the Config class.
        
        This is the preferred way to access the Config instance. If no instance
        exists, one will be created automatically.
        
        Returns:
            Config: The singleton Config instance.
        
        Example:
            >>> config = Config.get_instance()
            >>> port = config.API_PORT
        """
        if Config._instance is None:
            Config()
            
        return Config._instance

