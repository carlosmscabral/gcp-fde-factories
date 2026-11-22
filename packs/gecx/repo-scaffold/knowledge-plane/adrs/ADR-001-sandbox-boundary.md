# ADR-001 — Sandbox Zero-PII and Promotion Boundary

- **Status:** Accepted
- **Decision:** Autonomous factory agents deploy only ephemeral `[CI]` apps into the disposable Sandbox GCP project using split custom IAM roles (`gecxSandboxDeployer` and `gecxSandboxEvaluator`). Upper environments (DEV, HML, PRD) receive deployments exclusively via customer GitHub Actions WIF after human merge approval.
