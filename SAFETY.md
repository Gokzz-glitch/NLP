# SAFETY.md — SmartSalai Edge-Sentinel

## System Classification

**SmartSalai Edge-Sentinel** is a **research/hackathon prototype** (IIT Madras CoERS Hackathon 2026).
It is **NOT** a certified automotive-grade safety system.

---

## What This System Is

| Attribute | Value |
|---|---|
| Purpose | Edge-native, offline-first driver-assistance advisory tool |
| Deployment target | Android NPU (Dimensity 700 / Snapdragon 680 class) |
| Function | Near-miss detection, legal-RAG lookup, BLE V2X hazard sharing, TTS alerts |
| Audience | Two-wheeler riders in Tamil Nadu (research/demo context) |
| Current status | **Prototype / pre-alpha (v0.1.0)** |

---

## What This System Is NOT

- ❌ **Not** a vehicle control system (no steering, braking, throttle actuation).
- ❌ **Not** certified to ISO 26262 (Functional Safety), ISO 21448 (SOTIF), AIS-189 (India ADAS), or any automotive safety standard.
- ❌ **Not** validated for real-world deployment in driving school vans, ambulances, firetrucks, civilian cars, or any vehicle on Indian roads.
- ❌ **Not** a production system. It contains known `[BLOCKED]` / `ERR_DATA_MISSING` stubs (see README and tasks.md).
- ❌ **Not** tested against formal hazard analysis (HARA/FMEA/FTA).

---

## Safety-Critical Claims Audit

| Claim in docs/code | Verification status |
|---|---|
| "near-miss detection" | Deterministic heuristic only — no real ML model loaded by default; falls back to rule-based classifier. No real-world validation data. |
| "YOLOv8-nano sign audit" | **STUB** — model weights are missing (ERR-001). Vision runs in mock mode unless `VISION_MODEL_PATH` is set. |
| "Bhashini TTS <100ms" | **STUB** — TTS model package missing (ERR-002). Latency claim is unverified. |
| "ZKP telemetry privacy" | Pedersen commitment implemented but not audited by a cryptographer. |
| "Section 208 challenge" | Legal draft generation is automated text; it is NOT legal advice and has not been reviewed by a licensed advocate. |
| "BLE V2X hazard sharing" | Protocol schema defined; real BLE mesh protocol implementation is incomplete (TODO T-008). |

---

## Required Safeguards Before Any Real-World Use

Any party wishing to deploy this system in a real vehicle **MUST** complete all of the following before use:

1. **Formal Safety Analysis** — Conduct a HARA (Hazard Analysis and Risk Assessment) per ISO 26262-3. Classify all safety goals. Determine ASIL levels.
2. **Functional Safety Case** — Produce a safety case document demonstrating that all ASIL-D (or applicable ASIL) requirements are met.
3. **Model Validation** — Replace all stub/mock models with validated, real-world-trained and tested ML models. Perform ODD (Operational Design Domain) characterization.
4. **Regulatory Compliance** — Obtain approvals under AIS-189 (Indian ADAS standard), CMVR, and any applicable state transport authority requirements.
5. **Legal Review** — Any automated legal drafting feature must be reviewed by a licensed advocate before use.
6. **Real-World Testing** — Conduct controlled test track validation followed by supervised real-world evaluation under all Indian road condition categories (NH/SH/MDR/ODR/village roads, monsoon, night, mixed traffic).
7. **Cybersecurity Audit** — Conduct a threat model (per ISO/SAE 21434) and penetration test before deployment.
8. **Privacy Audit** — Ensure ZKP envelope and data handling comply with DPDP Act 2023 (India).

---

## Indian Road Condition Considerations

Indian road conditions introduce unique safety challenges that this prototype does **not** adequately address:

| Challenge | Current Status |
|---|---|
| Mixed traffic (cattle, cycles, pedestrians, auto-rickshaws) | YOLOv8 weights are missing; detection is mocked |
| Poor road marking and missing/damaged signs | Sign audit is a stub (ERR-001) |
| Monsoon / low-visibility conditions | No degraded-mode testing performed |
| Speed breakers (unmarked/unlit) | Not modeled in IMU heuristic |
| Night driving / glare | Vision system has no night-mode logic |
| GPS-denied / urban canyon operation | GPS coordinates are placeholder slots only |
| Emergency vehicle right-of-way | Not implemented |

---

## Disclaimer

> **This software is provided "as is", without warranty of any kind, express or implied. The authors and contributors disclaim all liability for any injury, death, property damage, legal consequence, or other harm resulting from the use or misuse of this software in any vehicle or road-safety context.**
>
> **Do not deploy this software in any safety-critical system without completing the required safeguards listed above.**

---

## Reporting Safety Issues

If you find a safety-relevant bug, vulnerability, or incorrect safety claim in this repository, please open a GitHub Issue tagged `safety` or email the repository maintainer directly. Do **not** attempt to deploy a known-buggy version.

---

*Last updated: 2026-04-09 | Version: 0.1.0 | Status: Research Prototype*
