# Code Reviewer Pack Delta (`packs/adk`)

1. Execute a blind independent review using a distinct model family/provider from the `adk-developer` per `diversity_profile`.
2. Block any PR that breaks modular boundaries (`agent.py > 250` lines), initializes network clients at import time, or gates `FunctionTool` type hints behind `TYPE_CHECKING`.
3. Block any PR that sets `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT="true"`, omits `McpToolset` cache TTL, or injects per-span `traceparent` into `header_provider`.
4. Verify `ge_manifest.json` passes `schemas/ge-export.schema.json` and contains zero customer secrets, unapproved endpoints, or hardcoded production OAuth tokens.
5. Flag any simultaneous edit to `agent/` and `evals/` lacking an explicit human `eval-change-approved` instruction.
6. Verify zero PII (real emails, phone numbers, tax IDs, tokens) exists in tests, fixtures, or synthetic eval datasets.
