"""Tests for cli.py — format functions, commands, main routing.

Enterprise coverage: formatting, command outputs, error handling.
"""

import json
import sys
from io import StringIO
from unittest.mock import patch, MagicMock

import pytest

from cli import (
    fmt_duration,
    fmt_date,
    cmd_search,
    cmd_list,
    cmd_show,
    cmd_actions,
    main,
)


# =============================================================================
# fmt_duration (6 tests)
# =============================================================================


class TestFmtDuration:
    def test_seconds_only(self):
        """< 60s → '0m30s'."""
        assert fmt_duration(30) == "0m30s"

    def test_minutes_and_seconds(self):
        """125s → '2m05s'."""
        assert fmt_duration(125) == "2m05s"

    def test_exact_minute(self):
        """60s → '1m00s'."""
        assert fmt_duration(60) == "1m00s"

    def test_hours_minutes_seconds(self):
        """3661s → '1h01m01s'."""
        assert fmt_duration(3661) == "1h01m01s"

    def test_exact_hour(self):
        """3600s → '1h00m00s'."""
        assert fmt_duration(3600) == "1h00m00s"

    def test_zero(self):
        """0s → '0m00s'."""
        assert fmt_duration(0) == "0m00s"


# =============================================================================
# fmt_date (4 tests)
# =============================================================================


class TestFmtDate:
    def test_valid_iso(self):
        """Valid ISO date → formatted string."""
        result = fmt_date("2025-02-20T10:30:00")
        assert "2025" in result
        assert "02" in result or "Feb" in result

    def test_invalid_string(self):
        """Invalid date string → returned as-is."""
        result = fmt_date("not-a-date")
        assert result == "not-a-date"

    def test_none_returns_question_mark(self):
        """None → '?'."""
        assert fmt_date(None) == "?"

    def test_empty_string(self):
        """Empty string → '?'."""
        assert fmt_date("") == "?"


# =============================================================================
# cmd_search (3 tests)
# =============================================================================


class TestCmdSearch:
    def test_search_no_args_exits(self):
        """No search args → sys.exit(1)."""
        db = MagicMock()
        with pytest.raises(SystemExit) as exc_info:
            cmd_search(db, [])
        assert exc_info.value.code == 1

    def test_search_with_results(self, capsys, populated_db):
        """Search with results prints them."""
        cmd_search(populated_db, ["deployment"])
        output = capsys.readouterr().out
        assert "1 result" in output
        assert "20250220_140000" in output

    def test_search_no_results(self, capsys, populated_db):
        """Search with no results prints message."""
        cmd_search(populated_db, ["xyznonexistent"])
        output = capsys.readouterr().out
        assert "No results" in output


# =============================================================================
# cmd_list (2 tests)
# =============================================================================


class TestCmdList:
    def test_list_with_calls(self, capsys, populated_db):
        """Lists calls with header and rows."""
        cmd_list(populated_db, [])
        output = capsys.readouterr().out
        assert "Session ID" in output
        assert "20250220_100000" in output
        assert "Zoom" in output

    def test_list_empty_db(self, capsys, tmp_db):
        """Empty DB prints 'No calls'."""
        cmd_list(tmp_db, [])
        output = capsys.readouterr().out
        assert "No calls" in output


# =============================================================================
# cmd_show (2 tests)
# =============================================================================


class TestCmdShow:
    def test_show_existing_call(self, capsys, populated_db):
        """Show existing call prints all details."""
        cmd_show(populated_db, ["20250220_100000"])
        output = capsys.readouterr().out
        assert "Zoom" in output
        assert "SUMMARY" in output
        assert "TRANSCRIPT" in output

    def test_show_nonexistent_exits(self, populated_db):
        """Show nonexistent call → sys.exit(1)."""
        with pytest.raises(SystemExit) as exc_info:
            cmd_show(populated_db, ["nonexistent"])
        assert exc_info.value.code == 1


# =============================================================================
# cmd_actions (2 tests)
# =============================================================================


class TestCmdActions:
    def test_actions_with_items(self, capsys, populated_db):
        """Shows action items from calls."""
        cmd_actions(populated_db, ["365"])
        output = capsys.readouterr().out
        assert "Написать ТЗ" in output

    def test_actions_empty(self, capsys, tmp_db):
        """No action items prints message."""
        cmd_actions(tmp_db, [])
        output = capsys.readouterr().out
        assert "No action items" in output


# =============================================================================
# main() routing (3 tests)
# =============================================================================


class TestMain:
    def test_no_args_shows_help(self):
        """No args → help text + sys.exit(0)."""
        with patch.object(sys, "argv", ["cli.py"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0

    def test_unknown_command_exits(self):
        """Unknown command → sys.exit(1)."""
        with patch.object(sys, "argv", ["cli.py", "unknown"]):
            with patch("cli.Database"):
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 1

    def test_valid_command_routes(self):
        """Valid command routes to handler."""
        mock_db = MagicMock()
        mock_db.list_recent.return_value = []
        with patch.object(sys, "argv", ["cli.py", "list"]):
            with patch("cli.Database", return_value=mock_db):
                main()
                mock_db.list_recent.assert_called_once()
