# Engineering Invariants

- **INV-001:** Every callback under `cxas_app/*/agents/*/before_model_callbacks/` has a matching offline pytest in `evals/callback_tests/`.
- **INV-002:** Zero real customer PII appears in `evals/` or fixture files.
- **INV-003:** Production promotions execute exclusively from GitHub Actions via Workload Identity Federation after human PR approval.
