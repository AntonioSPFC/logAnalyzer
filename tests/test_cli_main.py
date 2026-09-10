"""Tests for the CLI entry point (log_analyzer.cli.main).

Verifies that:
- The main function can be imported
- Shows usage and exits with code 1 when insufficient arguments are provided
- Handles ErroDeIdentificador correctly (exit code 1 + stderr message)
- Parses app_id:caminho arguments correctly
- Handles arguments without app_id (no colon) as app_id=None
"""

import sys
from unittest.mock import patch

import pytest

from log_analyzer.cli.main import main


class TestMainImport:
    """Verify main function exists and is importable."""

    def test_main_is_callable(self):
        assert callable(main)

    def test_main_importable_from_cli_package(self):
        from log_analyzer.cli import main as main_from_pkg
        assert callable(main_from_pkg)


class TestMainUsage:
    """Verify usage message and exit behavior."""

    def test_exits_with_code_1_when_no_args(self, capsys):
        with patch.object(sys, "argv", ["log_analyzer"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Uso:" in captured.out

    def test_exits_with_code_1_when_only_identifier(self, capsys):
        with patch.object(sys, "argv", ["log_analyzer", "my-id"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Uso:" in captured.out


class TestMainInvalidIdentifier:
    """Verify that invalid identifiers produce error on stderr and exit 1."""

    def test_empty_identifier_exits_with_error(self, capsys):
        with patch.object(sys, "argv", ["log_analyzer", "", "VPL:dummy.log"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Erro:" in captured.err

    def test_whitespace_identifier_exits_with_error(self, capsys):
        with patch.object(sys, "argv", ["log_analyzer", "   ", "VPL:dummy.log"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Erro:" in captured.err


class TestMainArgumentParsing:
    """Verify correct parsing of file selection arguments."""

    def test_parses_app_id_and_path(self, capsys, tmp_path):
        # Create a dummy log file
        log_file = tmp_path / "test.log"
        log_file.write_text(
            "2024-01-01 10:00:00.000 [INFO] modulo.c:1 "
            "evento test-id\n"
        )

        with patch.object(
            sys, "argv", ["log_analyzer", "test-id", f"VPL:{log_file}"]
        ):
            # Should not raise (might not find anything, but won't crash)
            main()

        captured = capsys.readouterr()
        assert "Resultado da análise para:" in captured.out
        assert "test-id" not in captured.out + captured.err
        assert str(log_file) not in captured.out + captured.err

    def test_parses_arg_without_colon_as_no_app_id(self, capsys, tmp_path):
        log_file = tmp_path / "test.log"
        log_file.write_text("some log line\n")

        with patch.object(
            sys, "argv", ["log_analyzer", "search-term", str(log_file)]
        ):
            main()

        captured = capsys.readouterr()
        # A associação sem app_id permanece aceita, mas a saída é sanitizada.
        assert "Resultado da análise para:" in captured.out
        assert "search-term" not in captured.out + captured.err
        assert str(log_file) not in captured.out + captured.err
