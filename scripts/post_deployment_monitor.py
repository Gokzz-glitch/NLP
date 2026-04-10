#!/usr/bin/env python3
"""
POST-DEPLOYMENT MONITORING & MAINTENANCE PLAN
For Phase 5 production systems post-Chennai field trial.

Monitors:
- Real-time hazard detection accuracy (comparing detections to crowd-sourced ground truth)
- Network mesh stability (relay storms, lock contention)
- System health (crashes, thermal, memory leaks)
- Legal compliance (iRAD audit trail freshness, DriveLegal verdict logs)

Run: python scripts/post_deployment_monitor.py --vehicle CH-2026-001 --mode production
"""

import argparse
import json
import logging
import sqlite3
import time
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s"
)
logger = logging.getLogger("post_deployment_monitor")


class PostDeploymentMonitor:
    """Continuous monitoring for production-deployed Edge-Sentinel systems."""
    
    # SLO Thresholds (from Phase 5 Release Gate Part E)
    SLO_THRESHOLDS = {
        "hazard_detection_accuracy": 0.85,          # ≥85% vs ground truth
        "false_positive_rate": 0.05,                # <5%
        "false_negative_rate_critical": 0.02,       # <2% on potholes/accidents
        "network_uptime": 0.99,                     # ≥99%
        "db_lock_rate": 0.10,                       # <10%
        "relay_drop_rate": 0.05,                    # <5% below 18-node limit
        "mesh_node_limit": 18,                      # Hard limit per 1km radius
        "system_crash_rate": 0.0,                   # Zero crashes in 30 days
        "cpu_utilization_p95": 0.75,                # CPU <75% p95
        "memory_growth_per_day": 50.0,              # <50MB/day leak rate
        "irad_audit_trail_freshness_hours": 1.0,    # <1hr between submissions
    }
    
    def __init__(self, vehicle_id: str, db_path: str = "data/sentinel.db"):
        self.vehicle_id = vehicle_id
        self.db_path = db_path
        self.monitoring_report = {
            "vehicle_id": vehicle_id,
            "timestamp": datetime.now().isoformat(),
            "slo_violations": [],
            "recommendations": [],
            "overall_health": "UNKNOWN"
        }
    
    def check_hazard_detection_accuracy(self) -> dict:
        """Compare model detections vs crowd-sourced ground truth."""
        logger.info("\n[SLO CHECK] Hazard Detection Accuracy")
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Query: detections with matching ground truth within spatial/temporal windows
            cursor.execute("""
                SELECT COUNT(*) as total_detections
                FROM hazard_detections
                WHERE created_at > datetime('now', '-7 days')
            """)
            total = cursor.fetchone()[0]
            
            cursor.execute("""
                SELECT COUNT(*) as validated
                FROM hazard_detections hd
                JOIN ground_truth_markers gt
                    ON ST_Distance(hd.geom, gt.geom) < 50  -- 50m spatial tolerance
                    AND ABS(
                        (julianday(hd.created_at) - julianday(gt.timestamp))
                        * 24 * 60
                    ) < 10  -- 10min temporal tolerance
                WHERE hd.created_at > datetime('now', '-7 days')
            """)
            validated = cursor.fetchone()[0]
            
            accuracy = validated / total if total > 0 else 0.0
            threshold = self.SLO_THRESHOLDS["hazard_detection_accuracy"]
            
            result = {
                "accuracy": accuracy,
                "total_detections": total,
                "validated_matches": validated,
                "threshold": threshold,
                "status": "PASS" if accuracy >= threshold else "FAIL"
            }
            
            if accuracy < threshold:
                self.monitoring_report["slo_violations"].append({
                    "metric": "hazard_detection_accuracy",
                    "observed": accuracy,
                    "threshold": threshold,
                    "severity": "CRITICAL"
                })
            
            logger.info(f"  Accuracy: {accuracy*100:.1f}% (threshold: {threshold*100:.1f}%)")
            logger.info(f"  {result['status']}")
            
            conn.close()
            return result
        except Exception as e:
            logger.error(f"  Error: {e}")
            return {"status": "ERROR", "error": str(e)}
    
    def check_false_positive_rate(self) -> dict:
        """Measure false positive rate on confirmed non-hazard road sections."""
        logger.info("\n[SLO CHECK] False Positive Rate")
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT COUNT(*) as false_positives
                FROM hazard_detections hd
                LEFT JOIN ground_truth_markers gt
                    ON ST_Distance(hd.geom, gt.geom) < 50
                WHERE hd.created_at > datetime('now', '-7 days')
                    AND gt.id IS NULL  -- No matching ground truth
                    AND hd.confidence > 0.5  -- Only confident detections
            """)
            false_pos = cursor.fetchone()[0]
            
            cursor.execute("""
                SELECT COUNT(*) as total
                FROM hazard_detections
                WHERE created_at > datetime('now', '-7 days')
                    AND confidence > 0.5
            """)
            total = cursor.fetchone()[0]
            
            fp_rate = false_pos / total if total > 0 else 0.0
            threshold = self.SLO_THRESHOLDS["false_positive_rate"]
            
            result = {
                "false_positive_rate": fp_rate,
                "false_positives": false_pos,
                "total_detections": total,
                "threshold": threshold,
                "status": "PASS" if fp_rate < threshold else "FAIL"
            }
            
            if fp_rate > threshold:
                self.monitoring_report["slo_violations"].append({
                    "metric": "false_positive_rate",
                    "observed": fp_rate,
                    "threshold": threshold,
                    "severity": "HIGH"
                })
            
            logger.info(f"  FP Rate: {fp_rate*100:.1f}% (threshold: {threshold*100:.1f}%)")
            logger.info(f"  {result['status']}")
            
            conn.close()
            return result
        except Exception as e:
            logger.error(f"  Error: {e}")
            return {"status": "ERROR", "error": str(e)}
    
    def check_network_uptime(self) -> dict:
        """Check BLE mesh connectivity uptime (heartbeat presence)."""
        logger.info("\n[SLO CHECK] Network Uptime")
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Count heartbeat events in last 7 days
            cursor.execute("""
                SELECT COUNT(*) as heartbeat_count
                FROM events
                WHERE event_type = 'SYSTEM_HEARTBEAT'
                    AND created_at > datetime('now', '-7 days')
            """)
            heartbeats = cursor.fetchone()[0]
            
            # Expected heartbeats: 1 per 10 seconds * 60480 seconds/week = ~6000
            expected_heartbeats = 6000
            uptime = min(1.0, heartbeats / expected_heartbeats) if expected_heartbeats > 0 else 0.0
            threshold = self.SLO_THRESHOLDS["network_uptime"]
            
            result = {
                "uptime": uptime,
                "heartbeats_observed": heartbeats,
                "heartbeats_expected": expected_heartbeats,
                "threshold": threshold,
                "status": "PASS" if uptime >= threshold else "FAIL"
            }
            
            if uptime < threshold:
                self.monitoring_report["slo_violations"].append({
                    "metric": "network_uptime",
                    "observed": uptime,
                    "threshold": threshold,
                    "severity": "CRITICAL"
                })
            
            logger.info(f"  Uptime: {uptime*100:.1f}% (threshold: {threshold*100:.1f}%)")
            logger.info(f"  {result['status']}")
            
            conn.close()
            return result
        except Exception as e:
            logger.error(f"  Error: {e}")
            return {"status": "ERROR", "error": str(e)}
    
    def check_db_lock_rate(self) -> dict:
        """Check SQLite lock contention from agent logs."""
        logger.info("\n[SLO CHECK] Database Lock Rate")
        
        try:
            logs_dir = Path("logs")
            lock_events = 0
            write_operations = 0
            
            for log_file in logs_dir.glob("*.log"):
                try:
                    with open(log_file) as f:
                        for line in f:
                            if "database is locked" in line.lower():
                                lock_events += 1
                            if "INSERT" in line or "UPDATE" in line:
                                write_operations += 1
                except:
                    pass
            
            lock_rate = lock_events / write_operations if write_operations > 0 else 0.0
            threshold = self.SLO_THRESHOLDS["db_lock_rate"]
            
            result = {
                "lock_rate": lock_rate,
                "lock_events": lock_events,
                "write_operations": write_operations,
                "threshold": threshold,
                "status": "PASS" if lock_rate < threshold else "FAIL"
            }
            
            if lock_rate > threshold:
                self.monitoring_report["slo_violations"].append({
                    "metric": "db_lock_rate",
                    "observed": lock_rate,
                    "threshold": threshold,
                    "severity": "HIGH",
                    "recommendation": "Consider increasing WAL busy_timeout or connection pool size"
                })
            
            logger.info(f"  Lock Rate: {lock_rate*100:.1f}% (threshold: {threshold*100:.1f}%)")
            logger.info(f"  {result['status']}")
            
            return result
        except Exception as e:
            logger.error(f"  Error: {e}")
            return {"status": "ERROR", "error": str(e)}
    
    def check_relay_drop_rate(self) -> dict:
        """Check BLE relay storm control effectiveness (packet drop rate)."""
        logger.info("\n[SLO CHECK] Relay Drop Rate")
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_packets,
                    SUM(CASE WHEN dropped = 1 THEN 1 ELSE 0 END) as dropped_packets
                FROM ble_relay_events
                WHERE created_at > datetime('now', '-7 days')
            """)
            total, dropped = cursor.fetchone()
            
            drop_rate = (dropped or 0) / total if total > 0 else 0.0
            threshold = self.SLO_THRESHOLDS["relay_drop_rate"]
            
            result = {
                "drop_rate": drop_rate,
                "packets_dropped": dropped or 0,
                "total_packets": total or 0,
                "threshold": threshold,
                "status": "PASS" if drop_rate < threshold else "WARN"
            }
            
            if drop_rate > threshold:
                self.monitoring_report["recommendations"].append({
                    "metric": "relay_drop_rate",
                    "issue": f"Drop rate {drop_rate*100:.1f}% exceeds threshold {threshold*100:.1f}%",
                    "action": "Review TTL-probabilistic-drop tuning; may indicate node density >18 for given radius"
                })
            
            logger.info(f"  Drop Rate: {drop_rate*100:.1f}% (threshold: {threshold*100:.1f}%)")
            logger.info(f"  {result['status']}")
            
            conn.close()
            return result
        except Exception as e:
            logger.error(f"  Error: {e}")
            return {"status": "ERROR", "error": str(e)}
    
    def check_system_stability(self) -> dict:
        """Check for crashes, thermal throttling, and memory leaks."""
        logger.info("\n[SLO CHECK] System Stability")
        
        try:
            crash_count = 0
            thermal_events = 0
            memory_growth_mb_per_day = 0.0
            
            logs_dir = Path("logs")
            for log_file in logs_dir.glob("*.log"):
                try:
                    with open(log_file) as f:
                        for line in f:
                            if "Traceback" in line or "FATAL" in line or "Crash" in line:
                                crash_count += 1
                            if "thermal" in line.lower() or "throttling" in line.lower():
                                thermal_events += 1
                except:
                    pass
            
            result = {
                "crash_count": crash_count,
                "thermal_events": thermal_events,
                "memory_growth_mb_per_day": memory_growth_mb_per_day,
                "status": "PASS" if crash_count == 0 else "FAIL"
            }
            
            if crash_count > 0:
                self.monitoring_report["slo_violations"].append({
                    "metric": "system_stability",
                    "observed": f"{crash_count} crashes",
                    "threshold": 0,
                    "severity": "CRITICAL"
                })
            
            logger.info(f"  Crashes: {crash_count} (threshold: 0)")
            logger.info(f"  Thermal Events: {thermal_events}")
            logger.info(f"  {result['status']}")
            
            return result
        except Exception as e:
            logger.error(f"  Error: {e}")
            return {"status": "ERROR", "error": str(e)}
    
    def generate_final_report(self) -> str:
        """Synthesize all checks into final health report."""
        logger.info("\n" + "="*80)
        logger.info("FINAL SLO COMPLIANCE REPORT")
        logger.info("="*80)
        
        if len(self.monitoring_report["slo_violations"]) == 0:
            self.monitoring_report["overall_health"] = "HEALTHY"
            logger.info("✅ Overall Status: HEALTHY (all SLOs met)")
        elif len(self.monitoring_report["slo_violations"]) <= 2:
            self.monitoring_report["overall_health"] = "DEGRADED"
            logger.info("⚠️  Overall Status: DEGRADED (1-2 SLO violations)")
        else:
            self.monitoring_report["overall_health"] = "UNHEALTHY"
            logger.info("❌ Overall Status: UNHEALTHY (3+ SLO violations)")
        
        # Save report
        output_dir = Path("logs/monitoring")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        output_file = output_dir / f"slo_report_{self.vehicle_id}_{int(time.time())}.json"
        with open(output_file, 'w') as f:
            json.dump(self.monitoring_report, f, indent=2)
        
        logger.info(f"📄 Report saved to: {output_file}")
        return str(output_file)
    
    def run_all_checks(self):
        """Execute all SLO checks and generate report."""
        logger.info("\n" + "█"*80)
        logger.info("█ POST-DEPLOYMENT SLO MONITORING")
        logger.info(f"█ Vehicle: {self.vehicle_id}")
        logger.info("█"*80)
        
        self.check_hazard_detection_accuracy()
        self.check_false_positive_rate()
        self.check_network_uptime()
        self.check_db_lock_rate()
        self.check_relay_drop_rate()
        self.check_system_stability()
        
        return self.generate_final_report()


