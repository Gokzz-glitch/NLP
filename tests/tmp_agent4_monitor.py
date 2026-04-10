import sqlite3
import json
import time
import sys

conn = sqlite3.connect("knowledge_ledger.db")
conn.row_factory = sqlite3.Row

print("=" * 70)
print("  LIVE MONITOR: Agent 4 - SSLLoopAgent")
print("  SmartSalai Edge-Sentinel | system_orchestrator_v2.py")
print("=" * 70)
print(f"  Sleep interval: 35s | Task: Evaluate SSL Curriculum")
print(f"  Engine: UnifiedResearchClient (G0DM0D3 + NotebookLM)")
print("=" * 70)
print()

cur = conn.cursor()
cur.execute("SELECT COUNT(*) as cnt FROM agent_logs WHERE agent_name='Agent4-SSLLoop'")
total = cur.fetchone()["cnt"]
print(f"  Total Agent4 findings in ledger: {total}")
print()

cur.execute("SELECT * FROM agent_logs WHERE agent_name='Agent4-SSLLoop' ORDER BY id DESC LIMIT 10")
rows = cur.fetchall()

print(f"  --- Last 10 Iterations ---")
print()
for r in rows:
    r = dict(r)
    try:
        c = json.loads(r.get("content", "{}"))
    except:
        c = {}
    
    nlm = str(c.get("notebooklm_insight", "N/A"))[:350]
    god = str(c.get("godmod_strategy", "N/A"))[:350]
    winner = c.get("winner_model", "N/A")
    
    print(f"  [{r['timestamp']}]  ID={r['id']}  type={r['finding_type']}")
    print(f"  winner_model      : {winner}")
    print(f"  notebooklm_insight: {nlm[:180]}...")
    print(f"  godmod_strategy   : {god[:180]}...")
    print()

conn.close()
