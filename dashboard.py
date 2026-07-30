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


def fetch_source_docs() -> dict:
    """Read the actual round1/round2 markdown files fed to the agent as context."""
    result = {}
    for round_name, dir_path in (("round1", Path("synthetic-data/round1")), ("round2", Path("synthetic-data/round2"))):
        docs = []
        if dir_path.exists():
            for path in sorted(dir_path.glob("*.md")):
                docs.append({"name": path.name, "content": path.read_text()})
        result[round_name] = docs
    return result


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
    --bg: #f7f7f5;
    --panel: #ffffff;
    --border: #e5e3de;
    --text: #22201d;
    --muted: #78746c;
    --accent: #cc7a52;
    --accent2: #4d7fb0;
    --accent3: #3e9a68;
    --danger: #c0463e;
    --add-bg: #e7f5ec;
    --add-fg: #1e6b3f;
    --rem-bg: #fbeceb;
    --rem-fg: #a3352d;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    font-size: 15px;
  }
  header {
    padding: 18px 28px;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: var(--panel);
  }
  header h1 { font-size: 17px; margin: 0; font-weight: 600; }
  header .sub { color: var(--muted); font-size: 13px; margin-top: 3px; }
  .btn {
    background: var(--accent);
    color: white;
    border: none;
    padding: 8px 16px;
    border-radius: 7px;
    cursor: pointer;
    font-size: 13px;
    font-weight: 600;
    margin-left: 8px;
  }
  .btn.secondary { background: var(--panel); color: var(--text); border: 1px solid var(--border); }
  .btn.small { padding: 5px 12px; font-size: 12px; }
  .btn.ghost { background: transparent; color: var(--muted); border: 1px solid var(--border); }
  .btn:hover { opacity: 0.88; }
  .btn:disabled { opacity: 0.45; cursor: default; }

  .timeline {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 12px 28px;
    background: var(--panel);
    border-bottom: 1px solid var(--border);
    font-size: 12.5px;
    color: var(--muted);
    overflow-x: auto;
  }
  .timeline .step {
    padding: 5px 12px;
    border-radius: 14px;
    border: 1px solid var(--border);
    white-space: nowrap;
    background: var(--bg);
  }
  .timeline .step.done { color: var(--accent3); border-color: #bfe3cd; background: var(--add-bg); }
  .timeline .arrow { color: #cfccc4; }

  .tabs {
    display: flex;
    gap: 2px;
    padding: 0 28px;
    background: var(--panel);
    border-bottom: 1px solid var(--border);
  }
  .tab {
    padding: 12px 18px;
    font-size: 13.5px;
    font-weight: 600;
    color: var(--muted);
    cursor: pointer;
    border-bottom: 2px solid transparent;
    display: flex;
    align-items: center;
    gap: 7px;
  }
  .tab:hover { color: var(--text); }
  .tab.active { color: var(--text); border-bottom-color: var(--accent); }
  .tab .dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
  .dot.s1 { background: var(--accent2); }
  .dot.s2 { background: var(--accent3); }
  .dot.s3 { background: #9b6fc7; }
  .dot.mem { background: var(--accent); }
  .dot.diff { background: var(--danger); }
  .dot.sources { background: #9a8f6f; }
  .badge {
    background: var(--bg);
    color: var(--muted);
    font-size: 10.5px;
    padding: 2px 9px;
    border-radius: 10px;
    font-weight: 700;
    border: 1px solid var(--border);
  }

  main { padding: 24px 28px 40px; max-width: 980px; margin: 0 auto; }
  .view { display: none; }
  .view.active { display: block; }

  .card {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
  }
  .card-header {
    padding: 14px 20px;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .card-header .title { font-size: 14.5px; font-weight: 700; }
  .card-header .actions { display: flex; align-items: center; gap: 8px; }
  .card-body {
    padding: 22px 24px;
    line-height: 1.65;
    font-size: 14.5px;
  }
  .card-body.mono { font-family: ui-monospace, Menlo, monospace; font-size: 13px; white-space: pre-wrap; }

  .prose h1, .prose h2, .prose h3 { margin: 1.1em 0 0.4em; line-height: 1.3; }
  .prose h2 { font-size: 1.15em; }
  .prose h3 { font-size: 1.02em; }
  .prose p { margin: 0.6em 0; }
  .prose strong { color: var(--text); }
  .prose table { border-collapse: collapse; width: 100%; margin: 0.8em 0; font-size: 0.92em; }
  .prose th, .prose td { border: 1px solid var(--border); padding: 6px 10px; text-align: left; }
  .prose th { background: var(--bg); font-weight: 700; }
  .prose hr { border: none; border-top: 1px solid var(--border); margin: 1.2em 0; }
  .prose .callout {
    background: #fdf2ee;
    border-left: 3px solid var(--accent);
    padding: 10px 14px;
    border-radius: 6px;
    margin: 0.8em 0;
  }
  .prose ul, .prose ol { padding-left: 1.3em; }
  .placeholder { color: var(--muted); font-style: italic; }

  .agent-log {
    margin-top: 4px;
  }
  .agent-log summary {
    cursor: pointer;
    color: var(--muted);
    font-size: 12px;
    padding: 6px 0;
  }
  .agent-log .log-line {
    display: block;
    font-family: ui-monospace, Menlo, monospace;
    font-size: 11.5px;
    color: var(--muted);
    padding: 1px 0;
  }
  .agent-log .log-line.mem { color: var(--accent); }

  .diff-block { font-family: ui-monospace, Menlo, monospace; font-size: 12.5px; line-height: 1.7; }
  .diff-line-add { color: var(--add-fg); background: var(--add-bg); display: block; padding: 1px 6px; border-radius: 3px; }
  .diff-line-rem { color: var(--rem-fg); background: var(--rem-bg); display: block; padding: 1px 6px; border-radius: 3px; }
  .diff-line-ctx { color: var(--muted); display: block; padding: 1px 6px; }

  .mem-layout { display: grid; grid-template-columns: 200px 1fr; min-height: 400px; }
  .mem-list { border-right: 1px solid var(--border); }
  .mem-item {
    padding: 10px 16px;
    font-size: 13px;
    cursor: pointer;
    border-bottom: 1px solid var(--border);
    color: var(--muted);
  }
  .mem-item:hover, .mem-item.active { background: var(--bg); color: var(--text); font-weight: 600; }
  .mem-content { padding: 22px 24px; }

  ::-webkit-scrollbar { width: 8px; height: 8px; }
  ::-webkit-scrollbar-thumb { background: #d8d4cc; border-radius: 4px; }
</style>
</head>
<body>
<header>
  <div>
    <h1>Institutional Memory Agent — Demo Dashboard</h1>
    <div class="sub">Acme Corp / Customer Success scenario</div>
  </div>
  <div>
    <button class="btn secondary" onclick="loadStaticPanels()">Refresh</button>
  </div>
</header>

<div class="timeline" id="timeline"></div>

<div class="tabs" id="tabs">
  <div class="tab active" data-view="session1"><span class="dot s1"></span> Session 1</div>
  <div class="tab" data-view="session2"><span class="dot s2"></span> Session 2</div>
  <div class="tab" data-view="session3"><span class="dot s3"></span> What Changed?</div>
  <div class="tab" data-view="diff"><span class="dot diff"></span> Memory Diff <span class="badge" id="diff-badge">0</span></div>
  <div class="tab" data-view="memory"><span class="dot mem"></span> Live Memory</div>
  <div class="tab" data-view="sources"><span class="dot sources"></span> Source Documents</div>
</div>

<main>
  <div class="view active" id="view-session1">
    <div class="card">
      <div class="card-header">
        <div class="title">Session 1 — Baseline</div>
        <div class="actions"><button class="btn small" onclick="runLive('session1')">Run Live</button></div>
      </div>
      <div class="card-body prose" id="session1"><span class="placeholder">Loading...</span></div>
    </div>
  </div>

  <div class="view" id="view-session2">
    <div class="card">
      <div class="card-header">
        <div class="title">Session 2 — After Memory + New Context</div>
        <div class="actions"><button class="btn small" onclick="runLive('session2')">Run Live</button></div>
      </div>
      <div class="card-body prose" id="session2"><span class="placeholder">Loading...</span></div>
    </div>
  </div>

  <div class="view" id="view-session3">
    <div class="card">
      <div class="card-header">
        <div class="title">Session 3 — "What have you learned?"</div>
        <div class="actions"><button class="btn small" onclick="runLive('session3')">Run Live</button></div>
      </div>
      <div class="card-body prose" id="session3"><span class="placeholder">Not run yet — click Run Live.</span></div>
    </div>
  </div>

  <div class="view" id="view-diff">
    <div class="card">
      <div class="card-header">
        <div class="title">Memory Diff — Before &rarr; After Session 2</div>
        <div class="actions"><button class="btn small ghost" onclick="loadDiff()">Recompute</button></div>
      </div>
      <div class="card-body diff-block" id="diff-content">Run session 1, then session 2 (Run Live), then click Recompute.</div>
    </div>
  </div>

  <div class="view" id="view-memory">
    <div class="card">
      <div class="card-header">
        <div class="title">Live Memory Store</div>
      </div>
      <div class="mem-layout">
        <div class="mem-list" id="mem-list"></div>
        <div class="mem-content prose" id="mem-content">Loading...</div>
      </div>
    </div>
  </div>

  <div class="view" id="view-sources">
    <div class="card">
      <div class="card-header">
        <div class="title">Source Documents — What the Agent Reads</div>
        <div class="actions">
          <span class="badge" id="round-toggle-1" onclick="setRound('round1')" style="cursor:pointer;">Round 1</span>
          <span class="badge" id="round-toggle-2" onclick="setRound('round2')" style="cursor:pointer;">Round 2</span>
        </div>
      </div>
      <div class="mem-layout">
        <div class="mem-list" id="src-list"></div>
        <div class="mem-content mono" id="src-content">Loading...</div>
      </div>
    </div>
  </div>
</main>

<script>
let memoryItems = [];
let sourceDocs = {round1: [], round2: []};
let currentRound = 'round1';
let currentSrcItems = [];
const timelineSteps = [
  {key: 'round1', label: '1. Round 1 docs'},
  {key: 'session1', label: '2. Session 1'},
  {key: 'round2', label: '3. Round 2 docs'},
  {key: 'session2', label: '4. Session 2'},
  {key: 'session3', label: '5. What has it learned?'},
];

// --- Tabs ---
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById('view-' + tab.dataset.view).classList.add('active');
  });
});

// --- Minimal markdown-ish renderer (headers, bold, tables, hr, lists) ---
function renderMarkdown(text) {
  if (!text) return '<span class="placeholder">Nothing here yet.</span>';

  const lines = text.split('\\n');
  let html = '';
  let inTable = false;
  let tableRows = [];
  let inList = false;

  function flushTable() {
    if (!tableRows.length) return;
    const [headerRow, sepRow, ...bodyRows] = tableRows;
    const cells = row => row.split('|').map(c => c.trim()).filter((c, i, arr) => !(i === 0 && c === '') && !(i === arr.length - 1 && c === ''));
    let t = '<table><thead><tr>';
    cells(headerRow).forEach(c => t += `<th>${inlineMd(c)}</th>`);
    t += '</tr></thead><tbody>';
    bodyRows.forEach(r => {
      t += '<tr>';
      cells(r).forEach(c => t += `<td>${inlineMd(c)}</td>`);
      t += '</tr>';
    });
    t += '</tbody></table>';
    html += t;
    tableRows = [];
    inTable = false;
  }

  function inlineMd(s) {
    return s
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/\\*\\*(.+?)\\*\\*/g, '<strong>$1</strong>')
      .replace(/~~(.+?)~~/g, '<del>$1</del>')
      .replace(/`(.+?)`/g, '<code>$1</code>');
  }

  for (let raw of lines) {
    const line = raw;
    if (/^\\s*\\|.*\\|\\s*$/.test(line)) {
      inTable = true;
      tableRows.push(line);
      continue;
    } else if (inTable) {
      flushTable();
    }

    if (/^---+\\s*$/.test(line.trim())) { html += '<hr/>'; continue; }
    if (/^###\\s+/.test(line)) { html += `<h3>${inlineMd(line.replace(/^###\\s+/, ''))}</h3>`; continue; }
    if (/^##\\s+/.test(line)) { html += `<h2>${inlineMd(line.replace(/^##\\s+/, ''))}</h2>`; continue; }
    if (/^#\\s+/.test(line)) { html += `<h2>${inlineMd(line.replace(/^#\\s+/, ''))}</h2>`; continue; }

    if (/^\\s*[-*]\\s+/.test(line)) {
      if (!inList) { html += '<ul>'; inList = true; }
      html += `<li>${inlineMd(line.replace(/^\\s*[-*]\\s+/, ''))}</li>`;
      continue;
    } else if (inList) {
      html += '</ul>';
      inList = false;
    }

    if (line.trim() === '') { html += ''; continue; }

    // Callout for lines starting with a warning-ish marker
    if (/^\\s*(\\u26a0|Critical|IMPORTANT)/i.test(line)) {
      html += `<div class="callout">${inlineMd(line)}</div>`;
      continue;
    }

    html += `<p>${inlineMd(line)}</p>`;
  }
  if (inTable) flushTable();
  if (inList) html += '</ul>';
  return html;
}

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

function setSessionContent(elId, rawText) {
  const el = document.getElementById(elId);
  // Strip leading meta lines like "=== SESSION 1 ===" and "Question: ..." for readability
  const cleaned = rawText.replace(/^=== .+? ===\\nQuestion:.+?\\n\\n--- ANSWER ---\\n/s, '');
  el.innerHTML = renderMarkdown(cleaned);
}

async function loadStaticPanels() {
  document.getElementById('session1').innerHTML = '<span class="placeholder">Loading...</span>';
  document.getElementById('session2').innerHTML = '<span class="placeholder">Loading...</span>';
  document.getElementById('mem-content').innerHTML = '<span class="placeholder">Loading...</span>';

  const [s1, s2, s3, mem, src] = await Promise.all([
    fetch('/api/session/session1').then(r => r.json()),
    fetch('/api/session/session2').then(r => r.json()),
    fetch('/api/session/session3').then(r => r.json()),
    fetch('/api/memory').then(r => r.json()),
    fetch('/api/sources').then(r => r.json()),
  ]);

  if (s1.exists) setSessionContent('session1', s1.content);
  else document.getElementById('session1').innerHTML = '<span class="placeholder">Not run yet — click Run Live.</span>';

  if (s2.exists) setSessionContent('session2', s2.content);
  else document.getElementById('session2').innerHTML = '<span class="placeholder">Not run yet — click Run Live.</span>';

  if (s3.exists) setSessionContent('session3', s3.content);

  memoryItems = mem.items;
  renderMemList();
  if (memoryItems.length) selectMemItem(0);

  sourceDocs = src;
  setRound(currentRound);

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
  document.getElementById('mem-content').innerHTML = renderMarkdown(memoryItems[idx].content);
}

function setRound(round) {
  currentRound = round;
  document.getElementById('round-toggle-1').style.background = round === 'round1' ? 'var(--accent)' : '';
  document.getElementById('round-toggle-1').style.color = round === 'round1' ? 'white' : '';
  document.getElementById('round-toggle-2').style.background = round === 'round2' ? 'var(--accent)' : '';
  document.getElementById('round-toggle-2').style.color = round === 'round2' ? 'white' : '';

  currentSrcItems = sourceDocs[round] || [];
  renderSrcList();
  if (currentSrcItems.length) selectSrcItem(0);
  else document.getElementById('src-content').innerHTML = '<span class="placeholder">No documents in this round.</span>';
}

function renderSrcList() {
  const listEl = document.getElementById('src-list');
  listEl.innerHTML = '';
  currentSrcItems.forEach((item, idx) => {
    const div = document.createElement('div');
    div.className = 'mem-item' + (idx === 0 ? ' active' : '');
    div.textContent = item.name;
    div.onclick = () => selectSrcItem(idx);
    listEl.appendChild(div);
  });
}

function selectSrcItem(idx) {
  document.querySelectorAll('#src-list .mem-item').forEach((el, i) => {
    el.classList.toggle('active', i === idx);
  });
  document.getElementById('src-content').textContent = currentSrcItems[idx].content;
}

function runLive(sessionKey) {
  const el = document.getElementById(sessionKey);
  el.innerHTML = '';
  const btns = document.querySelectorAll(`button[onclick="runLive('${sessionKey}')"]`);
  btns.forEach(b => b.disabled = true);

  // Switch to that tab automatically
  document.querySelector(`.tab[data-view="${sessionKey}"]`)?.click();

  const logLines = [];
  let textBuffer = '';

  const logDetails = document.createElement('details');
  logDetails.className = 'agent-log';
  const summary = document.createElement('summary');
  summary.textContent = 'Agent actions (live)';
  logDetails.appendChild(summary);
  const logBody = document.createElement('div');
  logDetails.appendChild(logBody);
  el.appendChild(logDetails);

  const answerEl = document.createElement('div');
  el.appendChild(answerEl);

  const es = new EventSource(`/api/stream/${sessionKey}`);

  es.onmessage = (e) => {
    const evt = JSON.parse(e.data);
    if (evt.kind === 'status') {
      const line = document.createElement('span');
      line.className = 'log-line';
      line.textContent = evt.message;
      logBody.appendChild(line);
    } else if (evt.kind === 'tool') {
      const line = document.createElement('span');
      line.className = 'log-line' + (evt.is_memory ? ' mem' : '');
      line.textContent = `${evt.is_memory ? 'memory' : 'tool'}: ${evt.name} ${evt.target}`;
      logBody.appendChild(line);
    } else if (evt.kind === 'text') {
      textBuffer += evt.text;
      answerEl.innerHTML = renderMarkdown(textBuffer);
      el.scrollTop = el.scrollHeight;
    } else if (evt.kind === 'error') {
      const line = document.createElement('span');
      line.className = 'log-line';
      line.style.color = 'var(--danger)';
      line.textContent = 'ERROR: ' + evt.message;
      logBody.appendChild(line);
    } else if (evt.kind === 'done') {
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

  document.getElementById('diff-badge').textContent = data.change_count;

  if (!data.lines.length) {
    const p = document.createElement('div');
    p.className = 'placeholder';
    p.textContent = data.message || 'No diff available yet.';
    el.appendChild(p);
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


@app.route("/api/sources")
def api_sources():
    return jsonify(fetch_source_docs())


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
