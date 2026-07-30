"""
Shared session-runner logic for the dashboard's live-streaming demo.

Wraps the same Managed Agents session pattern used in run_session_1.py /
run_session_2.py / run_session_3.py behind a generator so the Flask
dashboard can stream tokens and tool calls to the browser via
Server-Sent Events, instead of only reading finished outputs/*.txt files.

Also handles memory snapshotting (for the diff view) — before running a
session we snapshot the current memory store contents to
memory_snapshots/<name>_before.md, and after the session finishes we
snapshot to memory_snapshots/<name>_after.md.
"""

import json
from pathlib import Path
from typing import Iterator

from anthropic import Anthropic

OUTPUT_DIR = Path("outputs")
SNAPSHOT_DIR = Path("memory_snapshots")

TEST_QUESTION = (
    "Acme's CTO Sarah just emailed asking for a renewal proposal. What should "
    "we know going in?"
)

LEARNED_QUESTION = (
    "Don't answer any new question. Instead, summarize everything you have "
    "learned about Acme Corp across our previous sessions — contacts, contract "
    "status, open issues, and anything that changed between sessions. This is "
    "a memory recall test, not a new briefing."
)

SESSION_CONFIGS = {
    "session1": {
        "title": "Session 1 — baseline",
        "docs_dir": Path("synthetic-data/round1"),
        "question": TEST_QUESTION,
        "output_name": "session1.txt",
        "intro": (
            "I'm including our account history, contract, and support ticket "
            "documents for Acme Corp below. Please:\n"
            "1. First, check your memory store at /mnt/memory/ to see what you've "
            "learned in previous sessions.\n"
            "2. Then read the documents below.\n"
            "3. Then answer the question.\n"
            "4. Before you finish, save anything worth remembering to /mnt/memory/.\n\n"
        ),
        "memory_instructions": (
            "This is your persistent institutional memory. Mounted at "
            "/mnt/memory/. Check it before starting. Record what you learn for "
            "future sessions."
        ),
    },
    "session2": {
        "title": "Session 2 — after memory + new context",
        "docs_dir": Path("synthetic-data/round2"),
        "question": TEST_QUESTION,
        "output_name": "session2.txt",
        "intro": (
            "I'm including some updated and new documents below. Some of them "
            "contradict things you learned in our previous session.\n\n"
            "Please:\n"
            "1. First, check your memory store at /mnt/memory/ to see what you "
            "already know.\n"
            "2. Read the new documents below.\n"
            "3. Reconcile conflicts — UPDATE memory entries to reflect the "
            "newer information. Note dates.\n"
            "4. Answer the question.\n"
            "5. If your answer differs from your previous answer, lead with what "
            "changed and why.\n\n"
        ),
        "memory_instructions": (
            "This is your persistent institutional memory. Some entries may be "
            "out of date — reconcile against the new documents in this session "
            "and UPDATE existing entries (don't just append)."
        ),
    },
    "session3": {
        "title": "Session 3 — what have you learned?",
        "docs_dir": None,
        "question": LEARNED_QUESTION,
        "output_name": "session3.txt",
        "intro": "",
        "memory_instructions": (
            "This is your persistent institutional memory. No new documents "
            "are being provided in this session — answer purely from what's "
            "stored in /mnt/memory/."
        ),
    },
}


def load_docs_as_context(docs_dir: Path) -> str:
    if docs_dir is None:
        return ""
    blocks = []
    for path in sorted(docs_dir.glob("*.md")):
        blocks.append(f"=====  DOCUMENT: {path.name}  =====\n{path.read_text()}")
    return "\n\n".join(blocks)


