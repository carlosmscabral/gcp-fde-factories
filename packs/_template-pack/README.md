# `_template-pack`

Copy this directory to `packs/<new-domain>/` when creating a new Google Cloud FDE Factory Pack.

## Checklist

1. Set `pack.name`, `pack.prefix`, and `runtime_image.dockerfile` (`packs/<new-domain>/Dockerfile`) in `pack.yaml` so every template isolates cleanly on the Scion Hub.
2. Update `compat.yaml` to set `pack: <new-domain>` and rename `images.example-pack-runtime` to `images.<new-domain>-runtime`.
3. Add domain skills under `skills/<skill-name>/SKILL.md` with an explicit `source:` field on every normative rule and `<= 300` lines per skill.
4. Add 1 to 2 specialist role deltas under `templates/<role>/delta.md` (`<= 15` rules each).
5. Provide `repo-scaffold/` and deterministic verification runners under `scripts/`.
6. Validate with `./build.sh --check packs/<new-domain>` and build a Release Kit with `./build.sh --release-kit packs/<new-domain> --out /tmp/<new-domain>-kit`.
