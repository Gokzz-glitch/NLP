# PHASE 5 DEPLOYMENT OPERATIONS MANUAL
## SmartSalai Edge-Sentinel v1.2.1 → Production Deployment SOP

**Document Version**: 1.0  
**Effective Date**: 2026-03-15  
**Last Updated**: {{TODAY}}  
**Owner**: Project Lead + Safety Officer  
**Classification**: Operational

---

## 1. EXECUTIVE SUMMARY

This manual outlines the complete operational procedures for deploying SmartSalai Edge-Sentinel v1.2.1 from Phase 5 validation into production across the Chennai metropolitan area.

### Key Deployment Artifacts
- **5 Critical Code Fixes**: BLE broker (h_idx, dedupe), swarm bridge (DB locking), audit assertions, heartbeat routing
- **Validation Framework**: Unit tests (14+ required passes), load tests (18-node stable), sensor calibration protocol
- **Field Test Plan**: 7-day shadow mode (2 riders), 6 days data collection, day 7 go/no-go decision
- **Production Monitoring**: Real-time SLO compliance checking, weekly maintenance tasks, escalation procedures

### Success Criteria
All of the following must be **GREEN** before proceeding to production fleet expansion:
- ✅ Phase 5 unit tests pass (100%)
- ✅ Load test stable at 18 nodes, <10ms p95 latency
- ✅ Field test positive results (≥85% accuracy, <5% FP, <2% FN critical)
- ✅ No system crashes during shadow mode (7 days)
- ✅ iRAD audit trail continuous and consistent
- ✅ Safety officer sign-off on all pre-deployment checklists

---

## 2. PRE-DEPLOYMENT PHASE (Days 1-3)

### 2.1 Code Deployment & Unit Testing

**Who**: DevOps Engineer  
**Duration**: 2 hours  
**Acceptance**: All 14+ unit tests pass  

```bash
# Step 1: Deploy code fixes from staging
git checkout phase-5-fixes
git merge --no-ff main
git push origin main

# Step 2: Run unit test suite
python -m pytest tests/test_phase5_fixes.py -v
# Expected: 14+ PASSED, 0 FAILED

# Step 3: Verify all modules import without errors
python -c "
from agents.ble_mesh_broker import BLEMeshBroker
from agents.swarm_bridge import process_swarm_payload
from scripts.production_audit import ProductionAuditor
from system_orchestrator import MachaOrchestrator
print('✅ All modules imported successfully')
"

# Checkpoint: Sign-off that unit tests pass
# [ ] Unit tests passed (record timestamp)
```

### 2.2 Hardware Validation & Sensor Calibration

**Who**: Hardware Technician + Calibration SW  
**Duration**: 4 hours per vehicle  
**Vehicles**: CH-2026-001, CH-2026-002 (pilot)  

```bash
# Step 1: Mount camera and IMU on each pilot vehicle
# Verify rigidity: no motion >0.5G under normal road vibration

# Step 2: Run sensor calibration protocol
python scripts/phase5_sensor_calibration.py CH-2026-001

# Expected output:
# - config/camera_intrinsics_CH-2026-001.json
# - config/camera_extrinsics_CH-2026-001.json
# - config/imu_calibration_CH-2026-001.json
# - logs/calibration_report_CH-2026-001.md

# Step 3: Validate calibration quality
# - Intrinsic reprojection error < 0.5 pixels
# - Extrinsic lever arm error < 2cm
# - IMU bias < 0.05 m/s²
# - Time sync skew < 10ms

# Checkpoint: Calibration sign-off
# [ ] CH-2026-001 calibrated and verified
# [ ] CH-2026-002 calibrated and verified
```

### 2.3 Pre-Deployment System Checklist

**Who**: Tech Lead  
**Duration**: 1 hour  

- [ ] All Phase 5 code fixes verified in git history
- [ ] Unit tests 100% passing
- [ ] Load test results reviewed (18-node stable, <10ms p95)
- [ ] Sensor calibration complete for all pilot vehicles
- [ ] iRAD audit trail initialized and tested
- [ ] DriveLegal violation logic operational end-to-end
- [ ] Emergency stop procedure tested and working
- [ ] Backup systems in place (fallback to SMS, restart protocol)
- [ ] Legal/insurance review completed
- [ ] Safety officer approved deployment

