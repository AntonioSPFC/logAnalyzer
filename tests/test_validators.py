"""Unit tests for dashboard.validators module."""

import pytest

from dashboard.validators import validate_call_id


class TestValidateCallId:
    """Tests for validate_call_id function."""

    def test_valid_lowercase_hex(self):
        """A 16-char lowercase hex string is accepted."""
        is_valid, error = validate_call_id("0018c4102ff2d6c7")
        assert is_valid is True
        assert error is None

    def test_valid_uppercase_hex(self):
        """A 16-char uppercase hex string is accepted."""
        is_valid, error = validate_call_id("0018C4102FF2D6C7")
        assert is_valid is True
        assert error is None

    def test_valid_mixed_case_hex(self):
        """A 16-char mixed-case hex string is accepted."""
        is_valid, error = validate_call_id("0018c4102FF2d6C7")
        assert is_valid is True
        assert error is None

    def test_valid_all_zeros(self):
        """All zeros is a valid CallId."""
        is_valid, error = validate_call_id("0000000000000000")
        assert is_valid is True
        assert error is None

    def test_valid_all_f(self):
        """All f's is a valid CallId."""
        is_valid, error = validate_call_id("ffffffffffffffff")
        assert is_valid is True
        assert error is None

    def test_empty_string_rejected(self):
        """Empty string is rejected with descriptive error."""
        is_valid, error = validate_call_id("")
        assert is_valid is False
        assert "vazio" in error

    def test_whitespace_only_rejected(self):
        """Whitespace-only string is rejected as empty."""
        is_valid, error = validate_call_id("   ")
        assert is_valid is False
        assert "vazio" in error

    def test_too_short_rejected(self):
        """String shorter than 16 characters is rejected."""
        is_valid, error = validate_call_id("0018c4102ff2d6")
        assert is_valid is False
        assert "16 caracteres" in error
        assert "14" in error  # received length

    def test_too_long_rejected(self):
        """String longer than 16 characters is rejected."""
        is_valid, error = validate_call_id("0018c4102ff2d6c7aa")
        assert is_valid is False
        assert "16 caracteres" in error
        assert "18" in error  # received length

    def test_non_hex_characters_rejected(self):
        """String with non-hex characters is rejected."""
        is_valid, error = validate_call_id("0018c4102ff2d6gx")
        assert is_valid is False
        assert "hexadecimais" in error

    def test_special_characters_rejected(self):
        """String with special characters is rejected."""
        is_valid, error = validate_call_id("0018c4102ff2d6-!")
        assert is_valid is False
        assert "hexadecimais" in error

    def test_spaces_in_middle_rejected(self):
        """String with spaces embedded (16 chars total) is rejected."""
        is_valid, error = validate_call_id("0018c410 ff2d6c7")
        assert is_valid is False
        assert "hexadecimais" in error

    def test_leading_trailing_whitespace_trimmed(self):
        """Leading/trailing whitespace is trimmed before validation."""
        is_valid, error = validate_call_id("  0018c4102ff2d6c7  ")
        assert is_valid is True
        assert error is None

    def test_single_character_rejected(self):
        """Single character is rejected for wrong length."""
        is_valid, error = validate_call_id("a")
        assert is_valid is False
        assert "16 caracteres" in error
