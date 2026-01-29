"""Tests for src/config_helper.py — ConfigHelper methods."""

import os
from unittest.mock import patch

import pytest

from config_helper import ConfigHelper


# ──────────────────────────────────────────────────────────────────────────────
# get_secure_value
# ──────────────────────────────────────────────────────────────────────────────

class TestGetSecureValue:

    def test_env_var_highest_priority(self, monkeypatch, mock_logger):
        monkeypatch.setenv("MY_KEY", "from_env")
        ch = ConfigHelper(logger=mock_logger)
        result = ch.get_secure_value("MY_KEY", config_value="from_config", default="from_default")
        assert result == "from_env"

    def test_config_value_fallback(self, monkeypatch, mock_logger):
        monkeypatch.delenv("MY_KEY", raising=False)
        ch = ConfigHelper(logger=mock_logger)
        result = ch.get_secure_value("MY_KEY", config_value="from_config", default="from_default")
        assert result == "from_config"

    def test_default_fallback(self, monkeypatch, mock_logger):
        monkeypatch.delenv("MY_KEY", raising=False)
        ch = ConfigHelper(logger=mock_logger)
        result = ch.get_secure_value("MY_KEY", default="from_default")
        assert result == "from_default"

    def test_none_when_optional_missing(self, monkeypatch, mock_logger):
        monkeypatch.delenv("MY_KEY", raising=False)
        ch = ConfigHelper(logger=mock_logger)
        result = ch.get_secure_value("MY_KEY")
        assert result is None

    def test_raises_when_required_and_missing_noninteractive(self, monkeypatch, mock_logger):
        monkeypatch.delenv("REQ_KEY", raising=False)
        ch = ConfigHelper(logger=mock_logger)
        ch.interactive_mode = False
        with pytest.raises(ValueError, match="Required configuration"):
            ch.get_secure_value("REQ_KEY", required=True)

    def test_env_var_expansion_in_config_value(self, monkeypatch, mock_logger):
        monkeypatch.delenv("MY_KEY", raising=False)
        monkeypatch.setenv("INNER_VAR", "expanded_value")
        ch = ConfigHelper(logger=mock_logger)
        result = ch.get_secure_value("MY_KEY", config_value="${INNER_VAR}")
        assert result == "expanded_value"

    def test_env_var_expansion_missing_required(self, monkeypatch, mock_logger):
        """When config_value is ${VAR} but VAR is not set and key is required, log a warning."""
        monkeypatch.delenv("MY_KEY", raising=False)
        monkeypatch.delenv("MISSING_VAR", raising=False)
        ch = ConfigHelper(logger=mock_logger)
        ch.interactive_mode = False
        # With required=True and missing env var expansion, it should eventually raise
        with pytest.raises(ValueError):
            ch.get_secure_value("MY_KEY", config_value="${MISSING_VAR}", required=True)

    @patch("builtins.input", return_value="typed_value")
    def test_interactive_prompt(self, mock_input, monkeypatch, mock_logger):
        monkeypatch.delenv("MY_KEY", raising=False)
        ch = ConfigHelper(logger=mock_logger)
        ch.interactive_mode = True
        result = ch.get_secure_value("MY_KEY", required=True, description="test value")
        assert result == "typed_value"

    @patch("config_helper.getpass.getpass", return_value="secret_pw")
    def test_getpass_for_passwords(self, mock_getpass, monkeypatch, mock_logger):
        monkeypatch.delenv("MY_KEY", raising=False)
        ch = ConfigHelper(logger=mock_logger)
        ch.interactive_mode = True
        result = ch.get_secure_value("MY_KEY", required=True, is_password=True)
        assert result == "secret_pw"

    @patch("builtins.input", side_effect=KeyboardInterrupt)
    def test_keyboard_interrupt_handling(self, mock_input, monkeypatch, mock_logger):
        monkeypatch.delenv("MY_KEY", raising=False)
        ch = ConfigHelper(logger=mock_logger)
        ch.interactive_mode = True
        # KeyboardInterrupt during prompt falls through to default/None
        result = ch.get_secure_value("MY_KEY", default="fallback")
        assert result == "fallback"

    @patch("builtins.input", side_effect=EOFError)
    def test_eoferror_handling(self, mock_input, monkeypatch, mock_logger):
        monkeypatch.delenv("MY_KEY", raising=False)
        ch = ConfigHelper(logger=mock_logger)
        ch.interactive_mode = True
        result = ch.get_secure_value("MY_KEY", default="fallback")
        assert result == "fallback"

    def test_config_value_zero_is_valid(self, monkeypatch, mock_logger):
        """config_value=0 should be returned (not None-skipped)."""
        monkeypatch.delenv("MY_KEY", raising=False)
        ch = ConfigHelper(logger=mock_logger)
        result = ch.get_secure_value("MY_KEY", config_value=0, default=99)
        assert result == 0


# ──────────────────────────────────────────────────────────────────────────────
# expand_config_variables
# ──────────────────────────────────────────────────────────────────────────────

