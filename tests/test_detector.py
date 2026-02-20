"""Tests for src.detector — mock psutil.process_iter."""

from unittest.mock import patch, MagicMock
import psutil

from src.detector import CallDetector
from tests.conftest import make_proc


def _make_conn(ip):
    """Create a mock UDP connection with remote address."""
    conn = MagicMock()
    conn.raddr = MagicMock()
    conn.raddr.ip = ip
    return conn


class TestCallDetector:
    def setup_method(self):
        self.detector = CallDetector()

    @patch("src.detector.psutil.process_iter")
    def test_no_calls(self, mock_iter):
        """No relevant processes → (False, None)."""
        mock_iter.return_value = [make_proc("Safari"), make_proc("Finder")]
        active, app = self.detector.check()
        assert active is False
        assert app is None

    @patch("src.detector.psutil.process_iter")
    def test_zoom_by_cpthost(self, mock_iter):
        """CptHost process → (True, 'Zoom')."""
        mock_iter.return_value = [make_proc("CptHost"), make_proc("Finder")]
        active, app = self.detector.check()
        assert active is True
        assert app == "Zoom"

    @patch("src.detector.psutil.process_iter")
    def test_teams_by_udp(self, mock_iter):
        """Teams + ≥2 UDP connections → (True, 'Microsoft Teams')."""
        teams = make_proc(
            "Microsoft Teams",
            connections=[_make_conn("10.0.0.1"), _make_conn("10.0.0.2")],
        )
        mock_iter.return_value = [teams, make_proc("Finder")]
        active, app = self.detector.check()
        assert active is True
        assert app == "Microsoft Teams"

    @patch("src.detector.psutil.process_iter")
    def test_browser_webrtc(self, mock_iter):
        """Chrome Helper + UDP → (True, 'Google Meet')."""
        chrome = make_proc(
            "Google Chrome Helper",
            connections=[_make_conn("142.250.1.1"), _make_conn("142.250.1.2")],
        )
        mock_iter.return_value = [chrome, make_proc("Finder")]
        active, app = self.detector.check()
        assert active is True
        assert app == "Google Meet"

    @patch("src.detector.psutil.process_iter")
    def test_zoom_priority(self, mock_iter):
        """Zoom + Teams simultaneously → Zoom wins (checked first)."""
        cpthost = make_proc("CptHost")
        teams = make_proc(
            "Microsoft Teams",
            connections=[_make_conn("10.0.0.1"), _make_conn("10.0.0.2")],
        )
        mock_iter.return_value = [cpthost, teams]
        active, app = self.detector.check()
        assert active is True
        assert app == "Zoom"

    @patch("src.detector.psutil.process_iter")
    def test_access_denied_handled(self, mock_iter):
        """psutil.AccessDenied doesn't crash."""
        bad_proc = MagicMock()
        bad_proc.info = {"name": "CptHost"}
        # _process_exists iterates, first proc raises AccessDenied
        bad_proc.__getitem__ = MagicMock(side_effect=psutil.AccessDenied(pid=1))

        # Make process_iter raise on the bad proc's name check
        def bad_info_get(key):
            raise psutil.AccessDenied(pid=1)

        bad_proc2 = MagicMock()
        type(bad_proc2).info = property(
            lambda self: (_ for _ in ()).throw(psutil.AccessDenied(pid=1))
        )

        # Simpler approach: proc.info["name"] raises
        class BadProc:
            @property
            def info(self):
                raise psutil.AccessDenied(pid=1)

        mock_iter.return_value = [BadProc(), make_proc("Finder")]
        active, app = self.detector.check()
        # Should not crash, just skip the bad process
        assert active is False
        assert app is None