**Sign-off**: 
```
Tech Lead Approval: ______________________ Date: ______
Safety Officer Approval: ______________________ Date: ______
```

---

## 3. FIELD TEST PHASE (Days 4-10)

### 3.1 Shadow Mode Deployment (Days 4-10)

**Duration**: 7 days  
**Riders**: 2 pilot motorcycles (CH-2026-001, CH-2026-002)  
**Route**: Chennai metropolitan area (Arterial → Mixed → Dense)  
**Mode**: SHADOW (alerts recorded but NOT broadcast to public)  

#### Day 1: Arterial Roads (OMR, CIT Road, Outer Ring)
- **Distance**: 50 km
- **Driver Action**: Record all detection events, note false positives manually
- **Metrics**: Accuracy, FP rate, network uptime
- **Contingency**: If >10% FP rate detected, reduce confidence threshold and retest

#### Day 2: Night Run (8 PM - 10 PM)
- **Distance**: 30 km
- **Driver Action**: Note any vision degradation under low light
- **Metrics**: Night accuracy vs day, GPS drift
- **Contingency**: If night accuracy <70%, increase exposure time and retest

#### Day 3: Wet/Rain Run
- **Distance**: 30 km
- **Driver Action**: Note any spurious alerts from rain
- **Metrics**: Wet surface detection accuracy
- **Contingency**: If rain causes >8% FP spike, tune vision preprocessing

#### Day 4: Violation Detection (Helmet/Speed)
- **Distance**: 40 km
- **Driver Action**: Test helmet detection (one rider with, one without); note detection timing
- **Metrics**: Violation detection accuracy, DriveLegal verdict correctness
- **Contingency**: If accuracy <80%, enhance DriveLegal ML feature extraction

#### Day 5: Network Stress (Swarm Formation)
- **Distance**: 10 km (tight 100m spacing between riders)
- **Driver Action**: Intent relay storm; monitor BLE relay traffic on dashboard
- **Metrics**: Relay drop rate, DB lock rate, mesh collisions
- **Contingency**: If drop rate >8%, reduce mesh density (space riders further apart)

#### Day 6: Extended Robustness (100 km mixed)
- **Distance**: 100 km (arterial + inner + flyover + residential)
- **Driver Action**: Monitor system for crashes, freezes, thermal throttling
- **Metrics**: System stability over long run, memory leak signature, CPU profile
- **Contingency**: If thermal throttle detected, reduce model complexity or increase cooling

#### Day 7: Analysis & Go/No-Go
- **Duration**: Team review & analysis
- **Action**: Aggregate 6 days of logs, calculate aggregate metrics, make deployment decision
- **Go Criteria**: All metrics meet SLO thresholds (see Section 2.1 Pre-Deployment)
- **No-Go Criteria**: 3+ critical issues remain, or crash detected

### 3.2 Daily Ritual (Repeat Each Day)

**Before Ride (30 min)**:
```bash
# 1. Check system health
python scripts/post_deployment_monitor.py --vehicle CH-2026-001

# 2. Verify all processes running
ps aux | grep -E 'ble_mesh_broker|swarm_bridge|system_orchestrator'

# 3. Check DB integrity
sqlite3 data/sentinel.db "PRAGMA integrity_check;"

# 4. Clear logs (keep <1GB)
# Compress logs older than 30 days
find logs -name '*.log' -mtime +30 -exec gzip {} \;

# 5. Final safety check
echo "✅ All systems ready for deployment"
```

**During Ride (Continuous)**:
- Dashboard monitors: Network uptime, detection accuracy, relay traffic
- Driver notes: Any unusual behavior, false positives/negatives
- Log collection: Automatic to `logs/hazard_detection_*.json`

**After Ride (1 hour)**:
```bash
# 1. Collect metrics from this run
tail -20 logs/ssl_verify_*.log

# 2. Quick SLO check
grep -c "database is locked" logs/*.log

# 3. Verify ground truth submission
ls -lt logs/ground_truth_markers_*.json | head -1

# 4. Backup logs to secondary storage
cp -r logs /backup/logs_$(date +%Y%m%d_%H%M%S)

echo "✅ Post-ride checks complete"
```

### 3.3 Field Test Data Submission

