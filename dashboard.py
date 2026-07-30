"""
Demo Dashboard — a tiny local web UI for the two-minute demo.

Shows three panels side by side in the browser instead of three terminal
windows:
  - Session 1 answer (outputs/session1.txt)
  - Session 2 answer (outputs/session2.txt)
  - Live memory store contents (fetched from the Memory Store API, same
    data as `python inspect_memory.py --full`)

Usage:
    pip install flask   (already in requirements.txt)
    python dashboard.py
    open http://127.0.0.1:5050
"""

import os
from pathlib import Path

from flask import Flask, jsonify, render_template_string
from anthropic import Anthropic

app = Flask(__name__)

OUTPUTS_DIR = Path("outputs")
MEMORY_STORE_ID_PATH = Path(".memory_store_id")


def read_output(name: str) -> str:
    path = OUTPUTS_DIR / name
    if not path.exists():
        return f"(no {name} yet — run the corresponding session script first)"
    return path.read_text()


def fetch_memory() -> list[dict]:
    if not MEMORY_STORE_ID_PATH.exists():
        return [{"path": "(none)", "content": "Run create_agent.py first."}]

    store_id = MEMORY_STORE_ID_PATH.read_text().strip()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return [{"path": "(error)", "content": "ANTHROPIC_API_KEY not set."}]

    client = Anthropic(api_key=api_key)
    page = client.beta.memory_stores.memories.list(store_id, path_prefix="/")
    items = sorted(page.data, key=lambda item: item.path)

    results = []
    for item in items:
        if item.type != "memory":
            continue
        retrieved = client.beta.memory_stores.memories.retrieve(
            item.id, memory_store_id=store_id
        )
        results.append({"path": item.path, "content": retrieved.content or ""})
    return results or [{"path": "(empty)", "content": "Memory store has no entries yet."}]


PAGE_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Institutional Memory Agent — Demo Dashboard</title>
<style>
  :root {
    --bg: #0f1115;
    --panel: #171a21;
    --border: #2a2f3a;
    --text: #e6e8eb;
    --muted: #9aa3b2;
    --accent: #d97757;
    --accent2: #6aa5ff;
    --accent3: #7ee3a3;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }
  header {
    padding: 16px 24px;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  header h1 { font-size: 18px; margin: 0; font-weight: 600; }
  header .sub { color: var(--muted); font-size: 13px; margin-top: 2px; }
  button#refresh {
    background: var(--accent);
    color: white;
    border: none;
    padding: 8px 16px;
    border-radius: 6px;
    cursor: pointer;
    font-size: 13px;
    font-weight: 600;
  }
  button#refresh:hover { opacity: 0.9; }
  main {
    display: grid;
    grid-template-columns: 1fr 1fr;
    grid-template-rows: 1fr 320px;
    gap: 1px;
    background: var(--border);
    height: calc(100vh - 65px);
  }
  .panel {
    background: var(--panel);
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  .panel-title {
    padding: 10px 16px;
    font-size: 13px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .dot { width: 8px; height: 8px; border-radius: 50%; }
  .dot.s1 { background: var(--accent2); }
  .dot.s2 { background: var(--accent3); }
  .dot.mem { background: var(--accent); }
  .panel-body {
    padding: 16px;
    overflow-y: auto;
    font-size: 13px;
    line-height: 1.55;
    white-space: pre-wrap;
    flex: 1;
  }
  .memory-row {
    grid-column: 1 / span 2;
  }
  .memory-body {
    display: grid;
    grid-template-columns: minmax(160px, 220px) 1fr;
    overflow: hidden;
    flex: 1;
  }
  .mem-list {
    border-right: 1px solid var(--border);
    overflow-y: auto;
  }
  .mem-item {
    padding: 8px 14px;
    font-size: 12.5px;
    cursor: pointer;
    border-bottom: 1px solid var(--border);
    color: var(--muted);
  }
  .mem-item:hover, .mem-item.active {
    background: #1f232c;
    color: var(--text);
  }
  .mem-content {
    padding: 16px;
    overflow-y: auto;
    font-size: 12.5px;
    line-height: 1.6;
    white-space: pre-wrap;
  }
  .loading { color: var(--muted); font-style: italic; }
  ::-webkit-scrollbar { width: 8px; }
  ::-webkit-scrollbar-thumb { background: #333844; border-radius: 4px; }
</style>
</head>
<body>
<header>
  <div>
    <h1>Institutional Memory Agent — Demo Dashboard</h1>
    <div class="sub">Acme Corp / Customer Success scenario &middot; live memory store</div>
  </div>
  <button id="refresh" onclick="loadAll()">Refresh</button>
</header>
<main>
  <div class="panel">
    <div class="panel-title"><span class="dot s1"></span> Session 1 — Baseline</div>
    <div class="panel-body" id="session1">Loading...</div>
  </div>
  <div class="panel">
    <div class="panel-title"><span class="dot s2"></span> Session 2 — After Memory + New Context</div>
    <div class="panel-body" id="session2">Loading...</div>
  </div>
  <div class="panel memory-row">
    <div class="panel-title"><span class="dot mem"></span> Live Memory Store</div>
    <div class="memory-body">
      <div class="mem-list" id="mem-list"></div>
      <div class="mem-content" id="mem-content">Loading...</div>
    </div>
  </div>
</main>
<script>
let memoryItems = [];

async function loadAll() {
  document.getElementById('session1').textContent = 'Loading...';
  document.getElementById('session2').textContent = 'Loading...';
  document.getElementById('mem-content').textContent = 'Loading...';

  const [s1, s2, mem] = await Promise.all([
    fetch('/api/session1').then(r => r.json()),
    fetch('/api/session2').then(r => r.json()),
    fetch('/api/memory').then(r => r.json()),
  ]);

  document.getElementById('session1').textContent = s1.content;
  document.getElementById('session2').textContent = s2.content;

  memoryItems = mem.items;
  renderMemList();
  if (memoryItems.length) selectMemItem(0);
}

function renderMemList() {
  const listEl = document.getElementById('mem-list');
  listEl.innerHTML = '';
  memoryItems.forEach((item, idx) => {
    const div = document.createElement('div');
    div.className = 'mem-item' + (idx === 0 ? ' active' : '');
    div.textContent = item.path;
    div.onclick = () => selectMemItem(idx);
    listEl.appendChild(div);
  });
}

function selectMemItem(idx) {
  document.querySelectorAll('.mem-item').forEach((el, i) => {
    el.classList.toggle('active', i === idx);
  });
  document.getElementById('mem-content').textContent = memoryItems[idx].content;
}

loadAll();
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(PAGE_TEMPLATE)


@app.route("/api/session1")
def api_session1():
    return jsonify({"content": read_output("session1.txt")})


@app.route("/api/session2")
def api_session2():
    return jsonify({"content": read_output("session2.txt")})


@app.route("/api/memory")
def api_memory():
    return jsonify({"items": fetch_memory()})


if __name__ == "__main__":
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Warning: ANTHROPIC_API_KEY not set — memory panel will show an error.")
    print("\nDashboard running at http://127.0.0.1:5050\n")
    app.run(host="127.0.0.1", port=5050, debug=False)
