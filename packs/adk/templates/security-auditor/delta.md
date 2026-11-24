# Security Auditor Pack Delta (`packs/adk`)

1. Verify strict 4-SA split-IAM boundaries: Worker SA has inference only, Deployer SA writes Sandbox only, Evaluator SA probes Sandbox only, and Janitor SA stays off Scion Hub.
2. Inspect `ge_manifest.json` `tool_authorizations` and A2A `url` settings to confirm HTTPS-only endpoints, least-privilege OAuth scopes, and zero hardcoded credentials.
3. Audit tool handlers and prompt templates for prompt-injection vectors, SSRF in custom HTTP tools, and PII leakage in OpenTelemetry spans or logs.
4. Confirm production Gemini Enterprise registration and DEV/HML/PRD Agent Engine promotion occur strictly via customer CI/WIF after human approval.
5. Verify no untrusted external `gh://`, unpinned package dependencies, or duplicate `deployment/terraform/` IAM files enter `pyproject.toml` or `Dockerfile`.
