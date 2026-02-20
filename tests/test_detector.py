"""Tests for src.detector — mock psutil.process_iter.

Enterprise coverage: all apps, priority, thresholds, resilience.
"""

from unittest.mock import patch, MagicMock
import psutil

from src.detector import CallDetector
from tests.conftest import make_proc, make_conn, make_conn_no_raddr


# =============================================================================
# Detector Functionality (10 tests)
# =============================================================================


class TestDetectorFunctionality:
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
    def test_teams_detected(self, mock_iter):
        """Microsoft Teams + ≥2 distinct UDP IPs → (True, 'Microsoft Teams')."""
        teams = make_proc(
            "Microsoft Teams",
            connections=[make_conn("10.0.0.1"), make_conn("10.0.0.2")],
        )
        mock_iter.return_value = [teams, make_proc("Finder")]
        active, app = self.detector.check()
        assert active is True
        assert app == "Microsoft Teams"

    @patch("src.detector.psutil.process_iter")
    def test_discord_detected(self, mock_iter):
        """Discord + ≥2 UDP → (True, 'Discord')."""
        discord = make_proc(
            "Discord", connections=[make_conn("1.1.1.1"), make_conn("2.2.2.2")]
        )
        mock_iter.return_value = [discord]
        active, app = self.detector.check()
        assert active is True
        assert app == "Discord"

    @patch("src.detector.psutil.process_iter")
    def test_telegram_detected(self, mock_iter):
        """Telegram + ≥2 UDP → (True, 'Telegram')."""
        tg = make_proc(
            "Telegram", connections=[make_conn("3.3.3.3"), make_conn("4.4.4.4")]
        )
        mock_iter.return_value = [tg]
        active, app = self.detector.check()
        assert active is True
        assert app == "Telegram"

    @patch("src.detector.psutil.process_iter")
    def test_facetime_detected(self, mock_iter):
        """FaceTime + ≥2 UDP → (True, 'FaceTime')."""
        ft = make_proc(
            "FaceTime", connections=[make_conn("5.5.5.5"), make_conn("6.6.6.6")]
        )
        mock_iter.return_value = [ft]
        active, app = self.detector.check()
        assert active is True
        assert app == "FaceTime"

    @patch("src.detector.psutil.process_iter")
    def test_google_meet_chrome(self, mock_iter):
        """Google Chrome Helper + ≥2 UDP → (True, 'Google Meet')."""
        chrome = make_proc(
            "Google Chrome Helper",
            connections=[make_conn("142.250.1.1"), make_conn("142.250.1.2")],
        )
        mock_iter.return_value = [chrome, make_proc("Finder")]
        active, app = self.detector.check()
        assert active is True
        assert app == "Google Meet"

    @patch("src.detector.psutil.process_iter")
    def test_google_meet_arc(self, mock_iter):
        """Arc Helper + ≥2 UDP → (True, 'Google Meet')."""
        arc = make_proc(
            "Arc Helper", connections=[make_conn("10.0.0.1"), make_conn("10.0.0.2")]
        )
        mock_iter.return_value = [arc]
        active, app = self.detector.check()
        assert active is True
        assert app == "Google Meet"

    @patch("src.detector.psutil.process_iter")
    def test_google_meet_chromium(self, mock_iter):
        """Chromium Helper + ≥2 UDP → (True, 'Google Meet')."""
        chromium = make_proc(
            "Chromium Helper",
            connections=[make_conn("10.0.0.1"), make_conn("10.0.0.2")],
        )
        mock_iter.return_value = [chromium]
        active, app = self.detector.check()
        assert active is True
        assert app == "Google Meet"

    @patch("src.detector.psutil.process_iter")
    def test_google_meet_renderer(self, mock_iter):
        """Google Chrome Helper (Renderer) + ≥2 UDP → (True, 'Google Meet')."""
        renderer = make_proc(
            "Google Chrome Helper (Renderer)",
            connections=[make_conn("10.0.0.1"), make_conn("10.0.0.2")],
        )
        mock_iter.return_value = [renderer]
        active, app = self.detector.check()
        assert active is True
        assert app == "Google Meet"


# =============================================================================
# Detection Priority & Thresholds (8 tests)
# =============================================================================


