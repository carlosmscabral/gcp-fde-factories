# Code-Reviewer Pack Delta (`packs/gecx`)

1. Execute blind reviews on a model distinct from `developer` as declared in `.factory/hub-project.yaml` `diversity_profile`.
2. Verify all Level 1 offline gates pass and inspect `evals/` diffs for relaxed expectations or PII patterns.
3. Verify any callback or tool edits follow `/opt/gecx-foundry/references/` contracts and include matching deterministic unit tests.
4. Reject any PR claiming `live-gcp-verified` if the diff touches telephony, SIP, SBC, VAIC, DTMF, or CCaaS transfer surfaces (require `not-verifiable-in-sandbox`).
5. Never approve a PR that introduces floating `@main`/`HEAD` URIs, static JSON keys, or predefined `roles/ces.*` bindings.
