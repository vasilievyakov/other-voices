"""Tests for src.meetings — pre-meeting briefs (local Granola-style Briefs).

Covers: calendar-peek output parsing, the 3-12 minute notification window,
the dedup key, note building on populated_db, note writing, and the thin
daemon wrapper _check_meetings with mocked subprocess/notify.
"""

import json
import subprocess
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import src.daemon
import src.meetings
from src.meetings import (
    build_premeeting_note,
    event_key,
    parse_peek_output,
    upcoming_window,
    write_premeeting_note,
)
from tests.conftest import SID1

NOW = datetime(2026, 8, 20, 14, 0, 0)


def _event(start, id="ev1", title="Sync", attendees=("Вася",)):
    return {"id": id, "title": title, "start": start, "attendees": list(attendees)}


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _utc_z(local_naive: datetime) -> str:
    """Render a naive local datetime as the UTC Z-string calendar-peek emits."""
    aware = local_naive.astimezone()  # naive is interpreted as local time
    return aware.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# =============================================================================
# parse_peek_output
# =============================================================================


class TestParsePeekOutput:
    def test_valid_list(self):
        raw = json.dumps(
            [
                {
                    "id": "e1",
                    "title": "Sync",
                    "start": "2026-08-20T14:05:00Z",
                    "attendees": ["Вася"],
                }
            ]
        )
        events = parse_peek_output(raw)
        assert events == [
            {
                "id": "e1",
                "title": "Sync",
                "start": "2026-08-20T14:05:00Z",
                "attendees": ["Вася"],
            }
        ]

    def test_error_dict_returns_none(self):
        assert parse_peek_output('{"error": "no-access"}') is None

    def test_garbage_returns_none(self):
        assert parse_peek_output("swift crashed: fatal error") is None

    def test_empty_string_returns_none(self):
        assert parse_peek_output("") is None
        assert parse_peek_output("   \n") is None

    def test_non_list_json_returns_none(self):
        assert parse_peek_output("42") is None
        assert parse_peek_output('"строка"') is None

    def test_items_missing_required_fields_dropped(self):
        raw = json.dumps(
            [
                {"title": "нет id и start"},
                {"id": "e1", "start": "2026-08-20T14:05:00"},
            ]
        )
        events = parse_peek_output(raw)
        assert len(events) == 1
        assert events[0]["id"] == "e1"

    def test_non_dict_items_dropped(self):
        raw = json.dumps([1, "x", {"id": "e1", "start": "2026-08-20T14:05:00"}])
        events = parse_peek_output(raw)
        assert len(events) == 1

    def test_missing_optional_fields_normalized(self):
        raw = json.dumps([{"id": "e1", "start": "2026-08-20T14:05:00"}])
        events = parse_peek_output(raw)
        assert events[0]["title"] == ""
        assert events[0]["attendees"] == []

    def test_non_string_attendees_dropped(self):
        raw = json.dumps(
            [
                {
                    "id": "e1",
                    "start": "2026-08-20T14:05:00",
                    "attendees": ["Вася", 7, None],
                }
            ]
        )
        events = parse_peek_output(raw)
        assert events[0]["attendees"] == ["Вася"]

    def test_empty_list_is_valid(self):
        assert parse_peek_output("[]") == []


# =============================================================================
# upcoming_window
# =============================================================================


class TestUpcomingWindow:
    def test_event_in_window_included(self):
        ev = _event(_iso(NOW + timedelta(minutes=5)))
        assert upcoming_window([ev], NOW) == [ev]

    def test_too_soon_excluded(self):
        ev = _event(_iso(NOW + timedelta(minutes=2)))
        assert upcoming_window([ev], NOW) == []

    def test_too_far_excluded(self):
        ev = _event(_iso(NOW + timedelta(minutes=13)))
        assert upcoming_window([ev], NOW) == []

    def test_boundaries_inclusive(self):
        early = _event(_iso(NOW + timedelta(minutes=3)), id="a")
        late = _event(_iso(NOW + timedelta(minutes=12)), id="b")
        assert upcoming_window([early, late], NOW) == [early, late]

    def test_past_event_excluded(self):
        ev = _event(_iso(NOW - timedelta(minutes=5)))
        assert upcoming_window([ev], NOW) == []

    def test_bad_start_skipped(self):
        ev = _event("не дата")
        assert upcoming_window([ev], NOW) == []

    def test_utc_z_start_with_naive_now(self):
        """calendar-peek emits UTC Z timestamps; now is naive local."""
        ev = _event(_utc_z(NOW + timedelta(minutes=5)))
        assert upcoming_window([ev], NOW) == [ev]

    def test_custom_lead_params(self):
        ev = _event(_iso(NOW + timedelta(minutes=20)))
        assert upcoming_window([ev], NOW, lead_min=25, min_lead_min=15) == [ev]
        assert upcoming_window([ev], NOW) == []


# =============================================================================
# event_key — dedup helper
# =============================================================================


