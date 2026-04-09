# SAFETY.md — SmartSalai Edge-Sentinel

> **READ THIS BEFORE DEPLOYING OR USING THIS SOFTWARE.**

---

## 1. Advisory-Only System

SmartSalai Edge-Sentinel is an **experimental research prototype** that provides
**advisory / informational alerts only**.  It does **NOT**:

- Control steering, braking, throttle, or any other vehicle actuator.
- Make safety-critical driving decisions.
- Guarantee detection of any road hazard, traffic sign, or obstacle.
- Replace attentive, skilled driving or professional driver training.

**The driver is solely and wholly responsible for safe vehicle operation at
all times.  No output from this system should be acted upon without
independent human verification.**

---

## 2. Not Certified for Safety-Critical Use

This software has **not** been evaluated, certified, or approved under any
automotive safety standard, including but not limited to:

| Standard | Status |
|---|---|
| ISO 26262 (Functional Safety — Road Vehicles) | Not evaluated |
| ISO/PAS 21448 (SOTIF — Safety of the Intended Functionality) | Not evaluated |
| AIS-190 / CMVR (India motor vehicle regulations) | Not evaluated |
| IEC 61508 (Generic Functional Safety) | Not evaluated |

**Do not deploy this system in any vehicle where system failure or incorrect
output could contribute to injury, death, or property damage.**

---

## 3. Intended Use Scope

This prototype is designed **exclusively** for:

- Offline video replay and research analysis.
- Academic / hackathon demonstration.
- Development of future certified systems (requires full safety process).

**Not intended for:**

- Production deployment in any vehicle.
- Emergency services (ambulances, fire trucks, police vehicles).
- Public transport (buses, vans, taxis).
- Any use case where incorrect output could endanger life or safety.

---

## 4. Indian Road Conditions Disclaimer

The vision models included in this prototype have **not** been validated
against the full diversity of Indian road conditions, including but not
limited to:

- Night / low-visibility driving
- Monsoon / waterlogged roads
- Unmaintained rural roads and off-road terrain
- Mixed traffic (auto-rickshaws, cattle, pedestrians, cyclists)
- Dust, fog, glare, and other adverse weather

**Detection accuracy in these conditions is unknown and may be very low.**
Advisory alerts may be wrong, delayed, or missing entirely.

---

## 5. Responsible Use Requirements

By using, running, or deploying this software you agree to:

1. **Always keep a qualified human driver in full control** of any vehicle.
2. **Never rely on advisory alerts** for safety-critical manoeuvres.
3. **Treat every alert as unverified** until confirmed by direct human
   observation.
4. **Not represent** this system as automotive-grade, certified, or safe for
   vehicle operation to any third party.
5. **Comply with all applicable traffic laws** in your jurisdiction,
   regardless of what this system reports.

---

## 6. Data Privacy

- Video, GPS, and IMU data collected during operation may contain sensitive
  personal and location information.
- Do not share or upload raw telemetry without appropriate consent and
  data-protection review.
- The ZKP (zero-knowledge proof) envelope reduces metadata leakage but does
  not eliminate it; consult a privacy professional before deploying in
  regulated contexts.

---

## 7. Contact

If you believe you have found a safety-critical bug or misuse risk, open a
GitHub Issue labelled **`safety`** and describe the concern.  Do **not**
attempt to deploy a fix in production without independent review.

---

*This disclaimer was written in accordance with responsible AI and automotive
software engineering principles.  It is not a substitute for formal safety
engineering process.*
