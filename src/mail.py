"""Follow-up drafts into Mail.app — a draft window, never a send.

Delivery stays with the owner: this module only opens a compose window with
the text already in place. There is deliberately no send anywhere here.
"""

import logging
import subprocess

log = logging.getLogger("call-recorder")


def _esc(text: str) -> str:
    return (text or "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def build_mail_draft_script(
    subject: str, body: str, recipient: str | None = None
) -> str:
    lines = [
        'tell application "Mail"',
        (
            "set msg to make new outgoing message with properties "
            f'{{subject:"{_esc(subject)}", content:"{_esc(body)}", visible:true}}'
        ),
    ]
    if recipient:
        lines.append(
            "tell msg to make new to recipient at end of to recipients "
            f'with properties {{address:"{_esc(recipient)}"}}'
        )
    lines += ["activate", "end tell"]
    return "\n".join(lines)


def create_mail_draft(subject: str, body: str, recipient: str | None = None) -> bool:
    """Open a Mail.app draft with the text in place. Soft-fails."""
    script = build_mail_draft_script(subject, body, recipient)
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=15)
        return True
    except Exception as e:
        log.warning(f"Mail draft failed: {e}", extra={"stage": "delivery"})
        return False
