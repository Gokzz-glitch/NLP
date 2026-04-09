"""
tests/test_ble_mesh_broker.py

Unit tests for agents/ble_mesh_broker.py covering:
  - HMAC-SHA256 message signing and verification
  - Tampered-payload detection
  - Replay attack prevention (nonce reuse, stale timestamp, future timestamp)
  - TTL enforcement and decrement
  - Hop-count increment on receive
  - Hazard and heartbeat publication structure
  - Handler dispatch and removal
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import time
import pytest

from agents.ble_mesh_broker import BLEMeshBroker, MeshMessage


def _broker(node_id="NODE_TEST", key=None):
    signing_key = key if key is not None else b"\x42" * 32
    return BLEMeshBroker(node_id=node_id, signing_key=signing_key)


# ---------------------------------------------------------------------------
# Message signing
# ---------------------------------------------------------------------------

class TestMessageSigning:

    def test_publish_hazard_returns_signed_message(self):
        b = _broker()
        msg = b.publish_hazard("POTHOLE", 12.9, 80.2, "HIGH", 0.85)
        assert msg.signature is not None

    def test_signature_is_32_bytes(self):
        b = _broker()
        msg = b.publish_hazard("POTHOLE", 12.9, 80.2, "HIGH", 0.85)
        assert len(msg.signature) == 32  # HMAC-SHA256 = 32 bytes

    def test_verify_own_signature(self):
        b = _broker()
        msg = b.publish_hazard("POTHOLE", 12.9, 80.2, "HIGH", 0.85)
        assert b._verify_signature(msg)

    def test_tampered_lat_fails(self):
        b = _broker()
        msg = b.publish_hazard("POTHOLE", 12.9, 80.2, "HIGH", 0.85)
        msg.payload["lat"] = 99.0
        assert not b._verify_signature(msg)

    def test_missing_signature_fails(self):
        b = _broker()
        msg = b.publish_hazard("POTHOLE", 12.9, 80.2, "HIGH", 0.85)
        msg.signature = None
        assert not b._verify_signature(msg)

    def test_different_key_fails(self):
        b1 = BLEMeshBroker("A", signing_key=b"\x01" * 32)
        b2 = BLEMeshBroker("B", signing_key=b"\x02" * 32)
        msg = b1.publish_hazard("POTHOLE", 12.9, 80.2, "HIGH", 0.85)
        assert not b2._verify_signature(msg)

    def test_heartbeat_is_also_signed(self):
        b = _broker()
        msg = b.publish_heartbeat(battery_level=0.9)
        assert b._verify_signature(msg)


# ---------------------------------------------------------------------------
# Replay prevention
# ---------------------------------------------------------------------------

class TestReplayPrevention:

    def test_accept_first_receive(self):
        b = _broker()
        msg = b.publish_hazard("POTHOLE", 12.9, 80.2, "HIGH", 0.85)
        assert b.receive(msg)

    def test_reject_duplicate_nonce(self):
        b = _broker()
        msg = b.publish_hazard("POTHOLE", 12.9, 80.2, "HIGH", 0.85)
        b.receive(msg)
        # Second receive of same message must be dropped
        # Re-sign to bypass signature check (nonce is same)
        msg2 = MeshMessage(
            message_type=msg.message_type,
            node_id=msg.node_id,
            timestamp_ms=int(time.time() * 1000),
            payload=msg.payload,
            nonce=msg.nonce,  # Same nonce → replay
            ttl=msg.ttl + 1,
        )
        msg2.signature = b._sign_message(msg2)
        assert not b.receive(msg2)

    def test_reject_future_timestamp(self):
        b = _broker()
        msg = b.publish_hazard("POTHOLE", 12.9, 80.2, "HIGH", 0.85)
        msg.timestamp_ms = int((time.time() + 60) * 1000)
        msg.signature = b._sign_message(msg)
        assert not b.receive(msg)

    def test_reject_stale_timestamp(self):
        b = _broker()
        msg = b.publish_hazard("POTHOLE", 12.9, 80.2, "HIGH", 0.85)
        msg.timestamp_ms = int((time.time() - 60) * 1000)
        msg.signature = b._sign_message(msg)
        assert not b.receive(msg)


# ---------------------------------------------------------------------------
# TTL enforcement
# ---------------------------------------------------------------------------

class TestTTLEnforcement:

    def test_message_accepted_positive_ttl(self):
        b = _broker()
        msg = b.publish_hazard("POTHOLE", 12.9, 80.2, "HIGH", 0.85)
        assert msg.ttl > 0
        assert b.receive(msg)

    def test_message_rejected_zero_ttl(self):
        b = _broker()
        msg = b.publish_hazard("POTHOLE", 12.9, 80.2, "HIGH", 0.85)
        msg.ttl = 0
        assert not b.receive(msg)

    def test_ttl_decremented_on_receive(self):
        b = _broker()
        msg = b.publish_hazard("POTHOLE", 12.9, 80.2, "HIGH", 0.85)
        initial = msg.ttl
        b.receive(msg)
        assert msg.ttl == initial - 1

    def test_hop_count_incremented_on_receive(self):
        b = _broker()
        msg = b.publish_hazard("POTHOLE", 12.9, 80.2, "HIGH", 0.85)
        b.receive(msg)
        assert msg.hop_count == 1


# ---------------------------------------------------------------------------
# Hazard publication
# ---------------------------------------------------------------------------

class TestHazardPublication:

    def test_message_type_is_1(self):
        b = _broker()
        msg = b.publish_hazard("POTHOLE", 12.9, 80.2, "HIGH", 0.85)
        assert msg.message_type == 1

    def test_node_id_correct(self):
        b = BLEMeshBroker("MY_NODE", signing_key=b"\x00" * 32)
        msg = b.publish_hazard("POTHOLE", 12.9, 80.2, "HIGH", 0.85)
        assert msg.node_id == "MY_NODE"

    def test_payload_has_lat_lon(self):
        b = _broker()
        msg = b.publish_hazard("POTHOLE", 12.9, 80.2, "HIGH", 0.85)
        assert "lat" in msg.payload and "lon" in msg.payload

    def test_nonce_is_12_bytes(self):
        b = _broker()
        msg = b.publish_hazard("POTHOLE", 12.9, 80.2, "HIGH", 0.85)
        assert len(msg.nonce) == 12

    def test_default_ttl_from_protocol(self):
        b = _broker()
        msg = b.publish_hazard("POTHOLE", 12.9, 80.2, "HIGH", 0.85)
        assert msg.ttl >= 1

    def test_confidence_rounded(self):
        b = _broker()
        msg = b.publish_hazard("POTHOLE", 12.9, 80.2, "HIGH", 0.855556)
        assert msg.payload["confidence"] == pytest.approx(0.856, abs=0.001)


# ---------------------------------------------------------------------------
# Heartbeat publication
# ---------------------------------------------------------------------------

class TestHeartbeat:

    def test_message_type_is_3(self):
        b = _broker()
        msg = b.publish_heartbeat(0.85)
        assert msg.message_type == 3

    def test_ttl_is_1(self):
        b = _broker()
        msg = b.publish_heartbeat(0.85)
        assert msg.ttl == 1

    def test_battery_level_in_payload(self):
        b = _broker()
        msg = b.publish_heartbeat(0.75)
        assert msg.payload["battery_level"] == pytest.approx(0.75)

    def test_node_id_in_payload(self):
        b = BLEMeshBroker("HB_NODE", signing_key=b"\x00" * 32)
        msg = b.publish_heartbeat(0.5)
        assert msg.payload["node_id"] == "HB_NODE"


# ---------------------------------------------------------------------------
# Handler dispatch
# ---------------------------------------------------------------------------

class TestHandlerDispatch:

    def test_handler_called_on_valid_receive(self):
        b = _broker()
        received = []
        b.add_handler(received.append)
        msg = b.publish_hazard("POTHOLE", 12.9, 80.2, "HIGH", 0.85)
        b.receive(msg)
        assert len(received) == 1

    def test_handler_not_called_on_replay(self):
        b = _broker()
        received = []
        b.add_handler(received.append)
        msg = b.publish_hazard("POTHOLE", 12.9, 80.2, "HIGH", 0.85)
        b.receive(msg)
        # Replay same message (nonce reuse)
        msg2 = MeshMessage(
            message_type=msg.message_type,
            node_id=msg.node_id,
            timestamp_ms=int(time.time() * 1000),
            payload=msg.payload,
            nonce=msg.nonce,
            ttl=msg.ttl + 2,
        )
        msg2.signature = b._sign_message(msg2)
        b.receive(msg2)
        assert len(received) == 1

    def test_remove_handler_stops_dispatch(self):
        b = _broker()
        received = []
        handler = received.append
        b.add_handler(handler)

        msg1 = b.publish_hazard("POTHOLE", 12.9, 80.2, "HIGH", 0.85)
        b.receive(msg1)

        b.remove_handler(handler)
        msg2 = b.publish_hazard("POTHOLE", 12.9, 80.2, "HIGH", 0.85)
        b.receive(msg2)
        assert len(received) == 1

    def test_handler_exception_does_not_block_others(self):
        b = _broker()
        second_called = []
        b.add_handler(lambda m: 1 / 0)
        b.add_handler(lambda m: second_called.append(1))
        msg = b.publish_hazard("POTHOLE", 12.9, 80.2, "HIGH", 0.85)
        b.receive(msg)
        assert len(second_called) == 1
