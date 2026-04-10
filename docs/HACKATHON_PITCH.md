# SmartSalai Edge-Sentinel
## 3-Minute Hackathon Pitch Script (Operator Version)

### Stage Setup (before speaking)
- Laptop running backend and dashboard.
- Phone running Expo app connected to websocket.
- Camera pointed to live scene or prepared test road clip.
- Terminal and dashboard visible to judges.

---

## 0:00 - 0:25 | Hook
"Good afternoon judges. India does not need another cloud demo that fails in dead zones. It needs a road-safety system that works when the network fails, when conditions get noisy, and when legal accountability matters in real time."

"This is SmartSalai Edge-Sentinel: an offline-first Bio-Legal Shield for Indian roads."

---

## 0:25 - 1:05 | Problem + Why We Built This
"Two things fail together in real incidents: detection and legal response. A rider gets flagged, stopped, or harmed, and there is no trusted, immediate legal context at the edge."

"So we merged three layers into one safety fabric:"
- "Edge vision for live hazard detection."
- "A legal intelligence layer focused on Section 208 Habeas Corpus context."
- "An offline BLE V2X swarm that propagates alerts without internet."

"If cloud dies, the system still detects, still reasons, still communicates."

---

## 1:05 - 1:45 | Bio-Legal Shield (Section 208 RAG)
"Our Bio-Legal Shield is not a static PDF lookup. It is a local RAG workflow tied to an on-device SQLite WAL legal ledger."

"When a critical event happens, the system can surface Section 208-relevant legal context, structured advisories, and audit trail entries on-device."

"That means no waiting for cloud APIs, no blind legal ambiguity, and no broken chain of evidence."

"In simple terms: we protect the human body on the road and the legal rights around that body in the same loop."

---

## 1:45 - 2:20 | Offline V2X Swarm + Latency
"Now the second pillar: offline V2X swarm."

"Nodes relay hazard alerts over BLE mesh with TTL and storm-control safeguards. This is built for dense urban noise and weak connectivity."

"We also benchmarked the internal alert bridge path to low-latency delivery, with a 43 millisecond p95 target profile for event propagation in local bench conditions."

"So this is not only resilient; it is fast enough for practical intervention windows."

---

## 2:20 - 2:55 | Golden Sequence Demo Cues

### Cue A (2:20)
Say: "I am now triggering the Golden Sequence."
Action: Start terminal screen focus and keep dashboard in frame.

### Cue B (2:28)
Say: "Watch the live event flow from detection to legal-context output."
Action: Trigger a hazard event (pothole/speed sign scenario). Keep websocket and dashboard updates visible.

### Cue C (2:40)
Say: "Now watch offline propagation behavior."
Action: Show swarm alert relay evidence and highlight that operation persists without cloud dependency.

### Cue D (2:50)
Say: "This is the Bio-Legal Shield in one pass: detect, reason, relay, and log."
Action: Freeze on dashboard summary and terminal latency line.

---

## 2:55 - 3:00 | Close
"SmartSalai Edge-Sentinel is our answer to real Indian roads: legally aware, offline capable, and engineered for action under failure. Thank you."

---

## Operator Notes (Do not read aloud)
- Keep speaking pace high but clean.
- Do not switch windows rapidly; judges must track causality.
- If any view lags, stay on dashboard and narrate the data path.
- Priority visual order: terminal latency, websocket alert, dashboard state, physical trigger evidence.
