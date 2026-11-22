# Repository Engineering Rules (`gcp-fde-factories`)

## Modularity and Entrypoints

1. Keep `build.sh` and scripts in `scripts/` as thin composition roots (`<= 150` lines).
2. Place reusable Python logic in single-responsibility modules under `scripts/lib/` (`<= 250` lines per module) with acyclic imports and lazy I/O.
3. Document every module, function, and script with "Why"-focused ASD-STE100 comments (active voice, explicit actor, short sentences, zero semicolons in prose).

## Security and Clean-Room Boundaries

1. Never commit internal Google links (`go/`, `b/`), `@google.com` addresses, customer identifiers, or Tier-C internal denylists to this repository.
2. Attach an explicit `source:` field (public URL or reproducible `canaries/` test) to every normative domain rule added under `packs/*/skills/`.
3. Never commit floating `@main`, `@HEAD`, or unpinned skill URIs. Update `skills.lock` and `compat.yaml` together in planned upgrade windows.

## Verification Gates

1. Run `./build.sh --check packs/gecx` and `./build.sh --test` before opening any pull request.
2. Run `terraform validate` across `deploy/01-landing-zone` and `deploy/02-factory-runtime/*` after any Terraform edit.
3. Keep `AGENTS.md`, `CLAUDE.md`, and `GEMINI.md` byte-identical inside `packs/*/repo-scaffold/`.
