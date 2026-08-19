"""Person briefing CLI: what stands between you and this person.

Usage: .venv/bin/python scripts/brief.py "<имя>"
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.brief import build_brief, render_brief  # noqa: E402
from src.database import Database  # noqa: E402


def main():
    if len(sys.argv) != 2:
        print('Usage: brief.py "<имя человека>"')
        sys.exit(2)
    name = sys.argv[1]
    brief = build_brief(Database(), name)
    if brief is None:
        print(f"«{name}» не найден среди участников звонков.")
        sys.exit(1)
    print(render_brief(brief))


if __name__ == "__main__":
    main()
