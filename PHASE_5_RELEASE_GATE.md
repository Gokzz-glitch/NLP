# 🚦 PHASE 5 RELEASE GATE & GO-LIVE CHECKLIST
## SmartSalai Edge-Sentinel v1.2.1-Secure/Stress → Public Deployment

---

## PART A: CRITICAL CODE FIXES (MUST PASS BEFORE FIELD TESTING)

### ✅ Critical Bug Fixes (6 hours)
- [x] **FIX #1**: BLE broker h_idx undefined + protocol initialization
  - Evidence: [agents/ble_mesh_broker.py](agents/ble_mesh_broker.py#L35-L45)
  - Status: COMPLETED | Hazard type mapping + protocol auto-load added
  - Test: `pytest tests/test_ble_broker_init.py`

- [x] **FIX #2**: Production audit packet length assertions misaligned
  - Evidence: [scripts/production_audit.py](scripts/production_audit.py#L55-L65)
  - Status: COMPLETED | Spec now [18-22]B instead of hardcoded 16B
  - Test: `python scripts/production_audit.py`

- [x] **FIX #3**: Swarm bridge DB writes not lock-safe (no WAL/timeout/retry)
  - Evidence: [agents/swarm_bridge.py](agents/swarm_bridge.py#L1-L80)
  - Status: COMPLETED | WAL, 2s timeout, exponential retry backoff added
  - Test: `pytest tests/test_swarm_bridge_concurrent.py`

- [x] **FIX #4**: Relay storm controls (dedupe, hop-budget, probabilistic drop)
  - Evidence: [agents/ble_mesh_broker.py](agents/ble_mesh_broker.py#L100-L130)
  - Status: COMPLETED | Dedupe cache limit + TTL-dependent drop rates
  - Test: Load test harness: `python tests/swarm_load_test.py`

- [x] **FIX #5**: Heartbeat wiring mismatch
  - Evidence: [system_orchestrator.py](system_orchestrator.py#L34-L43)
  - Status: COMPLETED | Heartbeat now routed through agent bus
  - Test: `pytest tests/test_heartbeat_routing.py`

---

## PART B: QUALIFICATION TESTS (Must pass with <5% variance)

### Code-Level Tests
- [ ] **Unit**: All broker/bridge/relay functions pass unit tests
  - Command: `pytest tests/test_*.py -v`
  - Gate: 100% pass rate, latency <50ms p95

- [ ] **Integration**: Simulated 18-node swarm load test
  - Command: `python tests/swarm_load_test.py`
  - Gate: p95 DB write latency <10ms, lock rate <5%, hazard latency p95 <150ms

- [ ] **Stress**: 24-node stress test to map hard-fail band
  - Command: `python tests/swarm_load_test.py --nodes 24 --duration 60`
  - Gate: Logs packet loss and lock frequency; documents failure mode

---

## PART C: PHYSICAL PREPARATION (Chennai Deployment)

### Sensor Integration & Calibration
- [ ] **Camera Mount**: Rigid windshield mount, anti-vibration bracket, torque spec locked
  - QC: Zero drift when road test vehicle hits 0.5G horizontal acceleration
  - Evidence: video capture test at 1km/h slow roll

- [ ] **IMU Calibration**: MPU6050 (or equiv) axis alignment + bias calibration on level ground
  - QC: Z-axis offset < ±0.05G, noise floor <0.02G RMS
  - Evidence: 1-minute static recording baseline

- [ ] **Time Sync**: Camera, IMU, and event logger within <10ms relative skew
  - QC: Cross-correlation of frame timestamps vs IMU sample timing
  - Evidence: sync_test.log latency histogram

### Electrical Integration
- [ ] **Power Budget**: 12V buck converter (fused, relay-controlled)
  - QC: Brownout tolerance test: maintain stable operation at 10.5V
  - Evidence: power_analysis.log

- [ ] **Thermal**: Enclosure soak test at 45°C (Chennai ambient) for 30 min
  - QC: No throttle events, CPU < 85°C, GPU < 80°C
  - Evidence: thermal_stress.log

- [ ] **Ignition Interlock**: Safe shutdown sequencing on power loss
  - QC: DB file integrity post power-cycle
  - Evidence: sqlite3_integrity_check.log

---

## PART D: REAL-WORLD DATA VALIDATION (Chennai streets)

### Protocol & Network Validation
- [ ] **BLE Mesh Integrity**: Day run (10 km, 2 riders)
  - Acceptance: 0 spoofed/corrupted packets, <2% relay drop
  - Evidence: mesh_integrity_report_day.json

- [ ] **Offline Mode**: Full hazard loop without internet
  - Acceptance: All detections logged to local DB, zero cloud traces
  - Evidence: offline_mode_audit.log

- [ ] **Database Durability**: Power cycle recovery test
  - Acceptance: Zero data loss, WAL checkpoint clean
  - Evidence: db_recovery_test.log

### Detection & Alert Quality
- [ ] **Day Road Test**: Mixed route (arterial, inner roads, flyover)
  - Acceptance: False positive rate <5%, missed critical <2%
  - Evidence: day_run_ground_truth_audit.csv

- [ ] **Night Road Test**: Low-light highway run
  - Acceptance: Maintain >80% of day mAP, no catastrophic failures
  - Evidence: night_run_detection_report.json

- [ ] **Rain/Wet Test**: Monsoon or post-rain condition
  - Acceptance: Acceptable graceful degradation, no spurious alerts
  - Evidence: rain_run_detection_report.json

### DriveLegal Violation Logic Gate
- [ ] **Violation Detection**: Helmet absence, speed limit breach, lane violation
  - Acceptance: All three major violation classes detected end-to-end
  - Evidence: Satisfies DL-2 from [logs/market_readiness_todo.md](logs/market_readiness_todo.md)
  - Status: **BLOCKER** — Must complete before public deployment

### Safety & Audit
- [ ] **Audio Alert Distraction**: Voice TTS alert timing and frequency acceptable to test drivers
  - Acceptance: Drivers report non-distracting, clear instructions
  - Evidence: driver_feedback_survey.json

- [ ] **False Negative Ceiling**: Critical hazards 3 km ahead are detected >95% of time
  - Acceptance: Pothole / accident / breach hazards
  - Evidence: critical_hazard_audit.log

- [ ] **Audit Trail**: All events logged to iRAD-compliant format
  - Acceptance: Zero audit gaps, checksum validation passes
  - Evidence: irad_audit_trace.json

---

## PART E: DEPLOYMENT SIGN-OFF

### Pre-Deployment Review
- [ ] **Architecture Review**: All Phase 5 fixes integrated and tested
  - Reviewer: Tech lead
  - Sign-off: ___________________ Date: ___________

- [ ] **Safety Review**: All SLOs met, no known blockers
  - Reviewer: Safety officer
  - Sign-off: ___________________ Date: ___________

- [ ] **Legal Compliance**: DriveLegal, iRAD, Section 208 logic verified
  - Reviewer: Policy/legal
  - Sign-off: ___________________ Date: ___________

### Deployment Parameters (Locked)
```json
{
  "deployment_target": "Chennai, TN, India",
  "vehicle_class": "Motorcycle / 2W",
  "max_initial_fleet_size": 2,
  "rollout_phase": "SHADOW_MODE_WEEK_1",
  "max_nodes_per_1km_cell": 18,
  "db_lock_timeout_ms": 2000,
  "ble_adv_interval_ms": 150,
  "mesh_ttl": 5,
  "hazard_latency_p95_ms": 150,
  "go_nogo_decision_date": "YYYY-MM-DD",
  "approved_by": ["Tech", "Safety", "Legal"],
  "frozen_git_commit": "SHA256"
}
```

### Pilot Expansion Gate
After 1 week of shadow mode:
- [ ] Hazard detection accuracy: Day/night/rain within acceptable variance
- [ ] Network stability: <5% relay drops, <10% DB lock rate
- [ ] User feedback: Non-negative driver sentiment, no critical incidents
- [ ] Performance: P95 latencies stable, no memory leaks

**Decision**: ⬜ Expand to 5 riders | ⬜ Pause for remediation | ⬜ Abort & pivot

---

## PART F: GO-LIVE COMMAND CHECKLIST (Final 24h before public deployment)

- [ ] All code fixes verified in production branch
- [ ] Load test harness run at 18 nodes: PASS
- [ ] All sensor calibrations locked in config files
- [ ] Go-live checklist signed by all 3 reviewers
- [ ] Rollback playbook tested (can revert in <30 min)
- [ ] Frozen git commit tagged and backed up
- [ ] Emergency contact list distributed
- [ ] Driver training completed
- [ ] Legal disclaimers signed by all pilot participants

---

## SUMMARY

**Total Dev Hours to Gate**: 52.0 (6 fixed + 9 DB + 4 audit + 7 relay + 8 heartbeat + 8 load test time)

**Timeline to Public Deployment** (from now):
1. Code fixes & unit tests: 1 week
2. Load testing & integration: 1 week
3. Chennai field validation: 2 weeks (parallel data collection)
4. Review cycles & sign-offs: 3-5 days
5. Pilot phase (shadow mode): 1 week minimum
6. Expansion decision: Day 35

**Final Verdict Gate**: Do not proceed to commercial fleet without EVERY checkbox below. Period.

✅ **SYSTEM READY FOR PHASE 5 EXECUTION**

---

*Document version*: 1.0 | *Last updated*: 2026-04-06 | *Next review*: Pre-field-test
