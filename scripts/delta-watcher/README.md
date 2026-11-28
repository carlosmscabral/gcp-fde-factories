# External Delta Watcher (`scripts/delta-watcher`)

Provider-agnostic, zero-token intake bridge running on private **Cloud Run + Cloud Scheduler** inside `hub_project_id`. Polls external issue trackers through a pluggable `TrackerAdapter` interface and wakes the Scion Hub `coordinator` only on genuine SEP-aligned deltas.

## Architecture & Modules

- `adapters/base.py`: Normalized `WorkItem`, `CommentEvent`, and `PullRequestEvent` models plus the `TrackerAdapter` protocol.
- `adapters/github.py`: First-class GitHub GraphQL adapter with bounded pagination and zero third-party pip dependencies.
- `intake_filter.py`: Pure deterministic policy engine (`factory:ready` opt-in, `factory:hold` and `intake.paused` veto, `Depends on #N` gating, SEP `max_concurrent_issues` 1–3 cap, anti-echo bot and `<!-- scion-factory -->` suppression).
- `state_store.py`: Optimistic-concurrency cursor storage in GCS (`ifGenerationMatch`) and atomic local file storage.
- `hub_notifier.py`: Authenticated Scion Hub client using GCP SA OIDC (`oidc_allowed_gcp_projects`) sending `wake=true` payloads.
- `watcher.py`: Idempotent `run_tick` orchestrator with Hub off-hours rollback plus backward-compatible CLI diff helper.
- `server.py`: Thin Cloud Run HTTP composition root (`GET /healthz`, `POST /tick`) emitting structured JSON telemetry logs.
- `Dockerfile`: Non-root `python:3.12-slim` image with zero external pip dependencies.

## Why Cloud Run + Cloud Scheduler (`WK-003`)

- Keeps backlog intake independent of GitHub Actions or inbound internet webhooks.
- Reaches private VPC / IAP-protected Scion Hubs via Direct VPC Egress and GCP SA OIDC.
- Runs deterministically at `0` LLM tokens and survives scheduled Hub VM off-hours cleanly.
