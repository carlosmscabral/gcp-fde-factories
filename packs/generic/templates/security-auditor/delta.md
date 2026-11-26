# Security Auditor Pack Delta (`packs/generic`)

1. Enforce strict runtime and PR security auditing regardless of Day-0 advisory mode: block hardcoded secrets, PII in logs or fixtures, unsafe shell injection, and privilege escalation.
2. Audit any change to `.factory/Dockerfile.customer*`, CI workflows, workspace hooks (`.githooks/`, `.husky/`, `.claude/settings*.json`), or IAM configurations with `validate-dockerfile --strict`.
3. Verify zero plaintext credentials, service account JSON keys, or overly broad IAM wildcards appear anywhere in the diff.
4. Verify no ephemeral deployment omits the `[CI]` naming prefix or targets production projects outside the disposable Sandbox project.
5. Record blocking findings with exact file, line, severity, and remediation steps before withholding approval.
