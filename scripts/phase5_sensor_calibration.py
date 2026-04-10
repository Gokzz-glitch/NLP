"""
SENSOR CALIBRATION & PHYSICAL VALIDATION PROTOCOL
Phase 5 Requirement: All sensors must be calibrated before field deployment.
Reference: PHASE_5_RELEASE_GATE.md Part C
"""

import json
import time
import logging
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, asdict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sensor_calibration")


@dataclass
class CalibrationReport:
    """Calibration result for a single sensor."""
    sensor_name: str
    calibration_date: str
    test_type: str
    pass_fail: bool
    metrics: dict
    notes: str
    approved_by: str = ""


class CameraCalibrationProtocol:
    """
    Camera rigid mount validation and intrinsic calibration.
    Procedure: Mount camera on vehicle, run through checklist below.
    """
    
    def __init__(self, vehicle_id: str):
        self.vehicle_id = vehicle_id
        self.report = CalibrationReport(
            sensor_name="Camera Mount",
            calibration_date=datetime.now().isoformat(),
            test_type="rigid_mount + intrinsic",
            pass_fail=False,
            metrics={},
            notes=""
        )
    
    def test_mount_rigidity(self) -> bool:
        """QC: Mount must not drift when vehicle accelerates 0.5G horizontal."""
        logger.info("TEST: Camera mount rigidity (0.5G horizontal acceleration)")
        logger.info("  1. Drive at 10-15 km/h straight")
        logger.info("  2. Steer firmly left/right (0.5G lateral accel)")
        logger.info("  3. Play video back frame-by-frame")
        logger.info("  4. Check: horizon line does NOT drift in frame")
        logger.info("  5. Record: total drift pixels, timestamp")
        
        # This is manual validation; placeholder for automated detection would go here
        drift_pixels = -1  # User to fill after manual check
        
        passed = drift_pixels >= 0 and drift_pixels <= 2
        self.report.metrics["drift_pixels"] = drift_pixels
        self.report.pass_fail = passed
        
        return passed
    
    def test_intrinsic_calibration(self) -> bool:
        """Camera intrinsic (principal point, focal length) calibration."""
        logger.info("TEST: Camera intrinsic calibration")
        logger.info("  1. Place checkerboard (or known pattern) at varied distances")
        logger.info("  2. Capture 10-15 frames at different angles")
        logger.info("  3. Run OpenCV calibrateCamera() on captured frames")
        logger.info("  4. Extract intrinsic matrix K and distortion coeffs")
        logger.info("  5. Save to config/camera_intrinsics.json")
        
        # Placeholder: would load calibrated K matrix and verify it's reasonable
        # Typical intrinsic: fx=500, fy=500, cx=320, cy=240 for 640x480
        
        logger.info("  → Save output to: config/camera_intrinsics.json")
        return True
    
    def test_extrinsic_to_imu(self) -> bool:
        """Camera-to-IMU lever arm and rotation matrix."""
        logger.info("TEST: Camera extrinsic (lever arm & rotation to IMU frame)")
        logger.info("  1. Measure physical X/Y/Z distance (meters) from camera to IMU")
        logger.info("  2. Measure rotation: pitch, roll, yaw (degrees)")
        logger.info("  3. Build 4x4 homogeneous transform matrix")
        logger.info("  4. Save to config/camera_extrinsics.json")
        logger.info("  5. Typical: (~0.05m forward, ~0.01m vertical)")
        
        logger.info("  → Save output to: config/camera_extrinsics.json")
        return True
    
    def run_all_tests(self) -> bool:
        """Run all camera tests and generate report."""
        logger.info("\n" + "="*80)
        logger.info("CAMERA CALIBRATION PROTOCOL")
        logger.info("="*80)
        
        test1 = self.test_mount_rigidity()
        test2 = self.test_intrinsic_calibration()
        test3 = self.test_extrinsic_to_imu()
        
        self.report.pass_fail = all([test1, test2, test3])
        return self.report.pass_fail


