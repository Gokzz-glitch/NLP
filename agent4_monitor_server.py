"""
Agent 4 - SSLLoopAgent Live Monitor Server
Serves a real-time dashboard at http://localhost:7774
"""
from http.server import HTTPServer, BaseHTTPRequestHandler
import sqlite3, json, os

DB_PATH = "knowledge_ledger.db"

def get_agent4_data():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as cnt FROM agent_logs WHERE agent_name='Agent4-SSLLoop'")
    total = cur.fetchone()["cnt"]
    cur.execute("SELECT * FROM agent_logs WHERE agent_name='Agent4-SSLLoop' ORDER BY id DESC LIMIT 15")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    for r in rows:
        try:
            r["content"] = json.loads(r["content"])
        except:
            pass
    return {"total": total, "findings": rows}

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Agent 4 – SSLLoopAgent Live Monitor</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --bg: #070b14;
    --surface: #0d1525;
    --surface2: #111d32;
    --border: #1e2f4d;
    --accent: #00d4ff;
    --accent2: #7c3aed;
    --accent3: #10b981;
    --warn: #f59e0b;
    --text: #e2e8f0;
    --muted: #64748b;
    --pulse: #00d4ff;
  }

  body {
    font-family: 'Inter', sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    overflow-x: hidden;
  }

  /* Animated grid background */
  body::before {
    content: '';
    position: fixed;
    inset: 0;
    background-image:
      linear-gradient(rgba(0,212,255,0.03) 1px, transparent 1px),
      linear-gradient(90deg, rgba(0,212,255,0.03) 1px, transparent 1px);
    background-size: 40px 40px;
    pointer-events: none;
    z-index: 0;
  }

  .container { max-width: 1200px; margin: 0 auto; padding: 24px; position: relative; z-index: 1; }

  /* HEADER */
  .header {
    display: flex; align-items: center; gap: 16px;
    padding: 20px 28px;
    background: linear-gradient(135deg, rgba(0,212,255,0.08), rgba(124,58,237,0.08));
    border: 1px solid var(--border);
    border-radius: 16px;
    margin-bottom: 24px;
    backdrop-filter: blur(10px);
    position: relative; overflow: hidden;
  }
  .header::before {
    content: '';
    position: absolute; top: 0; left: 0; right: 0; height: 2px;
    background: linear-gradient(90deg, var(--accent), var(--accent2));
  }
  .agent-badge {
    display: flex; align-items: center; justify-content: center;
    width: 56px; height: 56px; border-radius: 14px;
    background: linear-gradient(135deg, var(--accent), var(--accent2));
    font-size: 22px; font-weight: 700; color: #fff;
    flex-shrink: 0;
  }
  .header-info h1 { font-size: 22px; font-weight: 700; letter-spacing: -0.5px; }
  .header-info p { color: var(--muted); font-size: 13px; margin-top: 3px; }
  .status-pill {
    margin-left: auto; display: flex; align-items: center; gap: 8px;
    background: rgba(16,185,129,0.12); border: 1px solid rgba(16,185,129,0.3);
    padding: 6px 14px; border-radius: 999px; font-size: 13px; color: var(--accent3);
  }
  .live-dot {
    width: 8px; height: 8px; border-radius: 50%; background: var(--accent3);
    animation: pulse 1.5s infinite;
  }
  @keyframes pulse { 0%,100% { opacity:1; transform:scale(1); } 50% { opacity:0.5; transform:scale(0.8); } }

  /* STATS ROW */
  .stats-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 24px; }
  .stat-card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; padding: 18px 20px;
    display: flex; flex-direction: column; gap: 6px;
    transition: border-color 0.2s;
  }
  .stat-card:hover { border-color: var(--accent); }
  .stat-label { font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: var(--muted); }
  .stat-value { font-size: 28px; font-weight: 700; font-family: 'JetBrains Mono', monospace; }
  .stat-value.cyan { color: var(--accent); }
  .stat-value.purple { color: #a78bfa; }
  .stat-value.green { color: var(--accent3); }
  .stat-value.amber { color: var(--warn); }
  .stat-sub { font-size: 12px; color: var(--muted); }

  /* SECTION */
  .section-title {
    font-size: 13px; text-transform: uppercase; letter-spacing: 1.5px;
    color: var(--muted); margin-bottom: 12px; display: flex; align-items: center; gap: 8px;
  }
  .section-title::after {
    content: ''; flex: 1; height: 1px; background: var(--border);
  }

  /* FINDINGS LIST */
  .findings-list { display: flex; flex-direction: column; gap: 14px; margin-bottom: 28px; }
  .finding-card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 14px; padding: 20px 22px;
    transition: all 0.25s; position: relative; overflow: hidden;
  }
  .finding-card.newest { border-left: 3px solid var(--accent); }
  .finding-card:hover { border-color: rgba(0,212,255,0.4); transform: translateY(-1px); }
  .finding-card::before {
    content: '';
    position: absolute; top: 0; left: 0; bottom: 0; width: 1px;
    background: linear-gradient(180deg, var(--accent), transparent);
    opacity: 0;
    transition: opacity 0.25s;
  }
  .finding-card:hover::before { opacity: 1; }

  .finding-header { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; flex-wrap: wrap; }
  .finding-id {
    font-family: 'JetBrains Mono', monospace; font-size: 11px;
    background: rgba(0,212,255,0.08); color: var(--accent);
    padding: 2px 8px; border-radius: 5px; border: 1px solid rgba(0,212,255,0.2);
  }
  .finding-ts { font-size: 12px; color: var(--muted); font-family: 'JetBrains Mono', monospace; }
  .type-badge {
    font-size: 11px; padding: 2px 10px; border-radius: 5px;
    background: rgba(124,58,237,0.15); color: #a78bfa; border: 1px solid rgba(124,58,237,0.3);
    margin-left: auto;
  }
  .winner-badge {
    font-size: 11px; padding: 2px 10px; border-radius: 5px; text-transform: uppercase; letter-spacing: 0.5px;
  }
  .winner-badge.fallback { background: rgba(245,158,11,0.1); color: var(--warn); border: 1px solid rgba(245,158,11,0.25); }
  .winner-badge.live { background: rgba(16,185,129,0.1); color: var(--accent3); border: 1px solid rgba(16,185,129,0.25); }

  .finding-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
  .insight-block { background: var(--surface2); border-radius: 10px; padding: 14px; }
  .insight-block.full { grid-column: 1 / -1; }
  .insight-label {
    font-size: 10px; text-transform: uppercase; letter-spacing: 1px;
    color: var(--muted); margin-bottom: 8px; display: flex; align-items: center; gap: 6px;
  }
  .insight-label .dot { width: 6px; height: 6px; border-radius: 50%; }
  .dot-cyan { background: var(--accent); }
  .dot-purple { background: #a78bfa; }
  .insight-text {
    font-size: 13px; line-height: 1.6; color: #b0c0d8;
    font-family: 'Inter', sans-serif;
  }

  /* REFRESH */
  .refresh-bar {
    display: flex; align-items: center; gap: 12px;
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; padding: 12px 20px; margin-bottom: 24px;
  }
  .refresh-bar span { font-size: 13px; color: var(--muted); }
  #countdown { color: var(--accent); font-family: 'JetBrains Mono'; font-weight: 600; }
  .progress-track { flex: 1; height: 4px; background: var(--border); border-radius: 3px; overflow: hidden; }
  .progress-fill { height: 100%; background: linear-gradient(90deg, var(--accent), var(--accent2)); border-radius: 3px; transition: width 1s linear; }
  .refresh-btn {
    background: rgba(0,212,255,0.1); border: 1px solid rgba(0,212,255,0.3);
    color: var(--accent); padding: 6px 16px; border-radius: 8px; cursor: pointer;
    font-size: 13px; font-family: 'Inter'; transition: all 0.2s;
  }
  .refresh-btn:hover { background: rgba(0,212,255,0.2); }

  /* WATERMARK */
  .footer { text-align: center; color: var(--muted); font-size: 12px; padding: 16px 0 8px; border-top: 1px solid var(--border); }

  @media (max-width: 700px) {
    .stats-row { grid-template-columns: repeat(2, 1fr); }
    .finding-grid { grid-template-columns: 1fr; }
  }
</style>
</head>
<body>
<div class="container">

  <div class="header">
    <div class="agent-badge">A4</div>
    <div class="header-info">
      <h1>Agent 4 — SSLLoopAgent</h1>
      <p>SmartSalai Edge-Sentinel &nbsp;·&nbsp; system_orchestrator_v2.py &nbsp;·&nbsp; Cycle: every 35 seconds</p>
    </div>
    <div class="status-pill">
      <div class="live-dot"></div>
      LIVE
    </div>
  </div>

  <div class="refresh-bar">
    <span>Auto-refresh in <span id="countdown">30</span>s</span>
    <div class="progress-track"><div class="progress-fill" id="progressFill" style="width:100%"></div></div>
    <button class="refresh-btn" onclick="loadData()">⟳ Refresh Now</button>
  </div>

  <div class="stats-row">
    <div class="stat-card">
      <div class="stat-label">Total SSL Iterations</div>
      <div class="stat-value cyan" id="statTotal">—</div>
      <div class="stat-sub">Lifetime ledger entries</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Sleep Interval</div>
      <div class="stat-value purple">35s</div>
      <div class="stat-sub">Between evaluations</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Active Engine</div>
      <div class="stat-value green" style="font-size:16px; margin-top:4px;">Unified</div>
      <div class="stat-sub">G0DM0D3 + NotebookLM</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Last Winner Model</div>
      <div class="stat-value amber" id="statWinner" style="font-size:14px; margin-top:4px;">—</div>
      <div class="stat-sub">Most recent iteration</div>
    </div>
  </div>

  <div class="section-title">Recent SSL Strategy Findings</div>
  <div class="findings-list" id="findingsList">
    <div style="text-align:center;color:var(--muted);padding:40px;">Loading live data…</div>
  </div>

  <div class="footer">SmartSalai Edge-Sentinel &nbsp;|&nbsp; CoERS Hackathon 2026 &nbsp;|&nbsp; Agent 4 Live Monitor</div>
</div>

<script>
  let remaining = 30;
  let timer;

  async function loadData() {
    try {
      const res = await fetch('/api/agent4');
      const data = await res.json();
      renderData(data);
      resetCountdown();
    } catch(e) {
      console.error(e);
    }
  }

  function renderData(data) {
    document.getElementById('statTotal').textContent = data.total;
    const newest = data.findings[0];
    if (newest && newest.content) {
      const w = newest.content.winner_model || '—';
      document.getElementById('statWinner').textContent = w;
    }

    const list = document.getElementById('findingsList');
    if (!data.findings || data.findings.length === 0) {
      list.innerHTML = '<div style="text-align:center;color:var(--muted);padding:40px;">No findings yet.</div>';
      return;
    }

    list.innerHTML = data.findings.map((f, i) => {
      const c = f.content || {};
      const nlm = (c.notebooklm_insight || 'No data').substring(0, 450);
      const god = (c.godmod_strategy || 'No data').substring(0, 450);
      const winner = c.winner_model || '—';
      const isLive = winner !== 'local-fallback';
      const winnerClass = isLive ? 'live' : 'fallback';

      return `<div class="finding-card ${i===0 ? 'newest' : ''}">
        <div class="finding-header">
          <span class="finding-id">#${f.id}</span>
          <span class="finding-ts">${f.timestamp}</span>
          <span class="type-badge">${f.finding_type || 'ssl_strategy'}</span>
          <span class="winner-badge ${winnerClass}">${winner}</span>
        </div>
        <div class="finding-grid">
          <div class="insight-block">
            <div class="insight-label"><span class="dot dot-cyan"></span> NotebookLM Insight</div>
            <div class="insight-text">${escHtml(nlm)}${nlm.length>=450 ? '…':''}</div>
          </div>
          <div class="insight-block">
            <div class="insight-label"><span class="dot dot-purple"></span> G0DM0D3 Strategy</div>
            <div class="insight-text">${escHtml(god)}${god.length>=450 ? '…':''}</div>
          </div>
        </div>
      </div>`;
    }).join('');
  }

  function escHtml(t) {
    return String(t).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  function resetCountdown() {
    remaining = 30;
    clearInterval(timer);
    startCountdown();
  }

  function startCountdown() {
    timer = setInterval(() => {
      remaining--;
      document.getElementById('countdown').textContent = remaining;
      const pct = (remaining / 30) * 100;
      document.getElementById('progressFill').style.width = pct + '%';
      if (remaining <= 0) {
        clearInterval(timer);
        loadData();
      }
    }, 1000);
  }

  loadData();
</script>
</body>
</html>"""

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # suppress noise

    def do_GET(self):
        if self.path == '/api/agent4':
            data = get_agent4_data()
            body = json.dumps(data).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)
        else:
            body = HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)

if __name__ == "__main__":
    port = 7774
    server = HTTPServer(("localhost", port), Handler)
    print(f"Agent 4 Monitor running at http://localhost:{port}")
    print("Press Ctrl+C to stop.")
    server.serve_forever()