**Per-Ride Deliverables**:
- `logs/hazard_detection_{TIMESTAMP}.json` - Detection events with timestamps, coords, confidence
- `logs/network_metrics_{TIMESTAMP}.json` - BLE relay stats, DB lock events, mesh topology
- `logs/system_health_{TIMESTAMP}.json` - CPU%, RAM usage, thermal data
- `logs/driver_feedback.md` - Subjective notes on false positives, false negatives, system behavior

**Daily Aggregation**:
```json
{
  "day": 1,
  "phase": "Shadow Mode - Day 1",
  "date": "2026-03-15",
  "hazard_metrics": {
    "total_detections": 47,
    "matched_ground_truth": 42,
    "accuracy": 0.894,
    "false_positives": 3,
    "false_negatives": 2
  },
  "network_metrics": {
    "uptime": 0.997,
    "db_lock_events": 2,
    "relay_drop_rate": 0.012,
    "mesh_node_count_max": 2
  },
  "system_health": {
    "crashes": 0,
    "thermal_throttling_events": 0,
    "memory_growth_mb": 12
  },
  "driver_feedback": "No critical issues. One false positive on speed bump (resolved by increased confidence threshold)."
}
```

### 3.4 Go/No-Go Decision Framework (Day 7)

**PASS Criteria (Proceed to Fleet Expansion)**:
- ✅ Hazard accuracy ≥85% (vs ground truth)
- ✅ FP rate <5%, FN rate on critical <2%
- ✅ Network uptime ≥99%
- ✅ DB lock rate <10%, relay drop <5%
- ✅ Zero crashes in 7 days
- ✅ Memory growth <50 MB/day
- ✅ iRAD audit trail continuous
- ✅ DriveLegal violation logic end-to-end working
- ✅ Driver feedback non-negative

**CONDITIONAL Criteria (Pause & Retest)**:
- ⚠️  1-2 minor issues (e.g., FP rate 5.2%, one non-fatal crash day 6)
- ⚠️  Action: Fix + 3-day retest on subset
- Expected outcome: PASS within 3 days

**FAIL Criteria (Abort to Investigation)**:
- ❌ 3+ critical issues remain
- ❌ Crashes detected >1 per day
- ❌ Accuracy <80%
- Action: Root cause analysis, roll back Phase 5 changes, investigate, redeploy after fixes

---

## 4. PRODUCTION PHASE (Post-Field Test)

### 4.1 Phased Fleet Expansion

If **Field Test PASSED** on Day 7, proceed with phased rollout:

| Phase | Timeline | Fleet Size | Action |
|-------|----------|-----------|--------|
| Phase 5A | Weeks 1-2 | 5 riders (CH-2026-001 to 005) | Shadow mode, collect metrics |
| Phase 5B | Weeks 3-4 | 15 riders (CH-2026-001 to 015) | Alert broadcast enabled |
| Phase 5C | Weeks 5-8 | 50 riders (fleet-wide) | Full production, public service |

### 4.2 Production Monitoring Loop

**Run Continuously** (once every 24 hours):
```bash
python scripts/post_deployment_monitor.py --vehicle CH-2026-001 --db data/sentinel.db

# Expected output: JSON report with all SLO metrics
# If any metric FAILS, escalate immediately
```

**Weekly Review** (Every Monday):
```bash
# Review all SLO reports from past week
find logs/monitoring -name "slo_report_*.json" -mtime -7 -exec cat {} \;

# Generate trend report
python scripts/phase5_deployment_executor.py --vehicle CH-2026-001 --gen-runbook > TREND_REPORT_WEEK.md

# Update maintenance schedule
python scripts/post_deployment_monitor.py --gen-schedule
```

### 4.3 Escalation Protocol

If any SLO violated:

**Severity: CRITICAL** (Network Uptime <99%, Crashes >0, Accuracy <85%)
1. Page on-call engineer immediately
2. Stop public broadcasts (shadow mode only)
3. Investigate root cause within 4 hours
4. If not fixable within 8 hours, roll back Phase 5 changes
5. Root cause analysis + permanent fix required before re-deployment

**Severity: HIGH** (FP rate >5%, DB lock >10%, Memory leak >50MB/day)
1. Create incident ticket within 1 hour
2. Schedule emergency fix (dev + QA + deployment)
3. Deploy hot-fix within 24 hours
4. Continue operations with enhanced monitoring

**Severity: MEDIUM** (FP rate 4.5-5%, Relay drop 4-5%)
1. File issue for next sprint
2. Continue normal monitoring
3. May require model tuning or config adjustment

