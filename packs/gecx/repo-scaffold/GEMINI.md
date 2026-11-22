# Customer GECX Repository Rules (Canonical Source)

NOTE: Keep `AGENTS.md`, `CLAUDE.md`, and `GEMINI.md` byte-identical. CI blocks any PR where these three files diverge.

## 1. Repository Boundaries
- Edit application code under `cxas_app/` and synthetic tests under `evals/`.
- Never commit real customer PII (CPF, phone numbers, email addresses, card numbers, or production call audio).
- Never modify `cxas_app/` and `evals/` in the same PR without the human `eval-change-approved` label.

## 2. Verification Requirements
- Run Level 1 offline gates (`cxas lint`, `sync-callbacks.py --from-local`, `cxas test-callbacks`, `pytest`) before requesting review.
- Keep `knowledge-plane/requirements.md` and `knowledge-plane/invariants.md` updated with every behavioral change.
- Classify telephony, SIP, SBC, VAIC, DTMF, or live CCaaS changes as `not-verifiable-in-sandbox`.
