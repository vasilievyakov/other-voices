"""Call Recorder — call detection: physical signal first, UDP heuristics fallback."""

import json
import subprocess

import psutil

from .config import CALL_SIGNAL_BIN

# Chrome holds this power assertion for the lifetime of a WebRTC call —
# it survives mute, unlike the mic-in-use signal.
WEBRTC_ASSERTION = "WebRTC has active PeerConnections"


class SignalProbe:
    """One-shot physical call signal: mic holders, camera, WebRTC assertion.

    Wraps bin/call-signal (CoreAudio per-process + CMIO camera, macOS 14.4+)
    and pmset. Returns None when the helper is missing or broken so the
    detector can fall back to legacy UDP heuristics.
    """

    def __init__(self, binary=CALL_SIGNAL_BIN):
        self._binary = binary

    def probe(self) -> dict | None:
        try:
            out = subprocess.run(
                [str(self._binary)], capture_output=True, timeout=3, text=True
            )
            data = json.loads(out.stdout)
            mic_apps = [
                p["name"] for p in data.get("mic_processes", []) if p.get("name")
            ]
            camera_on = bool(data.get("camera_on"))
        except Exception:
            return None
        try:
            pmset = subprocess.run(
                ["pmset", "-g", "assertions"], capture_output=True, timeout=3, text=True
            )
            assertion = WEBRTC_ASSERTION in pmset.stdout
        except Exception:
            assertion = False
        return {
            "mic_apps": mic_apps,
            "camera_on": camera_on,
            "webrtc_assertion": assertion,
        }


def _iter_processes(attrs):
    """psutil.process_iter that survives macOS sysctl races.

    On macOS psutil's as_dict → name() → proc_cmdline can raise
    SystemError/PermissionError from inside the iterator itself (sysctl
    KERN_PROCARGS2 race) — outside any per-process try/except in the loop
    body. This killed the daemon on 10.06, 11.07 and 13.07. Losing the rest
    of one poll cycle is fine: the next poll runs in POLL_INTERVAL seconds.
    """
    try:
        yield from psutil.process_iter(attrs)
    except (SystemError, PermissionError, psutil.Error):
        return


class CallDetector:
    """Detects active voice/video calls by checking running processes and UDP connections."""

    # CptHost only exists during active Zoom call — most reliable
    ZOOM_PROCESS = "CptHost"

    # Chrome speaks QUIC (HTTP/3) over UDP:443 during ordinary browsing, which
    # looks identical to a call by connection count alone. Meet media uses
    # high ports (19305+), so 443 is excluded for browser helpers only.
    BROWSER_EXCLUDED_PORTS = frozenset({443})

    # Apps where we check process + UDP connections
    UDP_APPS = {
        "Microsoft Teams": {"processes": ["Microsoft Teams"], "min_udp": 2},
        "Discord": {"processes": ["Discord"], "min_udp": 2},
        "Telegram": {"processes": ["Telegram"], "min_udp": 2},
        "FaceTime": {"processes": ["FaceTime"], "min_udp": 2},
    }

    # Browser-based: look for browser helper processes with UDP (WebRTC)
    BROWSER_HELPERS = [
        "Google Chrome Helper",
        "Arc Helper",
        "Chromium Helper",
        "Google Chrome Helper (Renderer)",
    ]

    # Mic holders that map to a call platform. Unknown holders (dictation
    # tools, voice notes, system agents like replayd) map to nothing — no
    # false positives by construction.
    KNOWN_CALL_APPS = {
        "zoom.us": "Zoom",
        "Microsoft Teams": "Microsoft Teams",
        "MSTeams": "Microsoft Teams",
        "Discord": "Discord",
        "Telegram": "Telegram",
        "FaceTime": "FaceTime",
    }

    # Our own recorder must never detect itself (it holds the mic while
    # recording — the classic stuck-detector bug).
    # "AudioCapture" is how the bundled recorder reports via its .app name.
    OWN_PROCESSES = {"audio-capture", "AudioCapture", "call-signal"}

    BROWSER_NAME_PREFIXES = ("Google Chrome", "Arc", "Chromium")

    def __init__(self, confirmations: int = 1, signal_probe=None):
        """confirmations — how many consecutive positive checks are required
        before a call is reported. 1 = report immediately.

        signal_probe — physical-signal source (SignalProbe by default);
        injectable for tests."""
        self._confirmations = confirmations
        self._streak = 0
        self._streak_app: str | None = None
        self._probe = signal_probe if signal_probe is not None else SignalProbe()

    def check(self) -> tuple[bool, str | None]:
        """Check if a call is active, debounced over consecutive calls.

        Returns:
            (is_active, app_name) — e.g. (True, "Zoom") or (False, None)
        """
        active, app = self._raw_check()
        if not active:
            self._streak = 0
            self._streak_app = None
            return False, None
        if app == self._streak_app:
            self._streak += 1
        else:
            self._streak = 1
            self._streak_app = app
        if self._streak >= self._confirmations:
            return True, app
        return False, None

    def _raw_check(self) -> tuple[bool, str | None]:
        """Single instantaneous detection pass, no debounce."""
        # 1. Zoom — just check for CptHost process (cheapest, proven)
        if self._process_exists(self.ZOOM_PROCESS):
            return True, "Zoom"

        # 2. Physical signal — authoritative when the helper is healthy
        signal = self._probe.probe()
        if signal is not None:
            return self._check_signal(signal)

        # 3. Legacy fallback: native apps — process + UDP connections
        for app_name, info in self.UDP_APPS.items():
            for proc_name in info["processes"]:
                if self._has_udp_connections(proc_name, info["min_udp"]):
                    return True, app_name

        # 4. Legacy fallback: Google Meet — browser helper with UDP connections
        for helper in self.BROWSER_HELPERS:
            if self._has_udp_connections(
                helper, 2, exclude_ports=self.BROWSER_EXCLUDED_PORTS
            ):
                return True, "Google Meet"

        return False, None

    def _check_signal(self, signal: dict) -> tuple[bool, str | None]:
        """Decide from the physical signal (see docs/plans/…detection-v2…)."""
        mic_apps = [a for a in signal["mic_apps"] if a not in self.OWN_PROCESSES]

        for name in mic_apps:
            if name in self.KNOWN_CALL_APPS:
                return True, self.KNOWN_CALL_APPS[name]

        # Browser call: the WebRTC assertion is the mute-proof signal;
        # mic + camera covers assertion-less browsers.
        if signal["webrtc_assertion"]:
            return True, "Google Meet"
        browser_has_mic = any(
            name.startswith(self.BROWSER_NAME_PREFIXES) for name in mic_apps
        )
        if browser_has_mic and signal["camera_on"]:
            return True, "Google Meet"

        return False, None

    def _process_exists(self, name: str) -> bool:
        """Check if a process with given name is running."""
        for proc in _iter_processes(["name"]):
            try:
                if proc.info["name"] == name:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return False

    def _has_udp_connections(
        self,
        process_name: str,
        min_count: int,
        exclude_ports: frozenset[int] = frozenset(),
    ) -> bool:
        """Check if a process has at least min_count UDP connections to distinct IPs."""
        for proc in _iter_processes(["name"]):
            try:
                if proc.info["name"] != process_name:
                    continue
                conns = proc.net_connections(kind="udp")
                # Count connections with remote addresses (active UDP)
                remote_ips = set()
                for conn in conns:
                    if conn.raddr and conn.raddr.port not in exclude_ports:
                        remote_ips.add(conn.raddr.ip)
                if len(remote_ips) >= min_count:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        return False
