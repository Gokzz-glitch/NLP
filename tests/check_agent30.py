import sqlite3, json
c = sqlite3.connect('knowledge_ledger.db')
print("Checking for Agent30-CloudSync logs...")
rows = c.execute(
    "SELECT agent_name, finding_type, content FROM agent_logs WHERE agent_name='Agent30-CloudSync' ORDER BY id DESC LIMIT 5"
).fetchall()
if rows:
    for row in rows:
        print(f"[{row[0]}] {row[1]}: {row[2][:100]}...")
else:
    print("No Agent30 logs found. Checking most recent active agents:")
    recent = c.execute(
        "SELECT agent_name, MAX(timestamp) as ts FROM agent_logs GROUP BY agent_name ORDER BY ts DESC LIMIT 10"
    ).fetchall()
    for agent, ts in recent:
        print(f" - {agent} (Last seen: {ts})")
c.close()