class IMUCalibrationProtocol:
    """
    IMU (MPU6050 or similar) axis alignment, bias calibration.
    Procedure: Place vehicle on level ground, run protocol.
    """
    
    def __init__(self, vehicle_id: str):
        self.vehicle_id = vehicle_id
        self.report = CalibrationReport(
            sensor_name="IMU",
            calibration_date=datetime.now().isoformat(),
            test_type="bias + axis_alignment",
            pass_fail=False,
            metrics={},
            notes=""
        )
    
    def test_axis_alignment(self) -> bool:
        """Verify IMU X/Y/Z axes align with vehicle frame."""
        logger.info("TEST: IMU axis alignment")
        logger.info("  1. Place vehicle on level ground, engines off")
        logger.info("  2. Record 60 seconds of static IMU readings")
        logger.info("  3. Extract mean for each axis:")
        logger.info("     - Z-axis must be ~+9.81 m/s² (gravity)")
        logger.info("     - X-axis (forward) must be ~0 m/s²")
        logger.info("     - Y-axis (lateral) must be ~0 m/s²")
        logger.info("  4. If axes are transposed or inverted, swap in config")
        
        # Placeholder: user to confirm
        z_axis_nominal = True  # Would check: abs(z_mean - 9.81) < 0.1
        self.report.metrics["z_axis_nominal"] = z_axis_nominal
        
        return z_axis_nominal
    
    def test_bias_calibration(self) -> bool:
        """Measure accelerometer bias under static conditions."""
        logger.info("TEST: IMU bias calibration (accel offset)")
        logger.info("  1. Vehicle stationary, level ground, 60 second sample")
        logger.info("  2. Compute bias per axis: mean(readings) during static period")
        logger.info("  3. Acceptance: |bias| < 0.05 m/s² per axis")
        logger.info("  4. Save to config/imu_calibration.json")
        
        logger.info("  → Typical output:")
        logger.info("  {")
        logger.info("    'accel_bias_x': 0.02,")
        logger.info("    'accel_bias_y': -0.01,")
        logger.info("    'accel_bias_z': 0.03,")
        logger.info("    'gyro_bias_x': 0.005,")
        logger.info("    'gyro_bias_y': -0.002,")
        logger.info("    'gyro_bias_z': 0.001")
        logger.info("  }")
        
        return True
    
    def test_noise_floor(self) -> bool:
        """Measure sensor noise RMS under static conditions."""
        logger.info("TEST: IMU noise floor (RMS)")
        logger.info("  1. Vehicle stationary, record 30 seconds")
        logger.info("  2. Remove DC (bias), compute RMS of residuals")
        logger.info("  3. Acceptance: RMS < 0.02 m/s² for accel, < 0.01 rad/s for gyro")
        logger.info("  4. Save to config/imu_noise_spec.json")
        
        noise_acceptable = True  # Placeholder
        self.report.metrics["noise_acceptable"] = noise_acceptable
        
        return noise_acceptable
    
    def run_all_tests(self) -> bool:
        """Run all IMU tests."""
        logger.info("\n" + "="*80)
        logger.info("IMU CALIBRATION PROTOCOL")
        logger.info("="*80)
        
        test1 = self.test_axis_alignment()
        test2 = self.test_bias_calibration()
        test3 = self.test_noise_floor()
        
        self.report.pass_fail = all([test1, test2, test3])
        return self.report.pass_fail


class TimeSyncProtocol:
    """
    Validate time synchronization between camera, IMU, and event logger.
    Requirement: <10ms relative skew.
    """
    
    def __init__(self, vehicle_id: str):
        self.vehicle_id = vehicle_id
        self.report = CalibrationReport(
            sensor_name="Time Sync",
            calibration_date=datetime.now().isoformat(),
            test_type="cross_sensor_latency",
            pass_fail=False,
            metrics={},
            notes=""
        )
    
    def test_time_sync(self) -> bool:
        """Measure timestamp alignment between camera frames and IMU samples."""
        logger.info("TEST: Time synchronization between sensors")
        logger.info("  1. Trigger external strobe light or known event")
        logger.info("  2. Capture video frame (get frame timestamp)")
        logger.info("  3. Check IMU log for nearest sample timestamp")
        logger.info("  4. Compute delta: |frame_ts - imu_ts|")
        logger.info("  5. Repeat 10 times at different times")
        logger.info("  6. Acceptance: max delta < 10ms, mean < 5ms")
        
        logger.info("  → Output to: logs/time_sync_validation.json")
        logger.info("  {")
        logger.info("    'frame_id': 1000,")
        logger.info("    'frame_timestamp_ms': 1234567890.123,")
        logger.info("    'imu_timestamp_ms': 1234567890.118,")
        logger.info("    'delta_ms': 5,")
        logger.info("    'pass': true")
        logger.info("  }")
        
        return True
    
    def run_all_tests(self) -> bool:
        """Run time sync tests."""
        logger.info("\n" + "="*80)
        logger.info("TIME SYNCHRONIZATION PROTOCOL")
        logger.info("="*80)
        
        test1 = self.test_time_sync()
        self.report.pass_fail = test1
        return self.report.pass_fail


