"""Tests for CallLogParser line filtering (pass 1)."""

import os
import sys
import importlib
import importlib.util
import tempfile

import pytest

# Import directly from the module file to avoid circular import
# that exists in log_analyzer.apps.__init__.py
_module_path = os.path.join(
    os.path.dirname(__file__), "..", "log_analyzer", "apps", "call_parser.py"
)
_spec = importlib.util.spec_from_file_location(
    "log_analyzer.apps.call_parser", _module_path
)
_call_parser = importlib.util.module_from_spec(_spec)
sys.modules["log_analyzer.apps.call_parser"] = _call_parser
_spec.loader.exec_module(_call_parser)
CallLogParser = _call_parser.CallLogParser


class TestCallLogParserInit:
    """Tests for CallLogParser.__init__ and file discovery."""

    def test_discovers_log_files_in_directory(self, tmp_path):
        """Parser discovers .log files in the given directory."""
        (tmp_path / "app.log").write_text("line1\nline2\n")
        (tmp_path / "other.log").write_text("line3\n")
        (tmp_path / "readme.txt").write_text("not a log\n")

        parser = CallLogParser(str(tmp_path))

        assert len(parser._log_files) == 2
        assert all(f.endswith(".log") for f in parser._log_files)

    def test_discovers_olos_ai_orchestrator_files(self, tmp_path):
        """Parser discovers files with 'olos-ai-orchestrator' in the name."""
        (tmp_path / "olos-ai-orchestrator-2024-01-01").write_text("data\n")
        (tmp_path / "unrelated.txt").write_text("not a log\n")

        parser = CallLogParser(str(tmp_path))

        assert len(parser._log_files) == 1
        assert "olos-ai-orchestrator" in parser._log_files[0]

    def test_includes_gz_files(self, tmp_path):
        """Parser includes .gz compressed files (gzip support)."""
        (tmp_path / "olos-ai-orchestrator-2024.gz").write_text("compressed\n")
        (tmp_path / "app.log").write_text("line\n")

        parser = CallLogParser(str(tmp_path))

        assert len(parser._log_files) == 2
        basenames = [os.path.basename(f) for f in parser._log_files]
        assert "olos-ai-orchestrator-2024.gz" in basenames
        assert "app.log" in basenames

    def test_nonexistent_directory_returns_empty(self, tmp_path):
        """Parser handles missing directory gracefully."""
        parser = CallLogParser(str(tmp_path / "nonexistent"))

        assert parser._log_files == []

    def test_files_sorted_reverse(self, tmp_path):
        """Discovered files are sorted in reverse order (newest first)."""
        (tmp_path / "aaa.log").write_text("a\n")
        (tmp_path / "zzz.log").write_text("z\n")

        parser = CallLogParser(str(tmp_path))

        assert "zzz.log" in parser._log_files[0]
        assert "aaa.log" in parser._log_files[1]


class TestFilterLines:
    """Tests for CallLogParser._filter_lines (pass 1 filtering)."""

    def test_returns_only_matching_lines(self, tmp_path):
        """Only lines containing the CallId are returned."""
        log_content = (
            "2024-01-01 INFO CallId=abc123 Starting session\n"
            "2024-01-01 INFO General system log\n"
            "2024-01-01 ERROR CallId=abc123 Something failed\n"
            "2024-01-01 DEBUG CallId=xyz789 Other call\n"
        )
        log_file = tmp_path / "test.log"
        log_file.write_text(log_content)

        parser = CallLogParser(str(tmp_path))
        result = parser._filter_lines("abc123", str(log_file))

        assert len(result) == 2
        assert all("abc123" in line for line in result)
        assert "General system log" not in "\n".join(result)
        assert "xyz789" not in "\n".join(result)

    def test_returns_empty_for_no_matches(self, tmp_path):
        """Returns empty list when no lines match the CallId."""
        log_file = tmp_path / "test.log"
        log_file.write_text("line without any call id\nanother line\n")

        parser = CallLogParser(str(tmp_path))
        result = parser._filter_lines("nonexistent-id", str(log_file))

        assert result == []

    def test_handles_missing_file_gracefully(self, tmp_path):
        """Returns empty list for missing file without raising exception."""
        parser = CallLogParser(str(tmp_path))
        result = parser._filter_lines("abc123", str(tmp_path / "missing.log"))

        assert result == []

    def test_strips_trailing_newlines(self, tmp_path):
        """Returned lines have trailing newlines/carriage returns stripped."""
        log_file = tmp_path / "test.log"
        log_file.write_text("CallId=abc123 first line\r\nCallId=abc123 second line\n")

        parser = CallLogParser(str(tmp_path))
        result = parser._filter_lines("abc123", str(log_file))

        for line in result:
            assert not line.endswith('\n')
            assert not line.endswith('\r')

    def test_handles_file_with_encoding_errors(self, tmp_path):
        """Files with encoding errors are read using replacement characters."""
        log_file = tmp_path / "test.log"
        # Write binary content that includes invalid UTF-8 and the CallId
        content = b"CallId=abc123 valid line\n\xff\xfe invalid bytes CallId=abc123\n"
        log_file.write_bytes(content)

        parser = CallLogParser(str(tmp_path))
        result = parser._filter_lines("abc123", str(log_file))

        assert len(result) == 2
        assert all("abc123" in line for line in result)

    def test_case_sensitive_matching(self, tmp_path):
        """Filter is case-sensitive (exact string match)."""
        log_file = tmp_path / "test.log"
        log_file.write_text("CallId=ABC123 upper\nCallId=abc123 lower\n")

        parser = CallLogParser(str(tmp_path))
        result = parser._filter_lines("abc123", str(log_file))

        assert len(result) == 1
        assert "lower" in result[0]
