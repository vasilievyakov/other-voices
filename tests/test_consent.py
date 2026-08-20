"""Tests for src.consent — osascript consent dialog and per-call gate."""

from unittest.mock import MagicMock, patch

from src.consent import ConsentPrompt, ConsentGate


def make_osascript_proc(stdout="", returncode=0, running=False):
    """Mock subprocess.Popen result for the osascript dialog."""
    proc = MagicMock()
    proc.poll.return_value = None if running else returncode
    proc.returncode = None if running else returncode
    proc.communicate.return_value = (stdout, "")
    return proc


# =============================================================================
# ConsentPrompt — dialog spawning and answer parsing
# =============================================================================


class TestConsentPrompt:
    @patch("src.consent.subprocess.Popen")
    def test_spawns_osascript_dialog(self, mock_popen):
        mock_popen.return_value = make_osascript_proc(running=True)
        ConsentPrompt("Google Meet")
        args = mock_popen.call_args[0][0]
        assert args[0] == "osascript"
        script = " ".join(args)
        assert "Google Meet" in script
        assert "Записать" in script

    @patch("src.consent.subprocess.Popen")
    def test_pending_while_dialog_open(self, mock_popen):
        mock_popen.return_value = make_osascript_proc(running=True)
        prompt = ConsentPrompt("Google Meet")
        assert prompt.poll() is None

    @patch("src.consent.subprocess.Popen")
    def test_record_button_returns_record(self, mock_popen):
        mock_popen.return_value = make_osascript_proc(
            stdout="button returned:Записать, gave up:false\n"
        )
        prompt = ConsentPrompt("Google Meet")
        assert prompt.poll() == "record"

    @patch("src.consent.subprocess.Popen")
    def test_no_button_returns_decline(self, mock_popen):
        mock_popen.return_value = make_osascript_proc(
            stdout="button returned:Нет, gave up:false\n"
        )
        prompt = ConsentPrompt("Google Meet")
        assert prompt.poll() == "decline"

    @patch("src.consent.subprocess.Popen")
    def test_timeout_gave_up_returns_decline(self, mock_popen):
        mock_popen.return_value = make_osascript_proc(
            stdout="button returned:, gave up:true\n"
        )
        prompt = ConsentPrompt("Google Meet")
        assert prompt.poll() == "decline"

    @patch("src.consent.subprocess.Popen")
    def test_osascript_error_returns_decline(self, mock_popen):
        mock_popen.return_value = make_osascript_proc(stdout="", returncode=1)
        prompt = ConsentPrompt("Google Meet")
        assert prompt.poll() == "decline"

    @patch("src.consent.subprocess.Popen")
    def test_spawn_failure_returns_decline(self, mock_popen):
        mock_popen.side_effect = OSError("no osascript")
        prompt = ConsentPrompt("Google Meet")
        assert prompt.poll() == "decline"

    @patch("src.consent.subprocess.Popen")
    def test_hung_dialog_killed_after_grace(self, mock_popen):
        """osascript alive past timeout + grace → kill → decline."""
        proc = make_osascript_proc(running=True)
        mock_popen.return_value = proc
        with patch("src.consent.time.monotonic", side_effect=[100.0, 100.0 + 60 + 11]):
            prompt = ConsentPrompt("Google Meet", timeout=60)
            assert prompt.poll() == "decline"
        proc.kill.assert_called_once()

    @patch("src.consent.subprocess.Popen")
    def test_cancel_kills_dialog(self, mock_popen):
        proc = make_osascript_proc(running=True)
        mock_popen.return_value = proc
        prompt = ConsentPrompt("Google Meet")
        prompt.cancel()
        proc.kill.assert_called_once()

    @patch("src.consent.subprocess.Popen")
    def test_cancel_after_exit_is_safe(self, mock_popen):
        mock_popen.return_value = make_osascript_proc(stdout="button returned:Нет\n")
        prompt = ConsentPrompt("Google Meet")
        prompt.poll()
        prompt.cancel()  # must not raise


