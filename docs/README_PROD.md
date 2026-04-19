# SmartSalai Edge-Sentinel — Production Deployment Guide

This document outlines the steps to deploy the Edge-Sentinel system in a production-hardened state, ensuring maximum security and operational reliability (A to Z).

## 🛡️ Security Architecture

### 1. Web & API Security
- **Authentication**: All API requests require a `Bearer` token (found in `.dashboard_secret`).
- **Video Privacy**: The live cam feed is protected. Unauthorized access attempts are rejected with 401.
- **Rate Limiting**: IP-based leaky bucket protection is active (20 req burst, 0.5 req/s sustained) to prevent DoS.
- **Headers**: Strict CSP, HSTS, and X-Frame-Options are enforced.

### 2. Forensic Data Privacy
- **PII Masking**: The `KnowledgeLedger` automatically redacts GPS coordinates, phone numbers, and API keys before they touch the disk.
- **Data Integrity**: All findings are signed with HMAC-SHA256 to prevent offline tampering.

## 🚀 Deployment Steps

### Step 1: Resource Setup
Ensure the following directories are configured for low-latency I/O (SSD recommended):
- `G:\My Drive\NLP` (Model storage & large datasets)
- `~\SmartSalai_Local` (Local SQLite Knowledge Ledger)

### Step 2: Environment Variables
Create a `.env` file based on `.env.example`:
```bash
DASHBOARD_SECRET_KEY=yoursecret  # If omitted, one is auto-generated
FERNET_KEY=yourkey               # For Firebase credential encryption
ROBOFLOW_API_KEY=yourkey         # For Active Learning sync
```

For the primary production backend (`api.server:app`), also set:
- `INGEST_HMAC_SECRET`
- `FLEET_API_KEYS`
- `EDGE_SPATIAL_DB_PATH`
- `RAZORPAY_WEBHOOK_SECRET` (if webhook enabled)
- `API_ALLOWED_ORIGINS`

### Step 3: Launching the Watchdog
In production, do NOT run the scripts directly via `python`. Use the PowerShell watchdog to ensure auto-restart on failure:
1. Open PowerShell as Administrator.
2. Navigate to project root.
3. Run: `.\scripts\sentinel_service.ps1`


## 🩺 System Verification
- **Header Check**: `curl -I http://localhost:5555/`
- **Auth Check**: `curl http://localhost:5555/api/summary` (Should return 401 without token)
- **Log Audit**: Check `knowledge_ledger.db` for masked `[REDACTED_PII]` entries.

---

## 🚚 Fleet Pilot Validation Plan

**Objective:** Validate BLE mesh reliability, SQLite WAL concurrency, and legal DB automation in real-world fleet deployments before scaling.

**Steps:**
- Partner with 2–3 logistics fleets for a 30-day pilot.
- Instrument mesh and WAL for stress metrics (packet loss, event lag, DB lock rates).
- Collect feedback on dashboard usability, legal context accuracy, and support needs.
- Document all operational failures and iterate before broader rollout.

## 🛠️ Technical Roadmap: Scale & Automation

**Mesh/WAL Stress-Testing:**
- Simulate dense fleet environments (10–50 nodes) with moving vehicles.
- Benchmark BLE mesh packet delivery, TTL expiry, and deduplication under real noise.
- Load-test SQLite WAL with concurrent event writes and legal audit logs.
- Identify and address bottlenecks (DB locks, mesh partitioning, etc.).

**Legal DB Automation:**
- Build automated legal data sync pipeline (regulatory updates, jurisdiction changes).
- Integrate with public legal data sources and automate versioning.
- Add monitoring for stale/invalid legal references.

## 🏢 Centralized Ops, Compliance, and Support

- Implement centralized secret management and rotation (not just local env vars).
- Add audit logging for all API and dashboard actions.
- Prepare for GDPR/SOC2 compliance (data subject requests, breach notifications, etc.).
- Define 24/7 support SLAs and escalation paths for B2B customers.

---