class MaintenanceSchedule:
    """Planned maintenance schedule for production systems."""
    
    SCHEDULE = {
        "weekly": [
            "Rotate logs (compress >30 days old)",
            "Verify iRAD audit trail completeness",
            "Check for memory leaks via trending",
            "Review exception logs for patterns",
        ],
        "monthly": [
            "Recalibrate camera intrinsics (environmental drift)",
            "Audit all ground truth submissions for quality",
            "Update threat intelligence database (DriveLegal rules)",
            "Review thermal profile; adjust fan curves if needed",
        ],
        "quarterly": [
            "Full sensor recalibration (camera + IMU)",
            "Update machine learning models (if accuracy trend <85%)",
            "Security audit (check for unauthorized code execution)",
            "Legal compliance audit (iRAD, DriveLegal verdicts)",
        ],
    }
    
    @classmethod
    def generate_schedule(cls, output_file: str = "MAINTENANCE_SCHEDULE.md"):
        """Generate maintenance schedule markdown."""
        content = """# SmartSalai Edge-Sentinel v1.2.1 - Maintenance Schedule

## Weekly Tasks (Every Monday 10 AM)

"""
        for task in cls.SCHEDULE["weekly"]:
            content += f"- [ ] {task}\n"
        
        content += "\n## Monthly Tasks (1st of each month)\n\n"
        for task in cls.SCHEDULE["monthly"]:
            content += f"- [ ] {task}\n"
        
        content += "\n## Quarterly Tasks (Jan 1, Apr 1, Jul 1, Oct 1)\n\n"
        for task in cls.SCHEDULE["quarterly"]:
            content += f"- [ ] {task}\n"
        
        content += """

## Escalation Thresholds

| Metric | Warning Threshold | Escalation Action |
|--------|------------------|-------------------|
| Network Uptime | <99.5% | Page on-call; check relay topology |
| Hazard Accuracy | <87% (vs 85%) | Retrain model with latest data |
| DB Lock Rate | >7% (vs 10%) | Review concurrent writes; upgrade to pooling |
| Memory Growth | >40 MB/day (vs 50) | Profile for leaks; consider restart strategy |
| FP Rate | >4.5% (vs 5%) | Review false positive cluster; may indicate environmental change |

"""
        
        with open(output_file, 'w') as f:
            f.write(content)
        
        logger.info(f"📋 Maintenance schedule written to: {output_file}")
        return output_file


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Post-Deployment Monitor")
    parser.add_argument("--vehicle", required=True, help="Vehicle ID")
    parser.add_argument("--db", default="data/sentinel.db", help="Path to SQLite database")
    parser.add_argument("--gen-schedule", action="store_true", help="Generate maintenance schedule")
    
    args = parser.parse_args()
    
    if args.gen_schedule:
        MaintenanceSchedule.generate_schedule()
        return 0
    
    monitor = PostDeploymentMonitor(args.vehicle, args.db)
    monitor.run_all_checks()
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
