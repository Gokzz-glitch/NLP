#!/usr/bin/env python3
"""Smoke test for court standards mode.

Builds one Section 166 packet and prints validation gate output.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.legal_rag import LegalRAG


def main() -> int:
    rag = LegalRAG(jurisdiction="TN")

    claim = {
        "jurisdiction": "Chennai",
        "claimant_name": "A. Kumar",
        "victim_name": "R. Kumar",
        "victim_age": 32,
        "monthly_income_inr": 28000,
        "dependents_count": 3,
        "is_bachelor": False,
        "future_prospect_rate": 0.4,
        "occupation": "Field Technician",
        "accident_date": "2026-03-12",
        "accident_time": "18:20",
        "accident_location": "Anna Salai, Chennai",
        "accident_narrative": "Victim was hit by an overspeeding truck at a signal while crossing lawfully.",
        "respondent_driver": "S. Driver",
        "respondent_owner": "XYZ Logistics Pvt Ltd",
        "respondent_insurer": "ABC Insurance Co Ltd",
        "interest_percent": 12,
    }

    packet = rag.build_court_packet(claim)
    print(json.dumps({
        "court_ready": packet.get("court_ready"),
        "validation_gate": packet.get("validation_gate"),
        "validation": packet.get("validation"),
        "citations": packet.get("citations"),
        "total_compensation_inr": packet.get("compensation", {}).get("total_compensation_inr"),
    }, indent=2))

    if not packet.get("court_ready"):
        print("Court packet failed validation gate.")
        return 1

    print("Court packet passed validation gate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
