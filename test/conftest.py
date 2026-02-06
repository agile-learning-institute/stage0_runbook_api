#!/usr/bin/env python3
"""
Pytest configuration and shared fixtures.

This file is automatically loaded by pytest before any test modules are imported.
It ensures JWT_SECRET and MOUNT_DIR/EXECUTION_DIR are set before any Config initialization.
"""
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

# Set JWT_SECRET before any test modules are imported
if 'JWT_SECRET' not in os.environ:
    os.environ['JWT_SECRET'] = 'test-secret-for-pytest-discovery'

# Set MOUNT_DIR and EXECUTION_DIR so Config validation passes (e.g. when integration tests import create_app)
if 'MOUNT_DIR' not in os.environ:
    _execution_tmp = tempfile.mkdtemp()
    os.environ['MOUNT_DIR'] = _execution_tmp
    os.environ['EXECUTION_DIR'] = _execution_tmp


@pytest.fixture(autouse=True)
def _config_execution_validation_passes(request):
    """Make EXECUTION_DIR/MOUNT_DIR validation pass for unit tests that do not assert on it."""
    if request.node.cls and request.node.cls.__name__ == "TestConfigExecutionDir":
        yield
        return
    # Unit tests: mock Path so validation passes without a real EXECUTION_DIR
    os.environ.setdefault("MOUNT_DIR", "/test-mount")
    resolved = MagicMock()
    resolved.exists.return_value = True
    resolved.is_dir.return_value = True
    resolved.resolve.return_value = resolved
    mock_path = MagicMock(return_value=resolved)
    with patch("src.config.config.Path", mock_path):
        with patch("src.config.config.os.access", return_value=True):
            yield
