import sqlite3, json
c = sqlite3.connect('knowledge_ledger.db')
print("Checking for Agent7 & Agent30 activity...")
for agent in ['Agent7-GPUThermal', 'Agent30-CloudSync']:
    rows = c.execute(
        "SELECT agent_name, finding_type, content, timestamp FROM agent_logs WHERE agent_name=? ORDER BY id DESC LIMIT 3",
        (agent,)
    ).fetchall()
    if rows:
        for row in rows:
            print(f"[{row[0]}] {row[1]} @ {row[3]}: {row[2][:100]}...")
    else:
        print(f"No logs for {agent}")
c.close()