class TestDetectorPriority:
    def setup_method(self):
        self.detector = CallDetector()

    @patch("src.detector.psutil.process_iter")
    def test_zoom_wins_over_teams(self, mock_iter):
        """Zoom + Teams simultaneously → Zoom wins (checked first)."""
        cpthost = make_proc("CptHost")
        teams = make_proc(
            "Microsoft Teams",
            connections=[make_conn("10.0.0.1"), make_conn("10.0.0.2")],
        )
        mock_iter.return_value = [cpthost, teams]
        active, app = self.detector.check()
        assert active is True
        assert app == "Zoom"

    @patch("src.detector.psutil.process_iter")
    def test_zoom_wins_over_browser(self, mock_iter):
        """Zoom + Google Meet simultaneously → Zoom wins."""
        cpthost = make_proc("CptHost")
        chrome = make_proc(
            "Google Chrome Helper",
            connections=[make_conn("1.1.1.1"), make_conn("2.2.2.2")],
        )
        mock_iter.return_value = [cpthost, chrome]
        active, app = self.detector.check()
        assert active is True
        assert app == "Zoom"

    @patch("src.detector.psutil.process_iter")
    def test_native_app_wins_over_browser(self, mock_iter):
        """Teams + Chrome (Meet) simultaneously → Teams wins (checked before browsers)."""
        teams = make_proc(
            "Microsoft Teams",
            connections=[make_conn("10.0.0.1"), make_conn("10.0.0.2")],
        )
        chrome = make_proc(
            "Google Chrome Helper",
            connections=[make_conn("1.1.1.1"), make_conn("2.2.2.2")],
        )
        mock_iter.return_value = [teams, chrome]
        active, app = self.detector.check()
        assert active is True
        assert app == "Microsoft Teams"

    @patch("src.detector.psutil.process_iter")
    def test_udp_below_threshold_not_detected(self, mock_iter):
        """Teams with only 1 UDP connection → not detected (min_udp=2)."""
        teams = make_proc("Microsoft Teams", connections=[make_conn("10.0.0.1")])
        mock_iter.return_value = [teams]
        active, app = self.detector.check()
        assert active is False
        assert app is None

    @patch("src.detector.psutil.process_iter")
    def test_udp_no_connections(self, mock_iter):
        """Teams process running but 0 UDP → not detected."""
        teams = make_proc("Microsoft Teams", connections=[])
        mock_iter.return_value = [teams]
        active, app = self.detector.check()
        assert active is False
        assert app is None

    @patch("src.detector.psutil.process_iter")
    def test_distinct_ips_counted(self, mock_iter):
        """Same IP counted once — 3 connections to 1 IP = 1 distinct."""
        teams = make_proc(
            "Microsoft Teams",
            connections=[
                make_conn("10.0.0.1"),
                make_conn("10.0.0.1"),
                make_conn("10.0.0.1"),
            ],
        )
        mock_iter.return_value = [teams]
        active, app = self.detector.check()
        assert active is False  # Only 1 distinct IP, need 2

    @patch("src.detector.psutil.process_iter")
    def test_connections_without_raddr_ignored(self, mock_iter):
        """UDP connections without remote address (listening) don't count."""
        teams = make_proc(
            "Microsoft Teams",
            connections=[
                make_conn_no_raddr(),
                make_conn_no_raddr(),
                make_conn_no_raddr(),
            ],
        )
        mock_iter.return_value = [teams]
        active, app = self.detector.check()
        assert active is False

    @patch("src.detector.psutil.process_iter")
    def test_browser_below_threshold(self, mock_iter):
        """Chrome Helper with 1 UDP → not detected as Google Meet."""
        chrome = make_proc("Google Chrome Helper", connections=[make_conn("1.1.1.1")])
        mock_iter.return_value = [chrome]
        active, app = self.detector.check()
        assert active is False


# =============================================================================
# Detector Resilience (6 tests)
# =============================================================================


class TestDetectorResilience:
    def setup_method(self):
        self.detector = CallDetector()

    @patch("src.detector.psutil.process_iter")
    def test_access_denied_in_process_iter(self, mock_iter):
        """psutil.AccessDenied during iteration doesn't crash."""
        good = make_proc("Finder")

        class BadProc:
            @property
            def info(self):
                raise psutil.AccessDenied(pid=999)

        mock_iter.return_value = [BadProc(), good]
        active, app = self.detector.check()
        assert active is False

    @patch("src.detector.psutil.process_iter")
    def test_no_such_process(self, mock_iter):
        """psutil.NoSuchProcess during iteration is handled."""

        class DyingProc:
            @property
            def info(self):
                raise psutil.NoSuchProcess(pid=123)

        mock_iter.return_value = [DyingProc(), make_proc("Finder")]
        active, app = self.detector.check()
        assert active is False

    @patch("src.detector.psutil.process_iter")
    def test_zombie_process_in_udp_check(self, mock_iter):
        """ZombieProcess during net_connections doesn't crash."""
        teams = make_proc("Microsoft Teams")
        teams.net_connections.side_effect = psutil.ZombieProcess(pid=666)
        mock_iter.return_value = [teams]
        active, app = self.detector.check()
        assert active is False

    @patch("src.detector.psutil.process_iter")
    def test_access_denied_in_net_connections(self, mock_iter):
        """AccessDenied during net_connections doesn't crash."""
        teams = make_proc("Microsoft Teams")
        teams.net_connections.side_effect = psutil.AccessDenied(pid=123)
        mock_iter.return_value = [teams]
        active, app = self.detector.check()
        assert active is False

    @patch("src.detector.psutil.process_iter")
    def test_mixed_healthy_and_bad_processes(self, mock_iter):
        """Mix of healthy and crashing processes — healthy one wins."""
        bad_teams = make_proc("Microsoft Teams")
        bad_teams.net_connections.side_effect = psutil.AccessDenied(pid=1)

        good_discord = make_proc(
            "Discord", connections=[make_conn("1.1.1.1"), make_conn("2.2.2.2")]
        )
        mock_iter.return_value = [bad_teams, good_discord]
        active, app = self.detector.check()
        assert active is True
        assert app == "Discord"

    @patch("src.detector.psutil.process_iter")
    def test_empty_process_list(self, mock_iter):
        """Empty process list → (False, None)."""
        mock_iter.return_value = []
        active, app = self.detector.check()
        assert active is False
        assert app is None
