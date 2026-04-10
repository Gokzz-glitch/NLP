#!/usr/bin/env python3
import json
import urllib.request

for path in ("/api/summary", "/api/agents"):
    url = f"http://127.0.0.1:5555{path}"
    with urllib.request.urlopen(url, timeout=5) as r:
        data = json.loads(r.read().decode("utf-8", errors="ignore"))
    if path == "/api/summary":
        print("SUMMARY_TOTAL_LOGS=", data.get("total_logs"))
        print("SUMMARY_LAST_HOUR=", data.get("last_hour"))
    else:
        print("AGENTS_API_COUNT=", len(data))
        active = sum(1 for x in data if x.get("health") == "active")
        idle = sum(1 for x in data if x.get("health") == "idle")
        offline = sum(1 for x in data if x.get("health") == "offline")
        print("AGENTS_ACTIVE=", active)
        print("AGENTS_IDLE=", idle)
        print("AGENTS_OFFLINE=", offline)