### 4.4 System Health Dashboard

Maintain real-time visibility:
```
SmartSalai Production Dashboard
================================
Network Uptime:        ██████████ 99.8% ✅
Hazard Accuracy:       ███████░░░ 84.2% ⚠️  (target 85%)
False Positive Rate:    ████░░░░░░ 4.1% ✅
False Negative Rate:    ░░░░░░░░░░ 0.8% ✅
DB Lock Rate:          █░░░░░░░░░ 1.2% ✅
Relay Drop Rate:       ░░░░░░░░░░ 0.3% ✅
System Crashes:        █░░░░░░░░░ 1 (Day 5, resolved) ⚠️
Temperature:           ███░░░░░░░ 38°C ✅
Memory Usage:          ██░░░░░░░░ 256MB ✅

Last Updated: 2026-03-22 14:32:15 UTC
Active Vehicles: 5 (CH-2026-001 to 005)
Next Escalation Review: 2026-03-23 09:00 UTC
```

---

## 5. MAINTENANCE & OPERATIONS

### 5.1 Weekly Tasks

**Every Monday 10 AM**:
- [ ] Rotate logs (compress >30 days old, archive to cold storage)
- [ ] Verify iRAD audit trail completeness (no gaps >1 hour)
- [ ] Check memory leak trends (graph last 30 days growth)
- [ ] Review exception logs for recurring patterns

### 5.2 Monthly Tasks

**1st of each month**:
- [ ] Recalibrate camera intrinsics (environmental drift correction)
- [ ] Audit ground truth submissions for quality
- [ ] Update threat intelligence (DriveLegal rules, new violation categories)
- [ ] Review thermal profile, adjust fan curves if needed
- [ ] Generate compliance report for legal/insurance

### 5.3 Quarterly Tasks

**Quarterly (Jan, Apr, Jul, Oct)**:
- [ ] Full sensor recalibration (camera + IMU + time sync)
- [ ] Revalidate ML model if accuracy trend <85%
- [ ] Security audit (check for unauthorized code, verify iRAD signatures)
- [ ] Legal compliance audit (complete iRAD trail, DriveLegal verdict completeness)

### 5.4 Incident Response

**For Any Field Incident** (crash, behavioral anomaly, user complaint):

1. **Preserve Evidence** (within 5 minutes):
   ```bash
   # Copy all logs and system state
   mkdir -p /backup/incident_$(date +%Y%m%d_%H%M%S)
   cp -r logs/* /backup/incident_*/
   sqlite3 data/sentinel.db ".dump" > /backup/incident_*/db_dump.sql
   ```

2. **Notify Team** (within 10 minutes):
   - Create GitHub issue: `INCIDENT: <description>`
   - Notify on-call: Slack mention @oncall
   - Alert PM/legal if safety-related

3. **Investigate Root Cause** (within 4 hours):
   - Review logs for errors preceding incident
   - Run load test to reproduce
   - Inspect code changes since last stable version

4. **Remediation**:
   - Hot-fix if critical (safety threat)
   - Schedule for next release if minor
   - Implement safeguard to prevent recurrence

---

## 6. ROLLBACK PROCEDURES

If production deployment fails acceptance criteria:

### 6.1 Full Rollback (Return to v1.2.0)

```bash
# 1. Stop all public broadcasts
pkill -f 'sentinel_agent'

# 2. Revert code changes
git revert --no-edit <phase5-commit-hash>
git push origin main

# 3. Restart with previous version
python system_orchestrator.py --version 1.2.0

# 4. Verify fallback to SMS-only alerts
curl http://localhost:8000/api/health | jq '.alert_mode'
# Expected: "sms_primary_ble_backup"

# 5. Notify all stakeholders
echo "SmartSalai reverted to v1.2.0. Public SMS alerts active."
```

### 6.2 Partial Rollback (Disable Specific Component)

If only one component fails (e.g., DriveLegal):

```bash
# Disable DriveLegal, keep hazard detection
python system_orchestrator.py --disable-driveLegal --version 1.2.1

# Public receives hazard alerts only (skip violation verdicts)
```

### 6.3 Re-deployment After Fix

1. Root cause identified and fixed
2. Re-run unit tests + load test (all must pass)
3. Get safety officer sign-off
4. Deploy to 2-vehicle shadow test (3 days min)
5. If metrics acceptable, proceed with phased rollout

