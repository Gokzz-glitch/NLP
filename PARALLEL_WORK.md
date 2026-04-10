# Parallel Work - User Instructions

This file records the exact operating expectations provided by the user.

## Core Direction
- Run heavy tasks on Colab in parallel.
- Use local GPU work in parallel with Colab.
- Keep the system autonomous with no human-in-the-loop for routine cycles.
- Do not let the pipeline stop.

## Runtime Behavior
- Keep monitor updates live every 10 seconds.
- Keep dashboard, monitor, ingestion loop, and training loop running together.
- If downloads fail, do not stall; continue via fallback strategy.
- Keep processing even during API/quota pressure.

## Data + Download Resilience
- Support YouTube download path.
- Support direct HTTP/non-YouTube video source fallback.
- If source fetch fails, use cached local video so cycles continue.

## Gemini Verification Expectations
- Use all provided Gemini API keys.
- Rotate keys on quota/rate-limit errors.
- Log active key usage safely using masked fingerprints only.
- Never expose full key values in logs or reports.

## Reliability Expectation
- User should be able to leave for work and return later while pipeline remains active.
- Keep long-run progress visible in live monitor and logs.

## Current Work-Left Item (from dashboard)
- DL-2 DriveLegal violation/challan logic.
