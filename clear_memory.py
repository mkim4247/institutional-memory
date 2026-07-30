"""
Clear all entries from the agent's memory store — useful to reset before a
fresh demo run (so Session 1 truly starts from a blank slate again, and the
memory diff panel shows a dramatic before/after).

This does NOT delete the memory store itself, the agent, or the environment
— it just empties the store's contents. Re-run this before re-running
session 1 if you want a clean "no prior memory" moment.

Usage:
    python clear_memory.py            # asks for confirmation
    python clear_memory.py --yes      # skips confirmation
"""

import os
import sys
from pathlib import Path

from anthropic import Anthropic


def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("Set ANTHROPIC_API_KEY before running.")

    store_id_path = Path(".memory_store_id")
    if not store_id_path.exists():
        raise SystemExit("Missing .memory_store_id. Run create_agent.py first.")
    store_id = store_id_path.read_text().strip()

    client = Anthropic()

    page = client.beta.memory_stores.memories.list(store_id, path_prefix="/")
    items = [item for item in page.data if item.type == "memory"]

    if not items:
        print(f"Memory store {store_id} is already empty. Nothing to do.")
        return

    print(f"Memory store: {store_id}")
    print(f"Found {len(items)} entr{'y' if len(items) == 1 else 'ies'} to delete:")
    for item in items:
        print(f"  - {item.path}")

    if "--yes" not in sys.argv:
        confirm = input("\nDelete all of the above? [y/N] ").strip().lower()
        if confirm != "y":
            print("Aborted.")
            return

    for item in items:
        client.beta.memory_stores.memories.delete(item.id, memory_store_id=store_id)
        print(f"  deleted {item.path}")

    print("\nMemory store cleared.")
    print("Next: python run_session_1.py  (or use the dashboard's Run Live button)")


if __name__ == "__main__":
    main()