---

## 7. LEGAL & COMPLIANCE

### 7.1 iRAD Audit Trail

**Requirement**: Continuous, immutable record of all hazard detections, verdicts, and actions.

**Verification** (run weekly):
```bash
# Check for audit trail continuity
sqlite3 data/sentinel.db "
  SELECT 
    DATE(created_at), 
    COUNT(*) as events
  FROM irad_audit_trail
  WHERE created_at > datetime('now', '-30 days')
  GROUP BY DATE(created_at)
  ORDER BY DATE(created_at);
"

# Expected: One entry per day, no gaps >1 hour within a day
```

**Submission** (monthly):
- Submit audit trail to regulatory body (as per license requirements)
- Verify signatures match blockchain immutability contract

### 7.2 DriveLegal Verdict Completeness

**Requirement**: Every detection gets a DriveLegal verdict (violation or safe).

**Verification** (run daily):
```bash
sqlite3 data/sentinel.db "
  SELECT 
    COUNT(*) as total_detections,
    COUNT(CASE WHEN driveLegal_verdict IS NOT NULL THEN 1 END) as verdicted
  FROM hazard_detections
  WHERE created_at > datetime('now', '-1 day')
"

# Expected: verdicted = total_detections (100% coverage)
```

### 7.3 Insurance & Liability

- **Coverage**: All incidents during field test covered by R&D liability insurance
- **Public Liability**: Kicks in at Phase 5B (50+ rider expansion)
- **Incident Reporting**: 48-hour requirement to insurer for any injury-related events

---

## 8. SUCCESS METRICS (Phase 5 Completion)

By end of field test:
- ✅ **Detection Accuracy**: ≥85% vs ground truth
- ✅ **False Positive Rate**: <5%
- ✅ **False Negative Rate (Critical)**: <2% on potholes/accidents
- ✅ **System Uptime**: ≥99%
- ✅ **Latency (p95)**: <150ms from detection to alert
- ✅ **Zero Crashes**: 7 consecutive days without hang/crash
- ✅ **Memory Stability**: <50MB growth per day
- ✅ **Network Reliability**: <5% relay drop, <10% DB lock
- ✅ **Legal Compliance**: iRAD trail complete, DriveLegal 100% coverage
- ✅ **Driver Satisfaction**: Non-negative feedback from pilot riders

---

## 9. APPENDICES

### 9.1 Quick Reference - Key Files

| File | Purpose |
|------|---------|
| `agents/ble_mesh_broker.py` | BLE V2X swarm broker (FIX #1, #4) |
| `agents/swarm_bridge.py` | Swarm-to-DB bridge (FIX #3) |
| `scripts/production_audit.py` | Compliance auditor (FIX #2) |
| `system_orchestrator.py` | WebSocket orchestrator (FIX #5) |
| `tests/test_phase5_fixes.py` | Unit test suite |
| `scripts/phase5_sensor_calibration.py` | Sensor calibration protocol |
| `scripts/phase5_deployment_executor.py` | Deployment automation |
| `scripts/post_deployment_monitor.py` | SLO monitoring |
| `PHASE_5_RELEASE_GATE.md` | Release checklist |
| `ble_mesh_protocol_optimized.json` | Optimized mesh config |

### 9.2 Emergency Contacts

| Role | Name | Phone | Role |
|------|------|-------|------|
| On-Call Engineer | TBD | +91-XXXXXXXXXX | Immediate incident response |
| Safety Officer | TBD | +91-XXXXXXXXXX | Deployment sign-off, incident escalation |
| Project Lead | TBD | +91-XXXXXXXXXX | Strategic decisions, rollback authority |
| Legal Counsel | TBD | +91-XXXXXXXXXX | Compliance & incident reporting |

### 9.3 Related Documentation

- Phase 1-4 Audit Reports: `docs/audit_phases_1-4.md`
- Architecture Overview: `docs/ARCHITECTURE.md`
- BLE Mesh Protocol Spec: `docs/ais140_ble_mesh.md`
- iRAD Compliance: `docs/IRAD_COMPLIANCE.md`

---

**END OF OPERATIONS MANUAL**

Approval History:
```
v1.0 | 2026-03-15 | Initial Phase 5 OPS Manual | Tech Lead: _______ | Date: _______
```
