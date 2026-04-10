import os
import json
import time
import asyncio
import logging
from typing import List, Dict, Any
from core.agent_bus import bus

# [PERSONA 7: THE SOS RESPONDER]
# Task: Critical life-safety agent that handles emergency calling and coordination.
# Triggered by Persona 3 (IMU-Vision Collision Lock) or Manual SOS Button.

logger = logging.getLogger("edge_sentinel.sos_responder")
logger.setLevel(logging.INFO)

class SOSResponderAgent:
    def __init__(self, contacts_path: str = "config/emergency_contacts.json"):
        self.contacts_path = contacts_path
        self._load_contacts()
        self.active_sos_task = None
        self.active_incident_id = None  # SECURITY FIX #10: Store incident_id for scope access
        
        # Subscribe to high-priority emergency triggers
        bus.subscribe("SYSTEM_SOS_TRIGGER", self.initiate_emergency_protocol)
        bus.subscribe("IMU_ACCIDENT_DETECTED", self.initiate_emergency_protocol)
        bus.subscribe("SYSTEM_SOS_CANCEL", self.cancel_emergency_protocol)
        
        logger.info("PERSONA_7_REPORT: SOS_RESPONDER_ONLINE | MONITORING_FOR_TRAUMA")

    def _load_contacts(self):
        """Loads contacts from the localized registry."""
        try:
            if os.path.exists(self.contacts_path):
                with open(self.contacts_path, "r") as f:
                    self.contacts = json.load(f)
            else:
                self.contacts = []
                logger.warning("PERSONA_7_REPORT: EMERGENCY_CONTACTS_MISSING")
        except Exception as e:
            logger.error(f"CONFIG_ERROR: FAILED_TO_LOAD_CONTACTS: {e}")
            self.contacts = []

    def _dial_emergency_contacts(self, phone: str):
        """
        Hardware API Interface: GSM/SIM800L Module via Serial (AT Commands)
        This is the preferred offline-first edge solution for vehicular systems.
        """
        import serial # Requires pyserial
        try:
            # Example Serial Configuration (Change to match hardware e.g., /dev/ttyS0 or COM3)
            # gsm = serial.Serial('/dev/ttyUSB0', 9600, timeout=1) 
            
            # AT Command Sequence to initiate voice call
            # gsm.write(b'AT\r')
            # time.sleep(0.5)
            # gsm.write(f'ATD{phone};\r'.encode())
            
            raise NotImplementedError("Critical Error: GSM Serial Port (/dev/ttyUSB0) is not configured. Real emergency dial out blocked.")
        except ImportError:
            raise NotImplementedError("Critical Error: 'pyserial' package missing. Cannot interface with GSM module.")

    def initiate_emergency_protocol(self, payload: Dict[str, Any]):
        """Starts the asynchronous safety countdown."""
        if self.active_sos_task:
            logger.warning("PERSONA_7_REPORT: SOS_ALREADY_IN_PROGRESS | IGNORING_REDUNDANT_TRIGGER")
            return

        self.active_sos_task = asyncio.create_task(self._emergency_window_run(payload))

    async def _emergency_window_run(self, payload: Dict[str, Any]):
        """
        Executes the SOS sequence with a 30s cancellation window.
        """
        if "lat" not in payload or "lon" not in payload:
            logger.error("Missing GPS coordinates in SOS payload.")
            self.active_sos_task = None
            return
            
        incident_id = f"SOS_{int(time.time())}"
        self.active_incident_id = incident_id  # SECURITY FIX #10: Store for scope access
        
        logger.critical(f"PERSONA_7_REPORT: !!! POTENTIAL_ACCIDENT_DETECTED !!! ID: {incident_id}")
        
        # 1. Start Voice UI / Dashboard countdown alert
        bus.emit("VOICE_ALERT_REQUEST", {
            "text": "Critical impact detected. Macha, are you okay? I am starting the emergency protocol. Calling contacts in 30 seconds. Say 'Cancel' or press the stop button if you are safe.",
            "priority": "IMMEDIATE"
        })
        
        # 2. Wait 30 seconds for human-in-the-loop cancellation
        try:
            logger.info("PERSONA_7_REPORT: EMERGENCY_COUNTDOWN_START: 30s Window")
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            logger.warning(f"PERSONA_7_REPORT: EMERGENCY_PROTOCOL_ABORTED | user_cancelled:{incident_id}")
            self.active_sos_task = None
            self.active_incident_id = None  # Clear reference
            return

        # 3. Proceed to dial contacts only if NOT CANCELLED
        logger.critical(f"PERSONA_7_REPORT: !!! WINDOW_EXPIRED_COMMENCING_CALLS !!! ID: {incident_id}")
        
        for contact in self.contacts:
            name = contact.get("name")
            phone = contact.get("phone")
            logger.info(f"PERSONA_7_REPORT: ATTEMPTING_CALL: {name} ({phone}) ...")
            try:
                self._dial_emergency_contacts(phone)
            except Exception as e:
                logger.error(f"GSM_ERROR: CALL_FAILED: {e}")
        
        # 4. V2X Broadcast for nearby nodes
        bus.emit("SENTINEL_FUSION_ALERT", {
            "fusion_id": incident_id,
            "type": "ACCIDENT_NEAR_MISS",
            "severity": "CRITICAL",
            "lat": payload["lat"],
            "lon": payload["lon"],
            "confidence": 100,
            "timestamp_epoch_ms": int(time.time() * 1000)
        })

        bus.emit("V2X_SOS_BROADCAST", {
            "incident_id": incident_id,
            "severity": "CRITICAL",
            "location": f"{payload['lat']}, {payload['lon']}",
            "timestamp": time.time()
        })
        
        logger.info(f"PERSONA_7_REPORT: SOS_PROTOCOL_COMPLETED for {incident_id}")
        self.active_sos_task = None
        self.active_incident_id = None  # Clear reference

    def cancel_emergency_protocol(self, msg: Dict):
        """Cancels any active countdown."""
        if self.active_sos_task:
            self.active_sos_task.cancel()
        
        # SECURITY FIX #10: Use stored incident_id
        incident_id = self.active_incident_id or "UNKNOWN"
        
        bus.emit("VOICE_ALERT_REQUEST", {
            "text": "Emergency protocol cancelled. Staying in monitoring mode. Stay safe, Macha.",
            "priority": "NORMAL"
        })
        
        logger.info(f"PERSONA_7_REPORT: SOS_PROTOCOL_CANCELLED for {incident_id}")
        self.active_incident_id = None  # Clear reference

if __name__ == "__main__":
    # Test Mock Responder
    responder = SOSResponderAgent()
    # Simulate a trigger
    bus.emit("SYSTEM_SOS_TRIGGER", {"reason": "Collision Simulation", "severity": "CRITICAL"})
