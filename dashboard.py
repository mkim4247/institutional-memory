"""
Demo Dashboard — a local web UI for the two-minute demo.

Now supports:
  - Live streaming runs of Session 1 / Session 2 / Session 3 ("what have you
    learned?") straight from the browser, via Server-Sent Events — no more
    pre-baked text only.
  - A memory diff view showing exactly what changed in the agent's memory
    file between session 1 and session 2 (Stretch S8).
  - A timeline strip showing where you are in the demo.
  - A "corrections" badge auto-counted from the memory diff.

Usage:
    python dashboard.py
    open http://127.0.0.1:5050
"""

import difflib
import json
import os
from pathlib import Path

from flask import Flask, Response, jsonify, render_template_string, stream_with_context
from anthropic import Anthropic

from session_lib import run_session_stream, SNAPSHOT_DIR, SESSION_CONFIGS

app = Flask(__name__)

OUTPUT_DIR = Path("outputs")
MEMORY_STORE_ID_PATH = Path(".memory_store_id")


def read_output(name: str) -> str:
    path = OUTPUT_DIR / name
    if not path.exists():
        return f"(no {name} yet — click Run Live above, or run the corresponding script)"
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
    --danger: #ff6b6b;
    --add: #2ea36b;
    --rem: #c04b4b;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }
  header {
    padding: 14px 24px;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  header h1 { font-size: 18px; margin: 0; font-weight: 600; }
  header .sub { color: var(--muted); font-size: 13px; margin-top: 2px; }
  .btn {
    background: var(--accent);
    color: white;
    border: none;
    padding: 7px 14px;
    border-radius: 6px;
    cursor: pointer;
    font-size: 12.5px;
    font-weight: 600;
    margin-left: 6px;
  }
  .btn.secondary { background: #2a2f3a; }
  .btn.small { padding: 4px 10px; font-size: 11.5px; }
  .btn:hover { opacity: 0.9; }
  .btn:disabled { opacity: 0.5; cursor: default; }

  .timeline {
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 10px 24px;
    background: #12141a;
    border-bottom: 1px solid var(--border);
    font-size: 12px;
    color: var(--muted);
  }
  .timeline .step {
    padding: 4px 10px;
    border-radius: 12px;
    border: 1px solid var(--border);
    white-space: nowrap;
  }
  .timeline .step.active { color: var(--text); border-color: var(--accent); background: #201a16; }
  .timeline .step.done { color: var(--accent3); border-color: #1e3a2c; }
  .timeline .arrow { color: var(--border); }

  main {
    display: grid;
    grid-template-columns: 1fr 1fr;
    grid-auto-rows: minmax(220px, 1fr);
    gap: 1px;
    background: var(--border);
  }
  .panel {
    background: var(--panel);
    display: flex;
    flex-direction: column;
    overflow: hidden;
    min-height: 240px;
  }
  .panel-title {
    padding: 9px 14px;
    font-size: 12.5px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    gap: 8px;
    justify-content: space-between;
  }
  .panel-title .left { display: flex; align-items: center; gap: 8px; }
  .dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
  .dot.s1 { background: var(--accent2); }
  .dot.s2 { background: var(--accent3); }
  .dot.s3 { background: #c99bff; }
  .dot.mem { background: var(--accent); }
  .dot.diff { background: var(--danger); }
  .badge {
    background: #2a2f3a;
    color: var(--text);
    font-size: 10.5px;
    padding: 2px 8px;
    border-radius: 10px;
    font-weight: 700;
  }
  .panel-body {
    padding: 14px;
    overflow-y: auto;
    font-size: 12.5px;
    line-height: 1.55;
    white-space: pre-wrap;
    flex: 1;
  }
  .row-full { grid-column: 1 / span 2; }
  .memory-body, .diff-body {
    display: grid;
    grid-template-columns: minmax(150px, 200px) 1fr;
    overflow: hidden;
    flex: 1;
  }
  .mem-list {
    border-right: 1px solid var(--border);
    overflow-y: auto;
  }
  .mem-item {
    padding: 8px 14px;
    font-size: 12px;
    cursor: pointer;
    border-bottom: 1px solid var(--border);
    color: var(--muted);
  }
  .mem-item:hover, .mem-item.active { background: #1f232c; color: var(--text); }
  .mem-content, .diff-content {
    padding: 14px;
    overflow-y: auto;
    font-size: 12px;
    line-height: 1.6;
    white-space: pre-wrap;
  }
  .diff-line-add { color: var(--add); background: rgba(46,163,107,0.08); display: block; }
  .diff-line-rem { color: var(--rem); background: rgba(192,75,75,0.08); display: block; }
  .diff-line-ctx { color: var(--muted); display: block; }
  .tool-tag { color: var(--muted); font-style: italic; display: block; margin: 2px 0; }
  .tool-tag.mem { color: var(--accent); }
  .status-tag { color: #6b7280; display: block; }
  ::-webkit-scrollbar { width: 8px; }
  ::-webkit-scrollbar-thumb { background: #333844; border-radius: 4px; }
</style>
</head>
<body>
<header>
  <div>
    <h1>Institutional Memory Agent — Demo Dashboard</h1>
    <div class="sub">Acme Corp / Customer Success scenario &middot; live sessions + live memory store</div>
  </div>
  <div>
    <button class="btn secondary" onclick="loadStaticPanels()">Refresh</button>
  </div>
</header>

<div class="timeline" id="timeline"></div>

<main>
  <div class="panel">
    <div class="panel-title">
      <div class="left"><span class="dot s1"></span> Session 1 — Baseline</div>
      <div>
        <button class="btn small" onclick="runLive('session1')">Run Live</button>
      </div>
    </div>
    <div class="panel-body" id="session1">Loading...</div>
  </div>

  <div class="panel">
    <div class="panel-title">
      <div class="left"><span class="dot s2"></span> Session 2 — After Memory + New Context</div>
      <div>
        <button class="btn small" onclick="runLive('session2')">Run Live</button>
      </div>
    </div>
    <div class="panel-body" id="session2">Loading...</div>
  </div>

  <div class="panel">
    <div class="panel-title">
      <div class="left"><span class="dot s3"></span> Session 3 — "What have you learned?"</div>
      <div>
        <button class="btn small" onclick="runLive('session3')">Run Live</button>
      </div>
    </div>
    <div class="panel-body" id="session3">(not run yet — click Run Live)</div>
  </div>

  <div class="panel">
    <div class="panel-title">
      <div class="left"><span class="dot diff"></span> Memory Diff — Session 1 &rarr; Session 2</div>
      <div>
        <span class="badge" id="diff-badge">0 changes</span>
        <button class="btn small" onclick="loadDiff()">Recompute</button>
      </div>
    </div>
    <div class="panel-body" id="diff-content">Run session 1 then session 2 (Run Live), then click Recompute.</div>
  </div>

  <div class="panel row-full">
    <div class="panel-title"><span class="dot mem"></span> Live Memory Store</div>
    <div class="memory-body">
      <div class="mem-list" id="mem-list"></div>
      <div class="mem-content" id="mem-content">Loading...</div>
    </div>
  </div>
</main>

<script>
let memoryItems = [];
const timelineSteps = [
  {key: 'round1', label: '1. Round 1 docs'},
  {key: 'session1', label: '2. Session 1'},
  {key: 'round2', label: '3. Round 2 docs'},
  {key: 'session2', label: '4. Session 2'},
  {key: 'session3', label: '5. What has it learned?'},
];

function renderTimeline(state) {
  const el = document.getElementById('timeline');
  el.innerHTML = '';
  timelineSteps.forEach((step, i) => {
    if (i > 0) {
      const arrow = document.createElement('span');
      arrow.className = 'arrow';
      arrow.textContent = '\\u2192';
      el.appendChild(arrow);
    }
    const div = document.createElement('div');
    const isDone = step.key === 'round1' || step.key === 'round2' || state[step.key];
    div.className = 'step' + (isDone ? ' done' : '');
    div.textContent = step.label + (isDone ? ' \\u2713' : '');
    el.appendChild(div);
  });
}

async function loadStaticPanels() {
  document.getElementById('session1').textContent = 'Loading...';
  document.getElementById('session2').textContent = 'Loading...';
  document.getElementById('mem-content').textContent = 'Loading...';

  const [s1, s2, s3, mem] = await Promise.all([
    fetch('/api/session/session1').then(r => r.json()),
    fetch('/api/session/session2').then(r => r.json()),
    fetch('/api/session/session3').then(r => r.json()),
    fetch('/api/memory').then(r => r.json()),
  ]);

  document.getElementById('session1').textContent = s1.content;
  document.getElementById('session2').textContent = s2.content;
  if (s3.exists) document.getElementById('session3').textContent = s3.content;

  memoryItems = mem.items;
  renderMemList();
  if (memoryItems.length) selectMemItem(0);

  renderTimeline({session1: s1.exists, session2: s2.exists, session3: s3.exists});
  loadDiff();
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

function runLive(sessionKey) {
  const panel = document.getElementById(sessionKey);
  panel.innerHTML = '';
  const btns = document.querySelectorAll(`button[onclick="runLive('${sessionKey}')"]`);
  btns.forEach(b => b.disabled = true);

  const es = new EventSource(`/api/stream/${sessionKey}`);

  es.onmessage = (e) => {
    const evt = JSON.parse(e.data);
    if (evt.kind === 'status') {
      const line = document.createElement('span');
      line.className = 'status-tag';
      line.textContent = evt.message;
      panel.appendChild(line);
    } else if (evt.kind === 'tool') {
      const line = document.createElement('span');
      line.className = 'tool-tag' + (evt.is_memory ? ' mem' : '');
      line.textContent = `[${evt.is_memory ? 'memory' : 'tool'}: ${evt.name} ${evt.target}]`;
      panel.appendChild(line);
    } else if (evt.kind === 'text') {
      const span = document.createElement('span');
      span.textContent = evt.text;
      panel.appendChild(span);
      panel.scrollTop = panel.scrollHeight;
    } else if (evt.kind === 'error') {
      const line = document.createElement('span');
      line.className = 'status-tag';
      line.style.color = 'var(--danger)';
      line.textContent = 'ERROR: ' + evt.message;
      panel.appendChild(line);
    } else if (evt.kind === 'done') {
      const line = document.createElement('span');
      line.className = 'status-tag';
      line.textContent = '\\n[agent finished]';
      panel.appendChild(line);
      es.close();
      btns.forEach(b => b.disabled = false);
      loadStaticPanels();
    }
  };

  es.onerror = () => {
    es.close();
    btns.forEach(b => b.disabled = false);
  };
}

async function loadDiff() {
  const res = await fetch('/api/diff/session2');
  const data = await res.json();
  const el = document.getElementById('diff-content');
  el.innerHTML = '';

  document.getElementById('diff-badge').textContent = `${data.change_count} changes`;

  if (!data.lines.length) {
    el.textContent = data.message || 'No diff available yet.';
    return;
  }

  data.lines.forEach(line => {
    const span = document.createElement('span');
    if (line.startsWith('+')) span.className = 'diff-line-add';
    else if (line.startsWith('-')) span.className = 'diff-line-rem';
    else span.className = 'diff-line-ctx';
    span.textContent = line;
    el.appendChild(span);
  });
}

loadStaticPanels();
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(PAGE_TEMPLATE)


@app.route("/api/session/<key>")
def api_session(key):
    config = SESSION_CONFIGS.get(key)
    if not config:
        return jsonify({"exists": False, "content": "Unknown session."})
    path = OUTPUT_DIR / config["output_name"]
    exists = path.exists()
    content = read_output(config["output_name"])
    return jsonify({"exists": exists, "content": content})


@app.route("/api/memory")
def api_memory():
    return jsonify({"items": fetch_memory()})


@app.route("/api/stream/<key>")
def api_stream(key):
    if key not in SESSION_CONFIGS:
        return jsonify({"error": "unknown session"}), 404

    def generate():
        try:
            for event in run_session_stream(key):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as exc:  # noqa: BLE001
            yield f"data: {json.dumps({'kind': 'error', 'message': str(exc)})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/diff/<key>")
def api_diff(key):
    before_path = SNAPSHOT_DIR / f"{key}_before.md"
    after_path = SNAPSHOT_DIR / f"{key}_after.md"

    if not before_path.exists() or not after_path.exists():
        return jsonify({
            "lines": [],
            "change_count": 0,
            "message": "Run this session live at least once to generate a memory snapshot diff.",
        })

    before = before_path.read_text().splitlines()
    after = after_path.read_text().splitlines()

    diff = list(difflib.unified_diff(before, after, lineterm="", n=1))
    # Drop the file-header lines (---, +++) from unified_diff for a cleaner view
    diff = [line for line in diff if not (line.startswith("---") or line.startswith("+++"))]
    change_count = sum(1 for line in diff if line.startswith("+") or line.startswith("-"))

    return jsonify({"lines": diff, "change_count": change_count})


if __name__ == "__main__":
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Warning: ANTHROPIC_API_KEY not set — memory panel and live runs will error.")
    print("\nDashboard running at http://127.0.0.1:5050\n")
    app.run(host="127.0.0.1", port=5050, debug=False, threaded=True)
