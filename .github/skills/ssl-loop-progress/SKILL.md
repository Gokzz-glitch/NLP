---
title: SSL Loop Progress Skill
name: ssl-loop-progress
version: 1.0
trigger: ssl loop, progress, monitor, result
usage: "Use when: running or monitoring the SSL loop and the user requests periodic progress updates or final results."
description: |
  Use when running the SSL loop locally and the user wants to see progress updates every 15 minutes and a final result summary. This skill should:
  - Monitor the SSL loop execution
  - Report progress (status, errors, metrics) every 15 minutes
  - Summarize the final result and any issues
  - Only follow the SSL loop (do not monitor unrelated tasks)
  - Use clear, timestamped updates
  - Trigger on keywords: ssl loop, progress, monitor, result, every 15min

---

# SSL Loop Progress Skill

This skill is designed to:
- Periodically check the status of the SSL loop execution
- Print or log progress every 15 minutes
- Summarize the final outcome and any errors
- Be used only for the SSL loop workflow

## Example Prompts
- "Monitor the SSL loop and show me progress every 15 minutes."
- "Follow the SSL loop and summarize the result."
- "Show SSL loop progress and errors as they happen."

## Implementation Notes
- Use subprocess monitoring or log tailing as appropriate
- Timestamp each progress update
- Only report on the SSL loop, not other processes
