#!/usr/bin/env python3
"""Thin CLI orchestrating static pack checks and offline Release Kit generation."""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.lib.budget_engine import check_context_budget, check_workarounds_ttl
from scripts.lib.io_utils import load_json, load_yaml
from scripts.lib.lock_verifier import scan_for_floating_uris, verify_skills_lock
from scripts.lib.release_kit import build_release_kit
from scripts.lib.sanitizer import scan_repository
from scripts.lib.schema_validator import validate_against_schema, validate_yaml_file


def run_check(pack_rel: str) -> int:
    """Runs all static contract, lockfile, budget, TTL, and sanitization checks."""
    pack_dir = (REPO_ROOT / pack_rel).resolve()
    schemas_dir = REPO_ROOT / "schemas"
    errors: list[str] = []

    errors.extend(validate_yaml_file(pack_dir / "pack.yaml", schemas_dir / "pack.schema.json"))
    errors.extend(validate_yaml_file(REPO_ROOT / "compat.yaml", schemas_dir / "compat.schema.json"))

    pack_compat = pack_dir / "compat.yaml"
    compat_path = pack_compat if pack_compat.exists() else REPO_ROOT / "compat.yaml"
    if pack_compat.exists():
        errors.extend(validate_yaml_file(pack_compat, schemas_dir / "compat.schema.json"))

    if (pack_dir / "pack.yaml").exists() and compat_path.exists():
        pack_cfg = load_yaml(pack_dir / "pack.yaml")
        compat_cfg = load_yaml(compat_path)
        pack_name = str(pack_cfg["pack"]["name"])
        pack_version = str(pack_cfg["pack"]["version"])
        if compat_cfg.get("pack") != pack_name:
            errors.append(
                f"compat.yaml pack '{compat_cfg.get('pack')}' does not match pack.yaml '{pack_name}'."
            )
        if compat_cfg.get("pack_version") != pack_version:
            errors.append(
                f"compat.yaml pack_version '{compat_cfg.get('pack_version')}' does not match pack.yaml '{pack_version}'."
            )
        images = compat_cfg.get("images", {})
        if f"{pack_name}-runtime" not in images and f"scion-{pack_name}-runtime" not in images:
            errors.append(f"compat.yaml images lacks '{pack_name}-runtime' digest for pack '{pack_name}'.")
        df_rel = str(pack_cfg.get("runtime_image", {}).get("dockerfile") or "")
        df_candidates = [REPO_ROOT / df_rel, pack_dir / pathlib.Path(df_rel).name] if df_rel else []
        if not df_rel or not any(cand.is_file() for cand in df_candidates):
            errors.append(f"pack.yaml runtime_image.dockerfile not found: '{df_rel}'.")

    overlay_cfg = pack_dir / "repo-scaffold" / ".factory" / "hub-project.yaml"
    if overlay_cfg.exists():
        errors.extend(validate_yaml_file(overlay_cfg, schemas_dir / "hub-project.schema.json"))

    for schema_name in (
        "kaizen-snapshot.schema.json",
        "kaizen-proposal.schema.json",
        "factory-profile.schema.json",
        "ge-export.schema.json",
        "verdict.schema.json",
    ):
        schema_path = schemas_dir / schema_name
        if not schema_path.exists():
            errors.append(f"Missing required schema: {schema_path}")
        else:
            load_json(schema_path)

    toolchain_path = pack_dir / "toolchain-manifest.json"
    if toolchain_path.exists():
        tc = load_json(toolchain_path)
        if not isinstance(tc.get("baked_binaries"), dict) or not tc.get("pack"):
            errors.append(
                f"Invalid toolchain-manifest.json at {toolchain_path}: requires 'pack' and 'baked_binaries' object."
            )

    ge_manifest_path = pack_dir / "repo-scaffold" / "ge_manifest.json"
    if ge_manifest_path.exists():
        errors.extend(validate_against_schema(load_json(ge_manifest_path), schemas_dir / "ge-export.schema.json"))

    errors.extend(verify_skills_lock(REPO_ROOT / "skills.lock"))
    errors.extend(scan_for_floating_uris(pack_dir))
    errors.extend(scan_for_floating_uris(REPO_ROOT / "core-gcp-fde"))

    budget_errs, report = check_context_budget(REPO_ROOT, pack_dir, overlay_cfg if overlay_cfg.exists() else None)
    errors.extend(budget_errs)
    errors.extend(check_workarounds_ttl(REPO_ROOT / "WORKAROUNDS.yaml"))
    errors.extend(scan_repository(REPO_ROOT))

    # Enforce AGENTS.md, CLAUDE.md, and GEMINI.md byte parity inside repo-scaffold/.
    scaffold = pack_dir / "repo-scaffold"
    if (scaffold / "AGENTS.md").exists():
        base = (scaffold / "AGENTS.md").read_bytes()
        for sibling in ("CLAUDE.md", "GEMINI.md"):
            sib_path = scaffold / sibling
            if not sib_path.exists() or sib_path.read_bytes() != base:
                errors.append(f"Scaffold parity failure: {sib_path} differs from AGENTS.md.")

    if errors:
        print(f"CHECK FAILED ({len(errors)} error(s)):", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(f"CHECK PASSED for {pack_rel}.")
    print(json.dumps(report, indent=2))
    return 0


def run_release_kit(pack_rel: str, out_path: str) -> int:
    """Validates pack first, then generates a self-contained offline Release Kit."""
    rc = run_check(pack_rel)
    if rc != 0:
        return rc

    pack_dir = (REPO_ROOT / pack_rel).resolve()
    out_dir = pathlib.Path(out_path).resolve()
    manifest = build_release_kit(REPO_ROOT, pack_dir, out_dir)

    if manifest["external_uris_remaining"] != 0:
        print("RELEASE KIT FAILED: external URIs detected in generated templates.", file=sys.stderr)
        return 1

    print(f"RELEASE KIT READY: {out_dir}")
    print(f"  Pack:            {manifest['pack']}@{manifest['pack_version']}")
    print(f"  Templates:       {len(manifest['templates'])}")
    print(f"  Skills:          {len(manifest['skills'])}")
    print(f"  Harness Configs: {', '.join(manifest['harness_configs'])}")
    return 0


def main() -> int:
    """Parses CLI subcommands and dispatches check or release-kit builds."""
    parser = argparse.ArgumentParser(description="Build and check gcp-fde-factories packs.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_check = sub.add_parser("check")
    p_check.add_argument("--pack", required=True)

    p_kit = sub.add_parser("release-kit")
    p_kit.add_argument("--pack", required=True)
    p_kit.add_argument("--out", required=True)

    args = parser.parse_args()
    if args.cmd == "check":
        return run_check(args.pack)
    return run_release_kit(args.pack, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
