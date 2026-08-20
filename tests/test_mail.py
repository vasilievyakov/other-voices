"""Tests for src.mail — follow-up drafts into Mail.app.

A draft window, never a send: the AppleScript must not contain a send
command, and delivery stays with the owner's hand.
"""

from src.mail import build_mail_draft_script, create_mail_draft


class TestBuildScript:
    def test_contains_subject_body_and_stays_draft(self):
        s = build_mail_draft_script("Договоренности: Андрей", "Привет!\nДве строки")
        assert "make new outgoing message" in s
        assert "Договоренности: Андрей" in s
        assert "visible:true" in s
        assert "send" not in s.lower()

    def test_newlines_escaped_into_applescript(self):
        s = build_mail_draft_script("Т", "первая\nвторая")
        for line in s.splitlines():
            if "content" in line:
                assert "первая\\nвторая" in line

    def test_quotes_and_backslashes_escaped(self):
        s = build_mail_draft_script('Тема "в кавычках"', 'путь C:\\dir и "цитата"')
        assert '\\"в кавычках\\"' in s
        assert "C:\\\\dir" in s

    def test_recipient_when_known(self):
        s = build_mail_draft_script("Т", "B", recipient="a@b.co")
        assert "to recipients" in s
        assert "a@b.co" in s

    def test_no_recipient_block_when_unknown(self):
        s = build_mail_draft_script("Т", "B")
        assert "to recipients" not in s


class TestCreateDraft:
    def test_invokes_osascript(self, monkeypatch):
        import src.mail as mail_mod

        seen = {}

        def fake_run(cmd, **kwargs):
            seen["cmd"] = cmd

        monkeypatch.setattr(mail_mod.subprocess, "run", fake_run)
        assert create_mail_draft("Тема", "Тело") is True
        assert seen["cmd"][0] == "osascript"
        assert "make new outgoing message" in seen["cmd"][2]

    def test_soft_fail(self, monkeypatch):
        import src.mail as mail_mod

        def boom(*args, **kwargs):
            raise OSError("no Mail")

        monkeypatch.setattr(mail_mod.subprocess, "run", boom)
        assert create_mail_draft("Тема", "Тело") is False
