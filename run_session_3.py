"""
Session 3 — "What have you learned?" (Stretch S4)

No new documents are uploaded. The only message asks the agent to summarize
everything it has learned about Acme Corp across sessions 1 and 2, purely
from its persistent memory store. This is the most direct demo of what's
actually stored in memory.

Usage:
    python run_session_3.py
"""

import os
import sys

from session_lib import run_session_stream


def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("Set ANTHROPIC_API_KEY before running.")

    print("Asking the agent what it has learned about Acme Corp so far...\n")
    for event in run_session_stream("session3"):
        kind = event.get("kind")
        if kind == "status":
            print(event["message"])
        elif kind == "text":
            print(event["text"], end="", flush=True)
        elif kind == "tool":
            tag = "memory" if event.get("is_memory") else event.get("name")
            print(f"\n  [{tag}: {event.get('name')}  {event.get('target')}]", flush=True)
        elif kind == "error":
            print(f"ERROR: {event['message']}", file=sys.stderr)
            raise SystemExit(1)
        elif kind == "done":
            print("\n\n[agent finished]")

    print("\nSaved to outputs/session3.txt")


if __name__ == "__main__":
    main()