class TestExpandConfigVariables:

    def test_simple_var(self, monkeypatch, mock_logger):
        monkeypatch.setenv("HOST", "1.2.3.4")
        ch = ConfigHelper(logger=mock_logger)
        assert ch.expand_config_variables("rtsp://${HOST}/stream") == "rtsp://1.2.3.4/stream"

    def test_default_value_used(self, monkeypatch, mock_logger):
        monkeypatch.delenv("MISS", raising=False)
        ch = ConfigHelper(logger=mock_logger)
        assert ch.expand_config_variables("${MISS:-fallback}") == "fallback"

    def test_default_value_with_var_set(self, monkeypatch, mock_logger):
        monkeypatch.setenv("EXIST", "val")
        ch = ConfigHelper(logger=mock_logger)
        assert ch.expand_config_variables("${EXIST:-fallback}") == "val"

    def test_missing_var_returns_literal(self, monkeypatch, mock_logger):
        monkeypatch.delenv("NOPE", raising=False)
        ch = ConfigHelper(logger=mock_logger)
        assert ch.expand_config_variables("${NOPE}") == "${NOPE}"

    def test_nested_dicts(self, monkeypatch, mock_logger):
        monkeypatch.setenv("INNER", "deep")
        ch = ConfigHelper(logger=mock_logger)
        result = ch.expand_config_variables({"a": {"b": "${INNER}"}})
        assert result == {"a": {"b": "deep"}}

    def test_lists(self, monkeypatch, mock_logger):
        monkeypatch.setenv("ITEM", "x")
        ch = ConfigHelper(logger=mock_logger)
        result = ch.expand_config_variables(["${ITEM}", "literal"])
        assert result == ["x", "literal"]

    def test_non_string_passthrough(self, mock_logger):
        ch = ConfigHelper(logger=mock_logger)
        assert ch.expand_config_variables(42) == 42
        assert ch.expand_config_variables(None) is None
        assert ch.expand_config_variables(True) is True

    def test_multiple_vars_in_one_string(self, monkeypatch, mock_logger):
        monkeypatch.setenv("USER", "admin")
        monkeypatch.setenv("PASS", "pw")
        ch = ConfigHelper(logger=mock_logger)
        result = ch.expand_config_variables("rtsp://${USER}:${PASS}@host")
        assert result == "rtsp://admin:pw@host"


# ──────────────────────────────────────────────────────────────────────────────
# load_env_file
# ──────────────────────────────────────────────────────────────────────────────

class TestLoadEnvFile:

    def test_basic_key_value(self, tmp_path, monkeypatch, mock_logger):
        env = tmp_path / ".env"
        env.write_text("FOO=bar\n")
        ch = ConfigHelper(logger=mock_logger)
        result = ch.load_env_file(str(env))
        assert result == {"FOO": "bar"}
        assert os.environ.get("FOO") == "bar"
        monkeypatch.delenv("FOO", raising=False)

    def test_strips_quotes(self, tmp_path, monkeypatch, mock_logger):
        env = tmp_path / ".env"
        env.write_text('QUOTED="hello world"\nSINGLE=\'val\'\n')
        ch = ConfigHelper(logger=mock_logger)
        result = ch.load_env_file(str(env))
        assert result["QUOTED"] == "hello world"
        assert result["SINGLE"] == "val"
        monkeypatch.delenv("QUOTED", raising=False)
        monkeypatch.delenv("SINGLE", raising=False)

    def test_skips_comments_and_blanks(self, tmp_path, monkeypatch, mock_logger):
        env = tmp_path / ".env"
        env.write_text("# comment\n\nKEY=val\n")
        ch = ConfigHelper(logger=mock_logger)
        result = ch.load_env_file(str(env))
        assert result == {"KEY": "val"}
        monkeypatch.delenv("KEY", raising=False)

    def test_file_not_found(self, mock_logger):
        ch = ConfigHelper(logger=mock_logger)
        result = ch.load_env_file("/nonexistent/.env")
        assert result == {}

    def test_invalid_lines_logged(self, tmp_path, mock_logger):
        env = tmp_path / ".env"
        env.write_text("NO_EQUALS_HERE\n")
        ch = ConfigHelper(logger=mock_logger)
        ch.load_env_file(str(env))
        warnings = [r for r in mock_logger._test_handler.records if r.levelno == 30]
        assert len(warnings) == 1

    def test_value_with_equals(self, tmp_path, monkeypatch, mock_logger):
        """Values can contain '=' signs."""
        env = tmp_path / ".env"
        env.write_text("CONN=host=db;port=5432\n")
        ch = ConfigHelper(logger=mock_logger)
        result = ch.load_env_file(str(env))
        assert result["CONN"] == "host=db;port=5432"
        monkeypatch.delenv("CONN", raising=False)


# ──────────────────────────────────────────────────────────────────────────────
# validate_required_vars
# ──────────────────────────────────────────────────────────────────────────────

class TestValidateRequiredVars:

    def test_all_present(self, monkeypatch, mock_logger):
        monkeypatch.setenv("A", "1")
        monkeypatch.setenv("B", "2")
        ch = ConfigHelper(logger=mock_logger)
        assert ch.validate_required_vars({"A": "first", "B": "second"}) is True

    def test_missing_returns_false(self, monkeypatch, mock_logger):
        monkeypatch.delenv("MISSING_X", raising=False)
        ch = ConfigHelper(logger=mock_logger)
        assert ch.validate_required_vars({"MISSING_X": "needed"}) is False
