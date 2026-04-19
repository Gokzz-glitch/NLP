# SmartSalai Edge-Sentinel
## IIT Madras CoERS Hackathon 2026 - Judge Dossier

SmartSalai Edge-Sentinel is an offline-first road-safety stack that combines edge vision, legal-context reasoning, and V2X swarm coordination for low-connectivity Indian road environments.

### Mission
- Detect hazards in real time from an edge camera pipeline.
- Coordinate nearby vehicles over BLE mesh when cloud is unavailable.
- Preserve legal context and auditability using an on-device SQLite WAL ledger and RAG substrate.

## System Architecture

```mermaid
flowchart LR
    subgraph EDGE[Edge Compute Node (Laptop / Edge-NPU Runtime)]
        CAM[USB Camera Stream]
        VISION[Edge-NPU Vision Models\nYOLO Pothole / Traffic / Chaos]
        FUSION[Sensor + Event Fusion]
    end

    subgraph DATA[Local Data Plane]
        RAG[(SQLite WAL RAG DB\nLegal + Telemetry Ledger)]
        BUS[Agent Event Bus]
    end

    subgraph MESH[Offline V2X Plane]
        BLE[BLE Swarm Mesh Broker\nTTL + Storm Controls]
        PEERS[Nearby Nodes\nMotorcycle / Car Clients]
    end

    subgraph UI[Operator Interfaces]
        DASH[Dashboard API + Live Monitor]
        MOBILE[Expo Mobile Client]
    end

    CAM --> VISION --> FUSION --> BUS
    BUS <--> RAG
    BUS --> BLE --> PEERS
    BUS --> DASH
    DASH <--> MOBILE
```

## 43ms End-to-End Latency Benchmark

### Benchmark Claim
- Verified alert delivery path target: 43ms E2E at p95 under local bench conditions.

### Measurement Path
- Event emission on internal bus.
- API bridge websocket forward.
- Client receive and ACK.
- Roundtrip telemetry health capture.

### Reproducibility
Use the built-in benchmark runner:

```bash
python scripts/benchmark_alert_bridge_latency.py --host 127.0.0.1 --port 9876 --runs 200 --warmup 20 --pause-ms 1.0
```

The script reports:
- `p50_ms`, `p95_ms`, `p99_ms` for bridge delivery latency.
- ACK-based roundtrip metrics from bridge telemetry.

Reference implementation: `scripts/benchmark_alert_bridge_latency.py`.

## Core Technical Differentiators

### 1. Offline V2X Swarm Mesh
- BLE swarm relay with TTL control and dedupe logic.
- Designed for degraded connectivity and zero-cloud hazard propagation.

### 2. On-Device Legal + Telemetry State
- SQLite WAL-backed local persistence for resilient concurrent reads/writes.
- RAG-compatible storage layer for legal and operational context retrieval.

### 3. Edge Vision Safety Loop
- Real-time hazard inference from edge camera feeds.
- Production hooks for telemetry health, watchdogs, and graceful degradation.

## Security and Operations Posture
- Header-based auth for protected dashboard/video APIs.
- Environment-key enforcement for sensitive services.
- WAL database mode, lock-timeout strategies, and retry controls in critical paths.

## Judge Quick Start: Mobile App (Expo) in 3 Steps

### Step 1 - Install and enter app workspace
```bash
cd sentinel_app
npm install
```

### Step 2 - Start Expo over LAN
```bash
npx expo start --lan
```

### Step 3 - Open on phone
- Connect phone and laptop to the same network.
- Scan Expo QR with Expo Go.
- In-app settings, set backend websocket target to your laptop IP.

## Repository Highlights
- `agents/` - core autonomous agents and bridge layers.
- `agent2_dashboard/` - operator dashboard API and websocket surface.
- `api/` - **primary production backend API entrypoint** (`api.server:app`).
- `scripts/` - benchmarks, test harnesses, and deployment helpers.
- `sentinel_app/` - Expo mobile interface for field operation.

## Production Startup (Primary Backend)

```bash
uvicorn api.server:app --host 0.0.0.0 --port 8000
```

Production guide:
- `docs/PRODUCTION_READINESS.md`
- `.env.example`


## Reference Customers & Distribution Channels

### Reference Customers (Pilot Targets)
- [ ] FleetCo Logistics (Chennai)
- [ ] UrbanRider Express (Bangalore)
- [ ] TN State Transport (pending)

### Distribution Channels
- Direct B2B sales to logistics and fleet operators
- Channel partnerships with telematics integrators
- Pilot programs with government/municipal fleets

**Note:**
We are actively seeking real-world fleet pilots to validate BLE mesh reliability, WAL concurrency, and legal DB automation at scale. If you are a fleet operator or channel partner, contact us for early access and co-development opportunities.

---

## Real-World Validation & Next Steps

- All technical claims (mesh, WAL, legal RAG) will be validated in live fleet environments before scaling.
- Feedback from pilots will directly inform roadmap and product improvements.

---
    - Clones all three addons into local `addons/`
    - Supports refresh with `-Update`
- Firecrawl source seeding utility: `scripts/firecrawl_seed_sources.py`
    - Uses Firecrawl web search to append de-duplicated URLs into source files
    - Designed to feed your existing runtime source list workflow
- Integration guide: `docs/ADDONS_INTEGRATION.md`

### Setup Commands

Clone all addons:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_external_addons.ps1
```

Update all addons:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_external_addons.ps1 -Update
```

Install Firecrawl SDK:

```powershell
pip install firecrawl-py
```

Seed runtime sources with Firecrawl:

```powershell
$env:FIRECRAWL_API_KEY="fc-..."
python scripts/firecrawl_seed_sources.py --query "india pothole dashcam youtube" --limit 25 --output video_sources_youtube_runtime.txt
```

Run the unified addon improvement action (safe even without keys):

```powershell
python scripts/run_addon_improvements.py
```

This generates:
- `config/addon_source_queries.txt` (repeatable source-refresh query set)
- `reports/addon_improvement_status.json` (machine-readable run status)
- `reports/addon_improvement_action_*.md` (human-readable action report)

### Why This Improves the Model Loop

- Firecrawl improves data intake quality and freshness for SSL cycles (especially hard negatives and edge-case scenes).
- Everything Claude Code improves repeatability for agentic research and experiment loops.
- Google Cloud Generative AI repository gives production patterns for eval, RAG, and GenAI ops you can adapt.

## Status
Hackathon build is packaged for judge evaluation, live demo sequencing, and offline safety workflow validation.
