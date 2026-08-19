"""Call Recorder — call detection via psutil."""

import psutil


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

    def __init__(self, confirmations: int = 1):
        """confirmations — how many consecutive positive checks are required
        before a call is reported. 1 = report immediately."""
        self._confirmations = confirmations
        self._streak = 0
        self._streak_app: str | None = None

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
        # 1. Zoom — just check for CptHost process
        if self._process_exists(self.ZOOM_PROCESS):
            return True, "Zoom"

        # 2. Native apps — check process + UDP connections
        for app_name, info in self.UDP_APPS.items():
            for proc_name in info["processes"]:
                if self._has_udp_connections(proc_name, info["min_udp"]):
                    return True, app_name

        # 3. Google Meet (browser) — browser helper with multiple UDP connections
        for helper in self.BROWSER_HELPERS:
            if self._has_udp_connections(
                helper, 2, exclude_ports=self.BROWSER_EXCLUDED_PORTS
            ):
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
