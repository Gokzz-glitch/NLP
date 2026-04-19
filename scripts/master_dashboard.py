import os
import sys
import json
import sqlite3
import logging
import psutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Inject root project directory to sys.path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)
from core.knowledge_ledger import DB_PATH

app = FastAPI(title="SmartSalai Master Dashboard")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv(
            "MASTER_DASHBOARD_ALLOWED_ORIGINS",
            os.getenv("ALLOWED_ORIGINS", "http://127.0.0.1:5556,http://localhost:5556"),
        ).split(",")
        if origin.strip()
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Status thresholds from dashboard_api.py
AGENT_INTERVALS = {
    "Agent1-IndustryResearch": 30,
    "Agent2-ModelScout": 45,
    "Agent3-CodeOpt": 60,
    "Agent4-SSLLoop": 35,
    "Agent5-RAG": 40,
    "Agent6-DatasetBench": 50,
    "Agent7-GPUThermal": 10,
    "Agent30-CloudSync": 30,
}

# --- Database Utilities ---

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def query_db(sql: str, params=()):
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logging.error(f"DB Error: {e}")
        return []

# --- Consolidated API Endpoints ---

@app.get("/api/summary")
async def get_summary():
    total = query_db("SELECT COUNT(*) as cnt FROM agent_logs")
    last_hour = query_db("SELECT COUNT(*) as cnt FROM agent_logs WHERE timestamp >= datetime('now', '-1 hour')")
    by_agent = query_db("SELECT agent_name, COUNT(*) as cnt FROM agent_logs GROUP BY agent_name ORDER BY cnt DESC")
    
    # System RAM monitor
    vmem = psutil.virtual_memory()
    
    return {
        "total_logs": total[0]["cnt"] if total else 0,
        "last_hour": last_hour[0]["cnt"] if last_hour else 0,
        "by_agent": {r["agent_name"]: r["cnt"] for r in by_agent},
        "db_size_kb": round(os.path.getsize(DB_PATH) / 1024, 1) if os.path.exists(DB_PATH) else 0,
        "ram_usage_pct": vmem.percent,
        "ram_available_gb": round(vmem.available / (1024**3), 1),
        "server_time": datetime.now().isoformat(),
    }

@app.get("/api/agents")
async def get_agents():
    now = datetime.now(timezone.utc)
    # We'll use a simplified version of the logic from dashboard_api.py
    # This serves the main 'all agents' status view.
    agents_data = []
    
    # Get all latest logs in one query
    latest_logs = query_db("""
        SELECT id, agent_name, timestamp, finding_type, content,
               (SELECT COUNT(*) FROM agent_logs al2 WHERE al2.agent_name = al1.agent_name) as total_count
        FROM agent_logs al1
        WHERE id IN (SELECT MAX(id) FROM agent_logs GROUP BY agent_name)
    """)
    
    log_map = {l["agent_name"]: l for l in latest_logs}
    
    # Define metadata for UI (Simplified from dashboard_api.py)
    META = {
        "Agent1-IndustryResearch": {"label": "Industry Research", "icon": "🔬", "color": "#6366f1"},
        "Agent2-ModelScout": {"label": "Model Scout", "icon": "🤖", "color": "#8b5cf6"},
        "Agent3-CodeOpt": {"label": "Code Optimizer", "icon": "⚡", "color": "#06b6d4"},
        "Agent4-SSLLoop": {"label": "SSL Loop", "icon": "🔄", "color": "#10b981"},
        "Agent5-RAG": {"label": "RAG Tuner", "icon": "📚", "color": "#f59e0b"},
        "Agent6-DatasetBench": {"label": "Dataset Bench", "icon": "🗃️", "color": "#ef4444"},
        "Agent7-GPUThermal": {"label": "GPU Thermal", "icon": "🌡️", "color": "#f97316"},
        "Agent30-CloudSync": {"label": "Cloud Sync (Colab)", "icon": "☁️", "color": "#38bdf8"},
    }

    for agent_id, meta in META.items():
        log = log_map.get(agent_id, {})
        interval = AGENT_INTERVALS.get(agent_id, 30)
        
        status = "offline"
        elapsed = None
        if log:
            try:
                # Normalise timestamp for comparison
                ts_str = log["timestamp"].replace(" ", "T")
                if not ts_str.endswith("Z") and "+" not in ts_str: ts_str += "+00:00"
                dt = datetime.fromisoformat(ts_str)
                if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
                elapsed = (now - dt).total_seconds()
                
                if elapsed < interval * 3: status = "active"
                elif elapsed < interval * 10: status = "idle"
            except: pass

        agents_data.append({
            "id": agent_id,
            "label": meta["label"],
            "icon": meta["icon"],
            "color": meta["color"],
            "health": status,
            "total_logs": log.get("total_count", 0),
            "last_seen": log.get("timestamp"),
            "elapsed_secs": round(elapsed, 1) if elapsed is not None else None,
            "last_type": log.get("finding_type"),
            "last_content": json.loads(log["content"]) if log.get("content") else {}
        })
    return agents_data