def snapshot_memory(client: Anthropic, memory_store_id: str, label: str) -> str:
    """Fetch all memory content and write it to a snapshot file. Returns the text."""
    SNAPSHOT_DIR.mkdir(exist_ok=True)
    try:
        page = client.beta.memory_stores.memories.list(memory_store_id, path_prefix="/")
        items = sorted(page.data, key=lambda item: item.path)
        parts = []
        for item in items:
            if item.type != "memory":
                continue
            retrieved = client.beta.memory_stores.memories.retrieve(
                item.id, memory_store_id=memory_store_id
            )
            parts.append(f"--- {item.path} ---\n{retrieved.content or ''}")
        text = "\n\n".join(parts) if parts else "(memory store is empty)"
    except Exception as exc:  # noqa: BLE001
        text = f"(could not read memory store: {exc})"

    (SNAPSHOT_DIR / f"{label}.md").write_text(text)
    return text


def run_session_stream(session_key: str) -> Iterator[dict]:
    """
    Generator that runs a session against the live agent and yields dict
    events suitable for JSON-encoding over SSE:
        {"kind": "text", "text": "..."}
        {"kind": "tool", "name": "...", "target": "..."}
        {"kind": "status", "message": "..."}
        {"kind": "done", "final_text": "..."}
        {"kind": "error", "message": "..."}
    """
    config = SESSION_CONFIGS[session_key]

    for required in (".agent_id", ".environment_id", ".memory_store_id"):
        if not Path(required).exists():
            yield {"kind": "error", "message": f"Missing {required}. Run create_agent.py first."}
            return

    agent_id = Path(".agent_id").read_text().strip()
    environment_id = Path(".environment_id").read_text().strip()
    memory_store_id = Path(".memory_store_id").read_text().strip()

    client = Anthropic()

    yield {"kind": "status", "message": f"Snapshotting memory before {session_key}..."}
    snapshot_memory(client, memory_store_id, f"{session_key}_before")

    docs_dir = config["docs_dir"]
    if docs_dir is not None:
        yield {"kind": "status", "message": f"Loading docs from {docs_dir}/..."}
        for path in sorted(docs_dir.glob("*.md")):
            yield {"kind": "status", "message": f"  including {path.name}"}
        context = load_docs_as_context(docs_dir)
    else:
        context = ""

    yield {"kind": "status", "message": f"Starting session with memory store {memory_store_id}..."}

    session = client.beta.sessions.create(
        agent=agent_id,
        environment_id=environment_id,
        title=config["title"],
        resources=[
            {
                "type": "memory_store",
                "memory_store_id": memory_store_id,
                "access": "read_write",
                "instructions": config["memory_instructions"],
            }
        ],
    )

    user_message = (
        f"{config['intro']}{context}\n\n"
        "==================================================\n"
        f"QUESTION: {config['question']}"
    ).strip()

    final_text_parts: list[str] = []
    with client.beta.sessions.events.stream(session.id) as stream:
        client.beta.sessions.events.send(
            session.id,
            events=[
                {
                    "type": "user.message",
                    "content": [{"type": "text", "text": user_message}],
                }
            ],
        )
        for event in stream:
            if event.type == "agent.message":
                for block in event.content:
                    if getattr(block, "type", None) == "text":
                        final_text_parts.append(block.text)
                        yield {"kind": "text", "text": block.text}
            elif event.type == "agent.tool_use":
                name = getattr(event, "name", "?")
                inp = getattr(event, "input", {}) or {}
                target = inp.get("path") or inp.get("file_path") or inp.get("command") or ""
                yield {
                    "kind": "tool",
                    "name": name,
                    "target": str(target),
                    "is_memory": "/mnt/memory" in str(target),
                }
            elif event.type == "session.status_idle":
                break

    final_text = "".join(final_text_parts)
    OUTPUT_DIR.mkdir(exist_ok=True)
    out = OUTPUT_DIR / config["output_name"]
    out.write_text(
        f"=== {config['title'].upper()} ===\nQuestion: {config['question']}\n\n"
        f"--- ANSWER ---\n{final_text}\n"
    )

    yield {"kind": "status", "message": f"Snapshotting memory after {session_key}..."}
    snapshot_memory(client, memory_store_id, f"{session_key}_after")

    yield {"kind": "done", "final_text": final_text}
