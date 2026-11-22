# Security Auditor Pack Delta (`packs/gecx`)

1. Operate under the Inference Project worker Service Account (`--role baseline`) as a single specialist pass on the reviewed head just before PR submission.
2. Verify every sensitive CX Agent Studio tool enforces deterministic auth checks in callbacks or tool guards (`context.state`) rather than relying only on LLM prompt instructions.
3. Audit `evals/`, fixtures, and tests for zero real customer PII (CPF, phone numbers, real invoices, or real audio recordings) and zero static JSON service account keys.
4. Audit Terraform, scripts, and configs for zero predefined `roles/ces.*` bindings, zero wildcard IAM permissions, and zero floating `@main` or `gh://` URIs.
5. Classify every finding by severity and hold PR submission only for Critical or High risks above the project hold threshold.