class TestEventKey:
    def test_same_event_same_key(self):
        a = _event("2026-08-20T14:05:00", id="e1")
        b = _event("2026-08-20T14:05:00", id="e1", title="другое имя")
        assert event_key(a) == event_key(b)

    def test_different_start_different_key(self):
        a = _event("2026-08-20T14:05:00", id="e1")
        b = _event("2026-08-20T15:05:00", id="e1")
        assert event_key(a) != event_key(b)

    def test_different_id_different_key(self):
        a = _event("2026-08-20T14:05:00", id="e1")
        b = _event("2026-08-20T14:05:00", id="e2")
        assert event_key(a) != event_key(b)


# =============================================================================
# build_premeeting_note — on populated_db from conftest
# =============================================================================


def _add_history(db, name="Вася"):
    """Give `name` an entity on SID1 plus one confident debt each way."""
    db.insert_entities(SID1, [{"name": name, "type": "person"}])
    db.insert_commitments(
        SID1,
        [
            {
                "type": "outgoing",
                "who": "SPEAKER_ME",
                "to_whom": name,
                "what": "прислать смету",
                "deadline": "пятница",
                "quote": "пришлю смету в пятницу",
            },
            {
                "type": "incoming",
                "who": name,
                "to_whom": None,
                "what": "прислать бриф",
                "deadline": None,
                "quote": "скину бриф",
            },
        ],
    )


class TestBuildPremeetingNote:
    def test_known_participant_debts_in_note(self, populated_db):
        _add_history(populated_db)
        ev = _event("2026-08-20T15:30:00", title="Sync", attendees=["Вася", "Alice"])
        result = build_premeeting_note(populated_db, ev)
        assert result is not None
        title, body = result
        assert title == "Встреча Sync в 15:30"
        # SID1 is yesterday's call -> «вчера»
        assert "Вася: должен 1 / тебе должны 1, последний разговор вчера" in body
        assert "Alice: истории нет" in body

    def test_no_participants_in_db_gives_note_without_debts(self, populated_db):
        ev = _event("2026-08-20T15:30:00", title="Sync", attendees=["Незнакомец"])
        result = build_premeeting_note(populated_db, ev)
        assert result is not None
        _, body = result
        assert "Незнакомец: истории нет" in body
        assert "должен" not in body

    def test_no_attendees_returns_none(self, populated_db):
        ev = _event("2026-08-20T15:30:00", attendees=[])
        assert build_premeeting_note(populated_db, ev) is None

    def test_bad_start_returns_none(self, populated_db):
        ev = _event("мусор")
        assert build_premeeting_note(populated_db, ev) is None

    def test_empty_title_still_builds(self, populated_db):
        ev = _event("2026-08-20T15:30:00", title="")
        result = build_premeeting_note(populated_db, ev)
        assert result is not None
        title, _ = result
        assert title == "Встреча в 15:30"

    def test_utc_start_rendered_in_local_time(self, populated_db):
        local = datetime(2026, 8, 20, 15, 30, 0)
        ev = _event(_utc_z(local))
        result = build_premeeting_note(populated_db, ev)
        assert result is not None
        title, _ = result
        assert "15:30" in title

    def test_body_starts_with_title_header(self, populated_db):
        ev = _event("2026-08-20T15:30:00", title="Sync")
        _, body = build_premeeting_note(populated_db, ev)
        assert body.startswith("# Встреча Sync в 15:30")


# =============================================================================
# write_premeeting_note
# =============================================================================


class TestWritePremeetingNote:
    def test_writes_file_with_date_and_slug(self, populated_db, tmp_path, monkeypatch):
        monkeypatch.setattr(src.meetings, "DIGESTS_DIR", tmp_path)
        _add_history(populated_db)
        ev = _event("2026-08-20T15:30:00", title="Sync Альфа", attendees=["Вася"])
        result = write_premeeting_note(populated_db, ev)
        assert result is not None
        path, title = result
        assert path == str(tmp_path / "premeet-2026-08-20-sync-альфа.md")
        assert title == "Встреча Sync Альфа в 15:30"
        content = (tmp_path / "premeet-2026-08-20-sync-альфа.md").read_text()
        assert content.startswith("# Встреча Sync Альфа в 15:30")
        assert "Вася: должен 1 / тебе должны 1" in content

    def test_none_when_note_not_built(self, populated_db, tmp_path, monkeypatch):
        monkeypatch.setattr(src.meetings, "DIGESTS_DIR", tmp_path)
        ev = _event("2026-08-20T15:30:00", attendees=[])
        assert write_premeeting_note(populated_db, ev) is None
        assert list(tmp_path.glob("premeet-*.md")) == []


# =============================================================================
# Daemon wrapper — _check_meetings (mocked subprocess/notify)
# =============================================================================


