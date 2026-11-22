# External Delta Watcher (`scripts/delta-watcher`)

Polls GitHub repositories outside the LLM on a Cloud Scheduler cadence (Cloud Run service) and wakes the Scion `coordinator` only when new Issues, human comments, PR state changes, or stalls occur.

## Why This Exists (`WK-003`)

- Scion `hub.github_triggers` is alpha and inbound GitHub webhooks cannot cross an IAP-protected Hub.
- Polling outside the LLM eliminates idle coordinator wake-ups every 15 to 30 minutes and survives scheduled VM off-hours cleanly.
