"""Tests for the configuration validation in config.py."""

import importlib
import os
import sys

import pytest


class TestRequireEnvVar:
    """Tests for the _require_env_var validation function."""

    def test_missing_env_var_raises_configuration_error(self, monkeypatch):
        """ConfigurationError is raised when a required env var is not set."""
        # Remove LLM_API_KEY if it exists
        monkeypatch.delenv("LLM_API_KEY", raising=False)

        # Need to import ConfigurationError and _require_env_var without
        # triggering module-level validation. We do this by importing directly
        # from a fresh reload.

        # First, ensure the module isn't already loaded with old values
        if "backend.config" in sys.modules:
            # Save the current module state
            old_module = sys.modules.pop("backend.config")

        try:
            # Import the exception class and function for testing
            # by patching os.getenv to return a valid key during import
            monkeypatch.setenv("LLM_API_KEY", "test-key-for-import")
            from backend.config import ConfigurationError, _require_env_var

            # Now test the function directly with an unset variable
            # Use a different variable name to avoid module-level validation
            monkeypatch.delenv("TEST_MISSING_VAR", raising=False)

            with pytest.raises(ConfigurationError) as exc_info:
                _require_env_var("TEST_MISSING_VAR")

            assert "TEST_MISSING_VAR" in str(exc_info.value)
            assert "not set" in str(exc_info.value)

        finally:
            # Restore the old module if it existed
            if "old_module" in dir() and old_module is not None:
                sys.modules["backend.config"] = old_module

    def test_empty_string_env_var_raises_configuration_error(self, monkeypatch):
        """ConfigurationError is raised when env var is set to empty string."""
        # Set up for import
        monkeypatch.setenv("LLM_API_KEY", "test-key-for-import")

        if "backend.config" in sys.modules:
            old_module = sys.modules.pop("backend.config")

        try:
            from backend.config import ConfigurationError, _require_env_var

            # Test with empty string
            monkeypatch.setenv("TEST_EMPTY_VAR", "")

            with pytest.raises(ConfigurationError) as exc_info:
                _require_env_var("TEST_EMPTY_VAR")

            assert "TEST_EMPTY_VAR" in str(exc_info.value)
            assert "not set" in str(exc_info.value)

        finally:
            if "old_module" in dir() and old_module is not None:
                sys.modules["backend.config"] = old_module

    def test_whitespace_only_env_var_raises_configuration_error(self, monkeypatch):
        """ConfigurationError is raised when env var contains only whitespace."""
        monkeypatch.setenv("LLM_API_KEY", "test-key-for-import")

        if "backend.config" in sys.modules:
            old_module = sys.modules.pop("backend.config")

        try:
            from backend.config import ConfigurationError, _require_env_var

            # Test with whitespace only
            monkeypatch.setenv("TEST_WHITESPACE_VAR", "   ")

            with pytest.raises(ConfigurationError) as exc_info:
                _require_env_var("TEST_WHITESPACE_VAR")

            assert "TEST_WHITESPACE_VAR" in str(exc_info.value)

        finally:
            if "old_module" in dir() and old_module is not None:
                sys.modules["backend.config"] = old_module

    def test_error_message_includes_description(self, monkeypatch):
        """ConfigurationError message includes the description when provided."""
        monkeypatch.setenv("LLM_API_KEY", "test-key-for-import")

        if "backend.config" in sys.modules:
            old_module = sys.modules.pop("backend.config")

        try:
            from backend.config import ConfigurationError, _require_env_var

            monkeypatch.delenv("TEST_VAR_WITH_DESC", raising=False)

            with pytest.raises(ConfigurationError) as exc_info:
                _require_env_var("TEST_VAR_WITH_DESC", "My custom description")

            assert "My custom description" in str(exc_info.value)

        finally:
            if "old_module" in dir() and old_module is not None:
                sys.modules["backend.config"] = old_module

    def test_error_message_includes_fix_instructions(self, monkeypatch):
        """ConfigurationError message includes helpful fix instructions."""
        monkeypatch.setenv("LLM_API_KEY", "test-key-for-import")

        if "backend.config" in sys.modules:
            old_module = sys.modules.pop("backend.config")

        try:
            from backend.config import ConfigurationError, _require_env_var

            monkeypatch.delenv("MY_API_KEY", raising=False)

            with pytest.raises(ConfigurationError) as exc_info:
                _require_env_var("MY_API_KEY")

            error_msg = str(exc_info.value)
            assert "To fix this" in error_msg
            assert ".env" in error_msg
            assert "MY_API_KEY" in error_msg

        finally:
            if "old_module" in dir() and old_module is not None:
                sys.modules["backend.config"] = old_module


class TestLLMApiKeyValidation:
    """Tests for module-level LLM_API_KEY validation."""

    def test_missing_llm_api_key_raises_configuration_error(self, monkeypatch):
        """Importing config module raises ConfigurationError when LLM_API_KEY is not set."""
        # Remove the module from cache to force reimport
        if "backend.config" in sys.modules:
            del sys.modules["backend.config"]

        # Remove the env var
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

        # Attempt to import - this should raise ConfigurationError
        # We catch Exception and verify it's the right type since the class
        # is defined in the module that fails to load
        with pytest.raises(Exception) as exc_info:
            import backend.config  # noqa: F401

        # Verify it's a ConfigurationError by checking type name and message
        assert exc_info.type.__name__ == "ConfigurationError"
        error_msg = str(exc_info.value)
        assert "LLM_API_KEY" in error_msg
        assert "API key for LLM service" in error_msg
        assert "not set" in error_msg