class TestCheckMeetings:
    def setup_method(self):
        src.daemon._seen_meetings.clear()

    def _bin(self, tmp_path):
        fake = tmp_path / "calendar-peek"
        fake.write_text("")
        return fake

    def _stdout(self, minutes=5, id="e1", title="Sync"):
        start = (datetime.now() + timedelta(minutes=minutes)).isoformat()
        return json.dumps(
            [{"id": id, "title": title, "start": start, "attendees": ["Вася"]}]
        )

    @patch("src.daemon.notify")
    @patch("src.daemon.subprocess.run")
    def test_missing_binary_silently_skipped(
        self, mock_run, mock_notify, tmp_db, tmp_path
    ):
        with patch("src.daemon.CALENDAR_PEEK_BIN", tmp_path / "нет-такого"):
            src.daemon._check_meetings(tmp_db)
        mock_run.assert_not_called()
        mock_notify.assert_not_called()

    @patch("src.daemon.write_premeeting_note")
    @patch("src.daemon.notify")
    @patch("src.daemon.subprocess.run")
    def test_notifies_new_meeting_with_title_and_path(
        self, mock_run, mock_notify, mock_write, tmp_db, tmp_path
    ):
        mock_run.return_value = MagicMock(stdout=self._stdout(), returncode=0)
        mock_write.return_value = (
            "/x/digests/premeet-2026-08-20-sync.md",
            "Встреча Sync в 14:05",
        )
        with patch("src.daemon.CALENDAR_PEEK_BIN", self._bin(tmp_path)):
            src.daemon._check_meetings(tmp_db)
        mock_notify.assert_called_once()
        args = mock_notify.call_args[0]
        assert args[0] == "Встреча Sync в 14:05"
        assert "/x/digests/premeet-2026-08-20-sync.md" in args[1]

    @patch("src.daemon.write_premeeting_note")
    @patch("src.daemon.notify")
    @patch("src.daemon.subprocess.run")
    def test_dedup_same_event_notified_once(
        self, mock_run, mock_notify, mock_write, tmp_db, tmp_path
    ):
        stdout = self._stdout()
        mock_run.return_value = MagicMock(stdout=stdout, returncode=0)
        mock_write.return_value = ("/x/premeet.md", "Встреча Sync в 14:05")
        with patch("src.daemon.CALENDAR_PEEK_BIN", self._bin(tmp_path)):
            src.daemon._check_meetings(tmp_db)
            src.daemon._check_meetings(tmp_db)
        assert mock_notify.call_count == 1
        assert mock_write.call_count == 1

    @patch("src.daemon.notify")
    @patch("src.daemon.subprocess.run")
    def test_no_access_output_is_silent(self, mock_run, mock_notify, tmp_db, tmp_path):
        mock_run.return_value = MagicMock(stdout='{"error": "no-access"}', returncode=0)
        with patch("src.daemon.CALENDAR_PEEK_BIN", self._bin(tmp_path)):
            src.daemon._check_meetings(tmp_db)
        mock_notify.assert_not_called()

    @patch("src.daemon.notify")
    @patch("src.daemon.subprocess.run")
    def test_subprocess_timeout_does_not_crash(
        self, mock_run, mock_notify, tmp_db, tmp_path
    ):
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd="calendar-peek", timeout=10
        )
        with patch("src.daemon.CALENDAR_PEEK_BIN", self._bin(tmp_path)):
            src.daemon._check_meetings(tmp_db)  # не должно упасть
        mock_notify.assert_not_called()

    @patch("src.daemon.notify")
    @patch("src.daemon.subprocess.run")
    def test_subprocess_called_with_timeout_10(
        self, mock_run, mock_notify, tmp_db, tmp_path
    ):
        mock_run.return_value = MagicMock(stdout="[]", returncode=0)
        with patch("src.daemon.CALENDAR_PEEK_BIN", self._bin(tmp_path)):
            src.daemon._check_meetings(tmp_db)
        assert mock_run.call_args[1]["timeout"] == 10

    @patch("src.daemon.write_premeeting_note", return_value=None)
    @patch("src.daemon.notify")
    @patch("src.daemon.subprocess.run")
    def test_no_note_no_notification(
        self, mock_run, mock_notify, mock_write, tmp_db, tmp_path
    ):
        mock_run.return_value = MagicMock(stdout=self._stdout(), returncode=0)
        with patch("src.daemon.CALENDAR_PEEK_BIN", self._bin(tmp_path)):
            src.daemon._check_meetings(tmp_db)
        mock_write.assert_called_once()
        mock_notify.assert_not_called()

    @patch("src.daemon.write_premeeting_note")
    @patch("src.daemon.notify")
    @patch("src.daemon.subprocess.run")
    def test_note_failure_marks_seen_and_continues(
        self, mock_run, mock_notify, mock_write, tmp_db, tmp_path
    ):
        mock_run.return_value = MagicMock(stdout=self._stdout(), returncode=0)
        mock_write.side_effect = OSError("disk full")
        with patch("src.daemon.CALENDAR_PEEK_BIN", self._bin(tmp_path)):
            src.daemon._check_meetings(tmp_db)  # не должно упасть
        mock_notify.assert_not_called()
