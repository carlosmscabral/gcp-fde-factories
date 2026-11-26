# Test Engineer Pack Delta (`packs/generic`)

1. Align all automated tests with `commands.test`, `commands.e2e`, and `evaluation_pyramid` in `.factory/factory-profile.yaml`.
2. Use synthetic, non-PII fixtures only. Never commit customer identifiers, real tokens, or live production dumps in tests.
3. Verify offline tests pass with scrubbed GCP credentials via `python3 /opt/generic-factory/generic_sandbox_gate.py --level 1`.
4. Place heavy browser or JDK test tooling in `.factory/Dockerfile.customer-tester` rather than bloating the core runtime image.
