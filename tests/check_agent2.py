import sqlite3, json
DB = r'g:/My Drive/NLP/knowledge_ledger.db'
conn = sqlite3.connect(DB)
c = conn.cursor()

c.execute("SELECT COUNT(*) FROM agent_logs WHERE agent_name='Agent2-ModelScout'")
total = c.fetchone()[0]

c.execute("SELECT id, timestamp, content FROM agent_logs WHERE agent_name='Agent2-ModelScout' ORDER BY timestamp DESC LIMIT 3")
rows = c.fetchall()

c.execute("SELECT agent_name, COUNT(*) as cnt, MAX(timestamp) as last FROM agent_logs GROUP BY agent_name ORDER BY last DESC")
agents = c.fetchall()
conn.close()

print(f"=== AGENT 2 STATS ===")
print(f"Total model_candidate findings: {total}")
print()
print("=== LATEST 3 FINDINGS ===")
for r in rows:
    content = json.loads(r[2])
    rec = content.get('notebooklm_recommendation','')[:250]
    print(f"  ID#{r[0]} | {r[1]}")
    print(f"  NotebookLM says: {rec}...")
    print(f"  Winner: {content.get('winner_model')}")
    print()

print("=== ALL AGENTS SUMMARY ===")
for a in agents:
    print(f"  {a[0]:30s}  {a[1]:4d} runs  |  last at {a[2]}")