@app.get("/api/logs")
async def get_logs(limit: int = 60):
    rows = query_db("SELECT id, agent_name as agent, timestamp, finding_type as type, content FROM agent_logs ORDER BY id DESC LIMIT ?", (limit,))
    for r in rows:
        try: r["content"] = json.loads(r["content"])
        except: r["content"] = {}
    return rows

# --- Agent 2 Specific Routes ---

@app.get("/api/agent2/findings")
async def get_agent2_findings(limit: int = 20):
    rows = query_db("SELECT id, agent_name, timestamp, finding_type, content FROM agent_logs WHERE agent_name = 'Agent2-ModelScout' ORDER BY timestamp DESC LIMIT ?", (limit,))
    findings = []
    for r in rows:
        c = json.loads(r["content"])
        findings.append({
            "id": r["id"],
            "timestamp": r["timestamp"],
            "topic": c.get("topic", "Edge Vision Models"),
            "notebooklm_recommendation": c.get("notebooklm_recommendation", ""),
            "godmod_validation": c.get("godmod_validation", ""),
            "winner_model": c.get("winner_model", "local-fallback")
        })
    return {"findings": findings}

# --- Agent 4 Specific Routes ---

@app.get("/api/agent4")
async def get_agent4_data():
    total = query_db("SELECT COUNT(*) as cnt FROM agent_logs WHERE agent_name='Agent4-SSLLoop'")[0]["cnt"]
    rows = query_db("SELECT * FROM agent_logs WHERE agent_name='Agent4-SSLLoop' ORDER BY id DESC LIMIT 15")
    for r in rows:
        try: r["content"] = json.loads(r["content"])
        except: pass
    return {"total": total, "findings": rows}

# --- Page Server ---

@app.get("/", response_class=HTMLResponse)
async def serve_main():
    path = os.path.join(ROOT_DIR, "dashboard", "index.html")
    with open(path, encoding="utf-8") as f:
        html = f.read()
    return HTMLResponse(content=html)

@app.get("/agent2", response_class=HTMLResponse)
async def serve_agent2():
    path = os.path.join(ROOT_DIR, "agent2_dashboard", "index.html")
    # Fix relative manifest/fetch calls in the HTML to point to this new root
    with open(path, encoding="utf-8") as f:
        html = f.read()
    return HTMLResponse(content=html)

@app.get("/agent4", response_class=HTMLResponse)
async def serve_agent4():
    # Agent 4's HTML was embedded in the script, we'll need to extract it or use a simplified version
    from agent4_monitor_server import HTML as agent4_html
    return HTMLResponse(content=agent4_html)

if __name__ == "__main__":
    import uvicorn
    # Single Port 5556 handles EVERYTHING now (Moved from 5555 due to conflict)
    uvicorn.run(app, host="0.0.0.0", port=5556, log_level="info")
