#!/usr/bin/env python3
"""Chat CLI — ask questions about calls via command line.

Usage:
    python chat_cli.py <session_id> "What was decided?"
    python chat_cli.py --global "What did Vasya promise this week?"
"""

import argparse
import sys

from src.chat import ChatEngine


def main():
    parser = argparse.ArgumentParser(description="Chat with call recordings")
    parser.add_argument(
        "session_id",
        nargs="?",
        default=None,
        help="Session ID to ask about (omit for global)",
    )
    parser.add_argument("question", help="Question to ask")
    parser.add_argument(
        "--global",
        dest="global_scope",
        action="store_true",
        help="Ask across all calls",
    )

    args = parser.parse_args()

    session_id = None if args.global_scope else args.session_id
    if not session_id and not args.global_scope:
        # If first positional is the question (no session_id)
        session_id = None

    engine = ChatEngine()
    answer = engine.ask(args.question, session_id=session_id)

    if answer:
        print(answer)
    else:
        print("Error: Could not get response from Ollama", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
