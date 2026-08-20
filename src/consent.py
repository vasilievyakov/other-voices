"""Call Recorder — ask the user before recording a detected call.

ConsentPrompt shows a native macOS dialog (osascript, non-blocking Popen);
ConsentGate is the per-call state machine the daemon loop ticks every poll.
The mic is never touched without an explicit «Записать» — «Нет», timeout,
dialog errors and call-end all resolve to "do not record".
"""

import logging
import subprocess
import time

from .config import CONSENT_TIMEOUT

log = logging.getLogger("call-recorder")

# Extra seconds past the dialog's own "giving up after" before we assume
# osascript hung and kill it.
KILL_GRACE = 10

RECORD_BUTTON = "Записать"
DECLINE_BUTTON = "Нет"

# Without a bot in the meeting we cannot post into its chat — the honest
# minimum for second-party consent is the warn phrase one Cmd-V away.
CONSENT_PHRASE = (
    "Я записываю этот звонок для собственных заметок — запись и расшифровка "
    "остаются только на моем компьютере. Скажи, если ты против."
)


def offer_consent_phrase() -> bool:
    """Put the warn-the-other-side phrase on the clipboard. Soft-fails."""
    try:
        subprocess.run(["pbcopy"], input=CONSENT_PHRASE.encode("utf-8"), timeout=5)
        return True
    except Exception as e:
        log.warning(f"Consent phrase clipboard failed: {e}", extra={"stage": "consent"})
        return False


class ConsentPrompt:
    """A single non-blocking «Записать звонок?» dialog."""

    def __init__(self, app_name: str, timeout: int = CONSENT_TIMEOUT):
        self._timeout = timeout
        self._decision: str | None = None
        self._started = time.monotonic()
        safe_app = app_name.replace("\\", "\\\\").replace('"', '\\"')
        script = (
            f'display dialog "Записать звонок {safe_app}?" '
            f'with title "Call Recorder" '
            # No default button on purpose: consent must be a deliberate
            # click, a reflexive Enter must not start a recording.
            f'buttons {{"{DECLINE_BUTTON}", "{RECORD_BUTTON}"}} '
            f"giving up after {timeout}"
        )
        try:
            self._proc = subprocess.Popen(
                ["osascript", "-e", script],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except Exception as e:
            log.warning(
                f"Consent dialog failed to open: {e}", extra={"stage": "consent"}
            )
            self._proc = None
            self._decision = "decline"

    def poll(self) -> str | None:
        """None while the dialog is open; "record" or "decline" once resolved."""
        if self._decision is not None:
            return self._decision
        if self._proc.poll() is None:
            if time.monotonic() - self._started > self._timeout + KILL_GRACE:
                log.warning(
                    "Consent dialog hung, killing it", extra={"stage": "consent"}
                )
                self._proc.kill()
                self._decision = "decline"
                return self._decision
            return None
        out, _ = self._proc.communicate()
        if (
            self._proc.returncode == 0
            and "gave up:true" not in out
            and (f"button returned:{RECORD_BUTTON}" in out)
        ):
            self._decision = "record"
        else:
            self._decision = "decline"
        return self._decision

    def cancel(self):
        """Close the dialog (call ended before the user answered)."""
        if self._proc is not None and self._proc.poll() is None:
            self._proc.kill()
        self._decision = "decline"


class ConsentGate:
    """Per-call consent state machine, ticked by the daemon loop.

    tick() returns True exactly once — on the tick when the user granted
    recording. A decline (button, timeout, error) suppresses further prompts
    until the current call ends.
    """

    def __init__(self, prompt_factory=ConsentPrompt):
        self._factory = prompt_factory
        self._prompt = None
        self._denied = False

    def tick(self, in_call: bool, app_name: str | None, recording: bool) -> bool:
        if not in_call:
            if self._prompt is not None:
                log.info(
                    "Call ended before consent — dialog dismissed",
                    extra={"stage": "consent"},
                )
                self._prompt.cancel()
                self._prompt = None
            self._denied = False
            return False

        if recording or self._denied:
            return False

        if self._prompt is None:
            log.info(
                f"Asking consent to record: {app_name}", extra={"stage": "consent"}
            )
            self._prompt = self._factory(app_name)
            return False

        decision = self._prompt.poll()
        if decision is None:
            return False
        self._prompt = None
        if decision == "record":
            log.info("Consent granted, starting recording", extra={"stage": "consent"})
            return True
        log.info(
            "Consent declined (button/timeout) — not recording this call",
            extra={"stage": "consent"},
        )
        self._denied = True
        return False
