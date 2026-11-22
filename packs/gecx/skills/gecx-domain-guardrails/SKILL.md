---
name: gecx-domain-guardrails
description: Distilled Google Cloud CX Agent Studio (GECX / CES) engineering guardrails backed by public sources and canary proofs.
---

# GECX Domain Guardrails

## 1. Staging Bucket Requirement for Audio Evaluations
- Set `audioRecordingConfig.gcsBucket` in `app.json` to the Sandbox staging bucket from `environment.sandbox.json` during Sandbox pushes.
- Confirm the CES Service Agent holds `roles/storage.objectUser` on that bucket so `cxas push` exits cleanly without warnings.
- source: https://cloud.google.com/customer-engagement-ai/conversational-agents/ps/reference/rest

## 2. Deterministic Callbacks vs. LLM Prompting
- Implement strict state transitions, silence counters, session-start greetings, and deterministic escalation payloads in `before_model_callbacks` rather than relying solely on prompt prose.
- Provide matching `evals/callback_tests/tests/<agent>/<type>/<name>/test.py` tests and sync them via `sync-callbacks.py --from-local` before running `cxas test-callbacks`.
- source: https://github.com/GoogleCloudPlatform/cxas-scrapi/tree/f55e877638dfc07879aad4082abc35c34f18359c/.agents/skills/cxas-agent-foundry

## 3. Zero-PII Sandbox and Evaluation Hygiene
- Never use predefined `roles/ces.*` for factory agents because all 11 predefined roles include `contactcenterinsights.*` and `ces.conversations.*` permissions.
- Keep `evals/` 100% synthetic. Any change touching both `cxas_app/` and `evals/` requires the human `eval-change-approved` PR label.
- source: https://cloud.google.com/iam/docs/understanding-roles

## 4. Telephony Boundary Honesty
- Classify changes touching SIP trunks, SBCs, AudioCodes VAIC, carrier 8 kHz audio, DTMF signaling, or live CCaaS handoff as `not-verifiable-in-sandbox`.
- Pilot 1 validates text evaluations and synthetic `Sessions.async_bidi_run_session` audio only.
- source: https://github.com/GoogleCloudPlatform/cxas-scrapi
