# `_template-pack`

Copy this directory to `packs/<new-domain>/` when creating a new Google Cloud FDE Factory Pack.

## Checklist

1. Set `pack.name` and `pack.prefix` in `pack.yaml` so every template isolates cleanly on the Scion Hub.
2. Add domain skills under `skills/<skill-name>/SKILL.md` with an explicit `source:` field on every normative rule and `<= 300` lines per skill.
3. Add 1 to 2 specialist role deltas under `templates/<role>/delta.md` (`<= 15` rules each).
4. Provide `repo-scaffold/` and deterministic verification runners under `scripts/`.
5. Validate with `./build.sh --check packs/<new-domain>`.