# =============================================================================
# ConsentGate — per-call state machine for the daemon loop
# =============================================================================


class FakePrompt:
    def __init__(self, app_name):
        self.app_name = app_name
        self.answers = []
        self.cancelled = False

    def poll(self):
        return self.answers.pop(0) if self.answers else None

    def cancel(self):
        self.cancelled = True


class TestConsentGate:
    def setup_method(self):
        self.prompts: list[FakePrompt] = []

        def factory(app_name):
            prompt = FakePrompt(app_name)
            self.prompts.append(prompt)
            return prompt

        self.gate = ConsentGate(prompt_factory=factory)

    def test_no_call_no_prompt(self):
        assert self.gate.tick(False, None, recording=False) is False
        assert self.prompts == []

    def test_call_spawns_prompt_once(self):
        assert self.gate.tick(True, "Google Meet", recording=False) is False
        assert self.gate.tick(True, "Google Meet", recording=False) is False
        assert len(self.prompts) == 1
        assert self.prompts[0].app_name == "Google Meet"

    def test_record_answer_starts_recording_once(self):
        self.gate.tick(True, "Google Meet", recording=False)
        self.prompts[0].answers = ["record"]
        assert self.gate.tick(True, "Google Meet", recording=False) is True
        # recording is now on; no new prompt, no second True
        assert self.gate.tick(True, "Google Meet", recording=True) is False
        assert len(self.prompts) == 1

    def test_decline_answer_blocks_until_call_ends(self):
        self.gate.tick(True, "Google Meet", recording=False)
        self.prompts[0].answers = ["decline"]
        assert self.gate.tick(True, "Google Meet", recording=False) is False
        # same call continues — no re-prompt
        assert self.gate.tick(True, "Google Meet", recording=False) is False
        assert len(self.prompts) == 1
        # call ends, new call → fresh prompt
        self.gate.tick(False, None, recording=False)
        self.gate.tick(True, "Google Meet", recording=False)
        assert len(self.prompts) == 2

    def test_call_end_cancels_pending_prompt(self):
        self.gate.tick(True, "Google Meet", recording=False)
        assert self.gate.tick(False, None, recording=False) is False
        assert self.prompts[0].cancelled is True

    def test_no_prompt_while_recording(self):
        assert self.gate.tick(True, "Google Meet", recording=True) is False
        assert self.prompts == []


class TestNoDefaultButton:
    @patch("src.consent.subprocess.Popen")
    def test_dialog_has_no_default_button(self, mock_popen):
        """Consent must be a deliberate click — Enter must not answer the dialog.

        Board recommendation (Ive, Murati): a dialog with legal consequences
        must not be answerable by a reflexive keypress.
        """
        mock_popen.return_value = make_osascript_proc(running=True)
        ConsentPrompt("Google Meet")
        script = " ".join(mock_popen.call_args[0][0])
        assert "default button" not in script


class TestConsentPhrase:
    """The honest minimum for second-party consent: the warn phrase is one
    Cmd-V away the moment recording starts."""

    def test_phrase_lands_on_clipboard(self, monkeypatch):
        import src.consent as consent_mod

        seen = {}

        def fake_run(cmd, **kwargs):
            seen["cmd"] = cmd
            seen["input"] = kwargs.get("input")

        monkeypatch.setattr(consent_mod.subprocess, "run", fake_run)
        assert consent_mod.offer_consent_phrase() is True
        assert seen["cmd"] == ["pbcopy"]
        text = seen["input"].decode("utf-8").lower()
        assert "запис" in text
        assert "компьютер" in text

    def test_clipboard_failure_is_soft(self, monkeypatch):
        import src.consent as consent_mod

        def boom(*args, **kwargs):
            raise OSError("no clipboard")

        monkeypatch.setattr(consent_mod.subprocess, "run", boom)
        assert consent_mod.offer_consent_phrase() is False