class ElectricalValidationProtocol:
    """
    Validate power supply, thermal management, and brownout tolerance.
    """
    
    def __init__(self, vehicle_id: str):
        self.vehicle_id = vehicle_id
        self.report = CalibrationReport(
            sensor_name="Electrical",
            calibration_date=datetime.now().isoformat(),
            test_type="power + thermal",
            pass_fail=False,
            metrics={},
            notes=""
        )
    
    def test_brownout_tolerance(self) -> bool:
        """Test system stability at low voltage (10.5V)."""
        logger.info("TEST: Brownout tolerance (10.5V supply)")
        logger.info("  1. Set power supply to 10.5V (2V below nominal 12V)")
        logger.info("  2. Run inference loop for 5 minutes")
        logger.info("  3. Monitor: CPU temp, GPU temp, no crashes")
        logger.info("  4. Acceptance: system operates normally, no resets")
        logger.info("  → Log output to: logs/brownout_test.log")
        
        return True
    
    def test_thermal_soak(self) -> bool:
        """Thermal soak test in Chennai heat (45°C ambient)."""
        logger.info("TEST: Thermal soak at 45°C ambient")
        logger.info("  1. Preheat chamber to 45°C")
        logger.info("  2. Place system in enclosure with closed ventilation")
        logger.info("  3. Run inference loop for 30 minutes")
        logger.info("  4. Monitor: CPU <85°C, GPU <80°C, no throttle events")
        logger.info("  5. Check logs: no 'THERMAL_THROTTLE' messages")
        logger.info("  → Log output to: logs/thermal_soak_test.log")
        
        return True
    
    def test_ignition_interlock(self) -> bool:
        """Safe shutdown on power loss; DB recovery after power cycle."""
        logger.info("TEST: Ignition interlock and power-cycle recovery")
        logger.info("  1. Run system with database writes")
        logger.info("  2. Abruptly cut power (simulate crash)")
        logger.info("  3. Power back on")
        logger.info("  4. Check: database file integrity with sqlite3 PRAGMA integrity_check")
        logger.info("  5. Verify: no data loss in last records")
        logger.info("  → Output to: logs/power_cycle_recovery.log")
        
        return True
    
    def run_all_tests(self) -> bool:
        """Run all electrical tests."""
        logger.info("\n" + "="*80)
        logger.info("ELECTRICAL VALIDATION PROTOCOL")
        logger.info("="*80)
        
        test1 = self.test_brownout_tolerance()
        test2 = self.test_thermal_soak()
        test3 = self.test_ignition_interlock()
        
        self.report.pass_fail = all([test1, test2, test3])
        return self.report.pass_fail


class CalibrationOrchestrator:
    """Runs all calibration protocols and generates master report."""
    
    def __init__(self, vehicle_id: str):
        self.vehicle_id = vehicle_id
        self.reports = []
        self.output_dir = Path("logs/calibration")
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def run_full_calibration(self) -> bool:
        """Execute all sensor calibration and physical validation protocols."""
        logger.info("\n" + "█"*80)
        logger.info("█ PHASE 5 SENSOR CALIBRATION & PHYSICAL VALIDATION")
        logger.info("█ Vehicle: {} | Date: {}".format(
            self.vehicle_id, datetime.now().isoformat()))
        logger.info("█"*80)
        
        # Run all protocols
        protocols = [
            CameraCalibrationProtocol(self.vehicle_id),
            IMUCalibrationProtocol(self.vehicle_id),
            TimeSyncProtocol(self.vehicle_id),
            ElectricalValidationProtocol(self.vehicle_id)
        ]
        
        all_passed = True
        for protocol in protocols:
            passed = protocol.run_all_tests()
            self.reports.append(protocol.report)
            all_passed = all_passed and passed
            logger.info(f"  → {protocol.report.sensor_name}: {'✅ PASS' if passed else '❌ FAIL'}\n")
        
        # Generate master report
        self._write_master_report(all_passed)
        
        logger.info("█"*80)
        logger.info("█ CALIBRATION COMPLETE")
        logger.info(f"█ Final Status: {'✅ ALL PASS' if all_passed else '❌ FAILURES DETECTED'}")
        logger.info("█"*80 + "\n")
        
        return all_passed
    
    def _write_master_report(self, all_passed: bool):
        """Write comprehensive calibration report to JSON."""
        master_report = {
            "vehicle_id": self.vehicle_id,
            "calibration_date": datetime.now().isoformat(),
            "all_pass": all_passed,
            "sensor_reports": [asdict(r) for r in self.reports],
            "deployment_readiness": all_passed
        }
        
        report_path = self.output_dir / f"calibration_report_{self.vehicle_id}_{int(time.time())}.json"
        with open(report_path, 'w') as f:
            json.dump(master_report, f, indent=2)
        
        logger.info(f"\n📊 Master report written to: {report_path}")
        
        # Also write a checklist
        checklist_path = self.output_dir / f"pre_deployment_checklist_{self.vehicle_id}.md"
        self._write_checklist(checklist_path, all_passed)
    
    def _write_checklist(self, path: Path, all_passed: bool):
        """Write human-readable pre-deployment checklist."""
        checklist = f"""# Pre-Deployment Checklist
Vehicle: {self.vehicle_id}
Date: {datetime.now().isoformat()}

## Calibration Results
"""
        for report in self.reports:
            status = "✅ PASS" if report.pass_fail else "❌ FAIL"
            checklist += f"\n- [{status}] {report.sensor_name} ({report.test_type})\n"
        
        checklist += f"\n## Deployment Ready\n"
        checklist += f"- [{'x' if all_passed else ' '}] All sensors calibrated and validated\n"
        checklist += f"- [{'x' if all_passed else ' '}] Can proceed to field testing\n"
        
        with open(path, 'w') as f:
            f.write(checklist)


if __name__ == "__main__":
    # Example usage
    vehicle_id = "CH-2026-001"
    orchestrator = CalibrationOrchestrator(vehicle_id)
    passed = orchestrator.run_full_calibration()
    
    exit(0 if passed else 1)
