"""Call Recorder — call detection via psutil."""

import psutil


class CallDetector:
    """Detects active voice/video calls by checking running processes and UDP connections."""

    # CptHost only exists during active Zoom call — most reliable
    ZOOM_PROCESS = "CptHost"

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

    def check(self) -> tuple[bool, str | None]:
        """Check if a call is active.

        Returns:
            (is_active, app_name) — e.g. (True, "Zoom") or (False, None)
        """
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
            if self._has_udp_connections(helper, 2):
                return True, "Google Meet"

        return False, None

    def _process_exists(self, name: str) -> bool:
        """Check if a process with given name is running."""
        for proc in psutil.process_iter(["name"]):
            try:
                if proc.info["name"] == name:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return False

    def _has_udp_connections(self, process_name: str, min_count: int) -> bool:
        """Check if a process has at least min_count UDP connections to distinct IPs."""
        for proc in psutil.process_iter(["name"]):
            try:
                if proc.info["name"] != process_name:
                    continue
                conns = proc.net_connections(kind="udp")
                # Count connections with remote addresses (active UDP)
                remote_ips = set()
                for conn in conns:
                    if conn.raddr:
                        remote_ips.add(conn.raddr.ip)
                if len(remote_ips) >= min_count:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        return False
