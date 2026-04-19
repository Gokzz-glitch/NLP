# Edge-Sentinel Production Readiness (No-Compromise Checklist)

## Primary Backend Entrypoint

- **Production API entrypoint:** `api.server:app`
- Start command:
  - `uvicorn api.server:app --host 0.0.0.0 --port 8000`
- `agent2_dashboard/api.py` remains available for dashboard-specific runtime, but deployment should treat `api.server:app` as the main backend contract.

## Configuration Standard

1. Copy `.env.example` to `.env`.
2. Set strong secrets (minimum 32 chars) for:
   - `CSRF_SECRET_KEY`
   - `DASHBOARD_SECRET_KEY`
   - `INGEST_HMAC_SECRET`
3. Set fleet auth token list in `FLEET_API_KEYS`.
4. Configure `EDGE_SPATIAL_DB_PATH` to durable storage.
5. Keep `API_USE_HTTPS=true` and `API_REQUIRE_HTTPS_REDIRECT=true` in TLS-terminated production.

## Data Reliability

- API persistence uses SQLite WAL in `api/storage.py`.
- Schema metadata is tracked in `api_schema_meta` (`schema_version`).
- Backup procedure:
  - Use `APIDatabase.backup_to(<path>)` before releases and before major migrations.
- Restore procedure:
  - Stop service.
  - Replace DB file atomically with known-good backup.
  - Restart and validate `/healthz` + `/api/metrics`.

## Security Baseline

- Internal ingest endpoint requires `X-Ingest-Signature` HMAC.
- Fleet hazards endpoint requires API token (`X-API-Key` or `Authorization: Bearer`).
- Payment webhook requires `RAZORPAY_WEBHOOK_SECRET` signature verification.
- Request IDs are generated/propagated through `X-Request-ID`.
- CORS is restricted through `API_ALLOWED_ORIGINS`.

## Observability Baseline

- `/healthz`: process and DB liveness.
- `/api/metrics`: event counts and schema version.
- Structured request and event logging emitted by `api/server.py`.

## CI/CD Gate

GitHub Actions workflow: `.github/workflows/ci.yml`

Required checks:
- Dependency install from `requirements/dev.txt`
- Python compile check (`compileall`)
- API smoke tests (`tests/test_api_server.py`)

## Staging Promotion Gate

1. Deploy image with staging `.env`.
2. Verify:
   - `GET /healthz` = 200
   - `GET /api/metrics` = 200
   - Signed ingest returns 201
   - Hazard query with valid token returns 200
3. Run CI green on branch + merge commit.
4. Take DB backup snapshot.
5. Promote same image digest to production.

## Rollback Runbook

1. Roll back container image to previous known-good digest.
2. Restore DB from pre-release backup if data migration was involved.
3. Validate health/metrics and one signed ingest round-trip.
4. Open incident record with request IDs and failure window.
