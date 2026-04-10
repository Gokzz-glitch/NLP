#!/usr/bin/env python3
import sqlite3

conn = sqlite3.connect("knowledge_ledger.db")
cur = conn.cursor()

recent = cur.execute(
    """
    SELECT agent_name, COUNT(*)
    FROM agent_logs
    WHERE timestamp >= datetime('now','-5 minutes')
    GROUP BY agent_name
    ORDER BY COUNT(*) DESC
    """
).fetchall()

print(f"RECENT_ACTIVE_AGENTS={len(recent)}")
for name, cnt in recent:
    print(f"{name}: {cnt}")

conn.close()
