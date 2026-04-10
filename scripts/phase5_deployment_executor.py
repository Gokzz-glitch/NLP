#!/usr/bin/env python3
"""
PHASE 5 DEPLOYMENT AUTOMATION & VALIDATION SCRIPT
Automated pre-deployment checks, load testing, and field test initiation.
Run: python scripts/phase5_deployment_executor.py --vehicle CH-2026-001
"""

import argparse
import subprocess
import json
import sys
import time
import logging
from pathlib import Path
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s"
)
logger = logging.getLogger("phase5_deployment")


class Phase5DeploymentExecutor:
    """Orchestrates full Phase 5 validation pipeline."""
    
    def __init__(self, vehicle_id: str, run_load_test: bool = False):
        self.vehicle_id = vehicle_id
        self.run_load_test = run_load_test
        self.results = {
            "vehicle_id": vehicle_id,
            "timestamp": datetime.now().isoformat(),
            "checks": {},
            "overall_status": "PENDING"
        }
    
    def step_1_unit_tests(self) -> bool:
        """Run all Phase 5 unit tests."""
        logger.info("\n" + "="*80)
        logger.info("STEP 1: UNIT TESTS (Phase 5 Fixes)")
        logger.info("="*80)
        
        try:
            result = subprocess.run(
                ["python", "-m", "pytest", "tests/test_phase5_fixes.py", "-v"],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            passed = result.returncode == 0
            self.results["checks"]["unit_tests"] = {
                "passed": passed,
                "output_lines": len(result.stdout.split('\n'))
            }
            
            if passed:
                logger.info("✅ Unit tests PASSED")
            else:
                logger.error("❌ Unit tests FAILED")
                logger.error(result.stdout)
            
            return passed
        except Exception as e:
            logger.error(f"Unit test execution failed: {e}")
            self.results["checks"]["unit_tests"] = {"passed": False, "error": str(e)}
            return False
    
    def step_2_production_audit(self) -> bool:
        """Run production audit to verify protocol compliance."""
        logger.info("\n" + "="*80)
        logger.info("STEP 2: PRODUCTION AUDIT (AIS-140 / iRAD Compliance)")
        logger.info("="*80)
        
        try:
            result = subprocess.run(
                ["python", "scripts/production_audit.py"],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            passed = result.returncode == 0
            self.results["checks"]["production_audit"] = {"passed": passed}
            
            if passed:
                logger.info("✅ Production audit PASSED")
            else:
                logger.error("❌ Production audit FAILED")
                logger.error(result.stdout)
            
            return passed
        except Exception as e:
            logger.error(f"Production audit failed: {e}")
            self.results["checks"]["production_audit"] = {"passed": False, "error": str(e)}
            return False
    
    def step_3_load_test(self) -> bool:
        """Run swarm load test at specified node counts."""
        if not self.run_load_test:
            logger.info("\n⊘ Load test skipped (use --load-test to enable)")
            self.results["checks"]["load_test"] = {"skipped": True}
            return True
        
        logger.info("\n" + "="*80)
        logger.info("STEP 3: SWARM LOAD TEST (18 nodes stable, 24+ hard-fail)")
        logger.info("="*80)
        
        try:
            result = subprocess.run(
                ["python", "tests/swarm_load_test.py"],
                capture_output=True,
                text=True,
                timeout=300
            )
            
            passed = result.returncode == 0
            self.results["checks"]["load_test"] = {"passed": passed}
            
            if passed:
                logger.info("✅ Load test PASSED")
                # Parse latency metrics from output
                if "p95=" in result.stdout:
                    logger.info("  Latency metrics extracted from test output")
            else:
                logger.warning("⚠️  Load test stability check - review output")
            
            return passed
        except Exception as e:
            logger.error(f"Load test failed: {e}")
            self.results["checks"]["load_test"] = {"passed": False, "error": str(e)}
            return False
    
    def step_4_sensor_calibration_checklist(self) -> bool:
        """Verify sensor calibration protocols are documented."""
        logger.info("\n" + "="*80)
        logger.info("STEP 4: SENSOR CALIBRATION READINESS")
        logger.info("="*80)
        
        required_docs = [
            "scripts/phase5_sensor_calibration.py",
            "config/camera_intrinsics.json",
            "config/camera_extrinsics.json",
            "config/imu_calibration.json",
        ]
        
        missing = []
        for doc in required_docs:
            if not Path(doc).exists():
                missing.append(doc)
        
        passed = len(missing) == 0
        self.results["checks"]["sensor_calibration"] = {
            "passed": passed,
            "missing_files": missing
        }
        
        if passed:
            logger.info("✅ Sensor calibration documentation ready")
            logger.info("  → Run: python scripts/phase5_sensor_calibration.py")
        else:
            logger.warning(f"⚠️  Missing calibration files: {missing}")
        
        return passed
    
    def step_5_gate_checklist_completion(self) -> bool:
        """Verify release gate checklist is populated."""
        logger.info("\n" + "="*80)
        logger.info("STEP 5: RELEASE GATE CHECKLIST")
        logger.info("="*80)
        
        gate_file = Path("PHASE_5_RELEASE_GATE.md")
        if not gate_file.exists():
            logger.error("❌ PHASE_5_RELEASE_GATE.md not found")
            self.results["checks"]["gate_checklist"] = {"passed": False}
            return False
        
        with open(gate_file) as f:
            content = f.read()
        
        # Check for key sections
        required_sections = [
            "Critical Bug Fixes",
            "Qualification Tests",
            "Physical Preparation",
            "Real-World Data Validation",
            "Pre-Deployment Review"
        ]
        
        missing_sections = [s for s in required_sections if s not in content]
        passed = len(missing_sections) == 0
        
        self.results["checks"]["gate_checklist"] = {
            "passed": passed,
            "missing_sections": missing_sections
        }
        
        if passed:
            logger.info("✅ Release gate checklist complete")
        else:
            logger.warning(f"⚠️  Missing sections: {missing_sections}")
        
        return passed
    
    def step_6_system_architecture_check(self) -> bool:
        """Verify all fixed modules are importable and consistent."""
        logger.info("\n" + "="*80)
        logger.info("STEP 6: SYSTEM ARCHITECTURE CONSISTENCY")
        logger.info("="*80)
        
        try:
            # Try importing all fixed modules
            from agents.ble_mesh_broker import BLEMeshBroker
            from agents.swarm_bridge import process_swarm_payload
            from scripts.production_audit import ProductionAuditor
            from system_orchestrator import MachaOrchestrator
            
            logger.info("✅ All fixed modules import successfully")
            self.results["checks"]["system_architecture"] = {"passed": True}
            return True
        except Exception as e:
            logger.error(f"❌ Import error: {e}")
            self.results["checks"]["system_architecture"] = {"passed": False, "error": str(e)}
            return False
    
    def run_full_pipeline(self) -> bool:
        """Execute complete deployment validation pipeline."""
        logger.info("\n" + "█"*80)
        logger.info("█ PHASE 5 DEPLOYMENT VALIDATION PIPELINE")
        logger.info(f"█ Vehicle: {self.vehicle_id}")
        logger.info("█"*80)
        
        checks = [
            ("Step 1: Unit Tests", self.step_1_unit_tests),
            ("Step 2: Production Audit", self.step_2_production_audit),
            ("Step 3: Load Test", self.step_3_load_test),
            ("Step 4: Sensor Calibration", self.step_4_sensor_calibration_checklist),
            ("Step 5: Release Gate", self.step_5_gate_checklist_completion),
            ("Step 6: System Architecture", self.step_6_system_architecture_check),
        ]
        
        all_passed = True
        for step_name, step_func in checks:
            try:
                passed = step_func()
                status = "✅ PASS" if passed else "⚠️  FAIL/SKIP"
                logger.info(f"{step_name}: {status}")
                all_passed = all_passed and passed
            except Exception as e:
                logger.error(f"{step_name}: ❌ ERROR - {e}")
                all_passed = False
        
        # Final verdict
        self.results["overall_status"] = "READY_FOR_FIELD_TEST" if all_passed else "BLOCKERS_DETECTED"
        
        logger.info("\n" + "█"*80)
        logger.info("█ DEPLOYMENT VALIDATION COMPLETE")
        logger.info(f"█ Status: {self.results['overall_status']}")
        logger.info("█"*80 + "\n")
        
        # Write results to file
        self._save_results()
        
        return all_passed
    
    def _save_results(self):
        """Save deployment validation results to JSON."""
        output_dir = Path("logs/deployment")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        output_file = output_dir / f"phase5_validation_{self.vehicle_id}_{int(time.time())}.json"
        with open(output_file, 'w') as f:
            json.dump(self.results, f, indent=2)
        
        logger.info(f"📄 Results saved to: {output_file}")


class FieldTestRunbook:
    """
    Field test execution runbook for Chennai pilot deployment.
    Day 1: Shadow mode (2 riders), no public service.
    Days 2-7: Data collection and SLO validation.
    End of week: Go/no-go decision for fleet expansion.
    """
    
    DAYS_SEQUENCE = [
        {
            "day": 1,
            "phase": "Shadow Mode - Day 1",
            "riders": 2,
            "route": "Arterial roads (OMR, CIT Road, Outer Ring Road)",
            "duration_km": 50,
            "metrics_to_collect": [
                "hazard_detection_accuracy",
                "false_positive_rate",
                "network_uptime",
                "db_lock_rate"
            ],
            "driver_action": "Record all alert events, note any false positives"
        },
        {
            "day": 2,
            "phase": "Shadow Mode - Night Run",
            "riders": 2,
            "route": "Same arterial, 8 PM - 10 PM (low light)",
            "duration_km": 30,
            "metrics_to_collect": [
                "night_detection_accuracy",
                "false_negative_rate",
                "gps_drift"
            ],
            "driver_action": "Compare night accuracy vs day; note any vision degradation"
        },
        {
            "day": 3,
            "phase": "Shadow Mode - Monsoon/Wet",
            "riders": 2,
            "route": "Inner roads with potholes (wet surface)",
            "duration_km": 30,
            "metrics_to_collect": [
                "wet_surface_detection",
                "false_alarm_rate"
            ],
            "driver_action": "Validate rain doesn't cause spurious alerts"
        },
        {
            "day": 4,
            "phase": "Violation Detection - Helmet/Speed",
            "riders": 2,
            "route": "Varied speed zone areas",
            "duration_km": 40,
            "metrics_to_collect": [
                "violation_detection_accuracy",
                "driveLegal_verdict_correctness"
            ],
            "driver_action": "One rider wears helmet, one removes (safe test); verify detection"
        },
        {
            "day": 5,
            "phase": "Network Stress - Swarm Formation",
            "riders": 2,
            "route": "Dense corridor (100m spacing between riders)",
            "duration_km": 10,
            "metrics_to_collect": [
                "relay_drop_rate",
                "db_write_latency",
                "mesh_collision_count"
            ],
            "driver_action": "Ride in tight formation; monitor BLE relay traffic"
        },
        {
            "day": 6,
            "phase": "Robustness - Extended Run",
            "riders": 2,
            "route": "Mixed route: arterial + inner roads + flyover",
            "duration_km": 100,
            "metrics_to_collect": [
                "system_stability_long_run",
                "memory_leak_check",
                "cpu_temperature_profile"
            ],
            "driver_action": "Monitor for crashes, freezes, or thermal throttling"
        },
        {
            "day": 7,
            "phase": "Data Analysis & Go/No-Go Decision",
            "riders": 0,
            "route": "N/A",
            "duration_km": 0,
            "metrics_to_collect": [
                "overall_accuracy",
                "slo_compliance",
                "incident_count"
            ],
            "driver_action": "Tech team reviews all 6 days of data; makes expansion decision"
        }
    ]
    
    @classmethod
    def generate_runbook(cls, output_file: str = "FIELD_TEST_RUNBOOK_WEEK1.md"):
        """Generate markdown runbook for field test execution."""
        content = """# Phase 5 Field Test Runbook - Week 1 (Shadow Mode)
## SmartSalai Edge-Sentinel v1.2.1-Secure/Stress → Public Deployment

**Objective**: Validate all Phase 5 fixes in real-world Chennai conditions before fleet expansion.

**Participants**: 2 pilot riders (motorcycles)
**Duration**: 7 days
**Location**: Chennai, TN, India
**Go/No-Go Decision**: End of Day 7

---

"""
        
        for day_spec in cls.DAYS_SEQUENCE:
            day = day_spec["day"]
            content += f"## Day {day}: {day_spec['phase']}\n\n"
            content += f"**Riders**: {day_spec['riders']}\n"
            content += f"**Route**: {day_spec['route']}\n"
            if day_spec['duration_km'] > 0:
                content += f"**Distance**: {day_spec['duration_km']} km\n"
            content += f"\n**Metrics to Collect**:\n"
            
            for metric in day_spec['metrics_to_collect']:
                content += f"- [ ] {metric}\n"
            
            content += f"\n**Driver Action**: {day_spec['driver_action']}\n\n"
            content += "---\n\n"
        
        content += """## Acceptance Criteria (Go/No-Go)

All of the following MUST be met to proceed to fleet expansion:

- [ ] Day/night hazard detection accuracy ≥ 85% (vs ground truth)
- [ ] False positive rate < 5%
- [ ] False negative rate on critical hazards < 2%
- [ ] Network uptime ≥ 99%
- [ ] Database lock rate < 10%
- [ ] BLE relay drop rate < 5%
- [ ] No system crashes or memory leaks detected
- [ ] DriveLegal violation detection working end-to-end
- [ ] Driver feedback: non-negative sentiment, no critical issues
- [ ] iRAD audit trail complete and consistent

**Decision Framework**:
- **PASS (Expand)**: All criteria met → Proceed to 5-rider pilot
- **CONDITIONAL (Pause)**: 1-2 minor issues → Fix and retry within 3 days
- **FAIL (Abort)**: 3+ critical issues → Roll back and investigate

---

## Data Collection & Submission

**Per-Ride Data**:
- `logs/hazard_detection_{TIMESTAMP}.json` - all detections with ground truth
- `logs/network_metrics_{TIMESTAMP}.json` - latency, lock rate, relay stats
- `logs/system_health_{TIMESTAMP}.json` - CPU, RAM, thermal, crashes
- `logs/driver_feedback_{TIMESTAMP}.md` - subjective notes

**Daily Summary**:
- Aggregate above into `logs/day_{N}_summary.json`
- Submit to GitHub issue #PHASE5_FIELD_VALIDATION

**Final Report (Day 8)**:
- Generate `FIELD_TEST_RESULTS_WEEK1.md`
- All checklists completed, signed by tech lead + safety officer

---

## Emergency Protocol

**If crash or safety incident occurs**:
1. Stop immediately, check rider safety
2. Preserve logs: `cp -r logs /backup/incident_TIMESTAMP`
3. DO NOT continue field testing
4. Report to tech lead immediately
5. Root cause analysis before resumption

**If persistent lock or latency issues**:
- Revert to previous checkpoint
- Review logs for pattern
- Run load test to reproduce
- Fall back to reduced node count (1 rider)

---

## Timeline Lock

- **Week 1 (Days 1-7)**: Field testing
- **Day 8 (Monday)**: Decision & analysis
- **Day 9+**: Expansion or remediation

"""
        
        with open(output_file, 'w') as f:
            f.write(content)
        
        logger.info(f"📋 Field test runbook written to: {output_file}")
        return output_file


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Phase 5 Deployment Executor")
    parser.add_argument("--vehicle", required=True, help="Vehicle ID (e.g., CH-2026-001)")
    parser.add_argument("--load-test", action="store_true", help="Run full load test")
    parser.add_argument("--gen-runbook", action="store_true", help="Generate field test runbook")
    
    args = parser.parse_args()
    
    if args.gen_runbook:
        FieldTestRunbook.generate_runbook()
        return 0
    
    executor = Phase5DeploymentExecutor(args.vehicle, run_load_test=args.load_test)
    success = executor.run_full_pipeline()
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
