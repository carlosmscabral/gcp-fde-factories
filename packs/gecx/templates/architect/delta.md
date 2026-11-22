# Architect Pack Delta (`packs/gecx`)

1. Operate under the Inference Project worker Service Account (`--role baseline`) and read investigator findings before designing.
2. Structure CX Agent Studio designs around explicit `root_agent`, child sub-agents, deterministic Python callbacks, typed tools, and separate `evals/` coverage.
3. Verify JSON shapes and callback contracts against `/opt/gecx-foundry/references/api-schemas/` instead of guessing CES fields.
4. State explicitly which implementation phases gate parallel fan-out (for example shared `app.json` and auth callbacks before parallel domain sub-agents).
5. Flag any requirement touching SIP, SBC, AudioCodes VAIC, DTMF, or CCaaS transfer as `not-verifiable-in-sandbox` and list the manual verification surfaces.
6. Deliver design documents directly for human discussion and approval. Never trigger an agent code-review loop on prose-only architecture docs.
