<<<<<<< HEAD
# core/__init__.py
=======
"""
SmartSalai Edge-Sentinel — core package.

Modules:
  agent_bus.py      — JSON-RPC 2.0 inter-agent pub/sub bus (T-013)
  zkp_envelope.py   — Zero-Knowledge Proof GPS envelope (T-014)
  irad_serializer.py — MoRTH iRAD-2022 schema serializer (T-015)
"""
from .agent_bus import AgentBus, BusMessage, Topics, get_bus, reset_bus
from .zkp_envelope import ZKPEnvelopeBuilder, ZKPEnvelope, get_builder, wrap_event, coarsen_coordinate
from .irad_serializer import IRADSerializer, IRADRecord, get_serializer

__all__ = [
    "AgentBus", "BusMessage", "Topics", "get_bus", "reset_bus",
    "ZKPEnvelopeBuilder", "ZKPEnvelope", "get_builder",
    "wrap_event", "coarsen_coordinate",
    "IRADSerializer", "IRADRecord", "get_serializer",
]
>>>>>>> 2c7c158ab4b54348e45911533a25b045f3d7342e
