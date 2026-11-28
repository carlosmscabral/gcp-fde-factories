#!/usr/bin/env python3
"""Thin CLI composition root for Day-0 onboarding, unified validate(), and Day-2 drift (Wave 2).

Owns zero-token <2s Tier-A scanning (with zero jsonschema dependency on `scan`), 2-block
/grill-me draft generation, unified fail-closed `validate` (schema + confirmed_by + AGENTS.md
<= 6 KB + 4-rule Dockerfile lint + skill collisions), atomic Layer 3 `.factory/[<prefix>/]factory.yaml`
emission with --dry-run and --pr, plus backward-compatible aliases (`check`, `kp-check`, `validate-dockerfile`).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import yaml

SCRIPT_ROOT = pathlib.Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_ROOT.parent.parent if (SCRIPT_ROOT.parent.parent / "scripts" / "lib").exists() else SCRIPT_ROOT
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.lib.dockerfile_recipes import validate_customer_dockerfile
from scripts.lib.io_utils import load_yaml
from scripts.lib.onboard_emitter import check_readiness, emit_layer3_overlay
from scripts.lib.onboard_factory_v2 import check_v2_readiness, validate_factory_repo
from scripts.lib.onboard_git_ops import open_onboarding_pr
from scripts.lib.onboard_kp import check_knowledge_plane
from scripts.lib.onboard_questions import build_draft_profile
from scripts.lib.onboard_scanner import detect_repo_drift, scan_repository_facts


def _resolve_toolchain_manifest(explicit: pathlib.Path | None, pack: str | None) -> pathlib.Path | None:
    """Resolves toolchain-manifest.json from explicit path or packs/<pack>/ when available."""
    if explicit is not None:
        return explicit
    if not pack:
        return None
    for cand in (
        REPO_ROOT / "packs" / pack / "toolchain-manifest.json",
        pathlib.Path(f"/opt/gcp-fde/{pack}-toolchain-manifest.json"),
    ):
        if cand.is_file():
            return cand
    return None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parses scan, validate, emit, and legacy check/kp-check/validate-dockerfile subcommands."""
    parser = argparse.ArgumentParser(description="Universal <2s scanner, unified validate(), and Layer 3 emitter.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser("scan")
    p_scan.add_argument("--repo", type=pathlib.Path, required=True)
    p_scan.add_argument("--toolchain-manifest", type=pathlib.Path, default=None)
    p_scan.add_argument("--pack", choices=("adk", "gecx", "generic"), default=None)
    p_scan.add_argument("--track", choices=("express", "complete"), default="complete", help="Deprecated alias; 2-block interview is unified.")
    p_scan.add_argument("--roster-preset", choices=("lean", "full"), default="lean", help="Default 5-role lean preset or full agent-team SEP roster.")
    p_scan.add_argument("--format", choices=("v2", "v1"), default="v2", help="Draft schema format (v2=.factory/factory.yaml default, v1=legacy).")
    p_scan.add_argument("--emit-draft", type=pathlib.Path, default=None)
    p_scan.add_argument("--config", type=pathlib.Path, default=None, help="Explicit factory.yaml path for --drift.")
    p_scan.add_argument("--drift", action="store_true")
    p_scan.add_argument("--json", action="store_true", help="Emit JSON output (default behavior).")
    p_scan.add_argument("--out", type=pathlib.Path, default=None)

    p_validate = sub.add_parser("validate", help="Unified fail-closed check: schema, confirmed_by, AGENTS.md <= 6 KB, links, collisions, and Dockerfile.")
    p_validate.add_argument("--repo", type=pathlib.Path, required=True)
    p_validate.add_argument("--config", type=pathlib.Path, default=None, help="Optional relative or absolute path to .factory/[<prefix>/]factory.yaml.")
    p_validate.add_argument("--advisory-dockerfile", action="store_true", help="Downgrade Dockerfile linter findings to advisory.")
    p_validate.add_argument("--json", action="store_true", help="Emit JSON output (default behavior).")

    p_check = sub.add_parser("check")
    p_check.add_argument("--profile", type=pathlib.Path, required=True)
    p_check.add_argument("--json", action="store_true", help="Emit JSON output (default behavior).")
    p_check.add_argument("--schema", type=pathlib.Path, default=None)

    p_emit = sub.add_parser("emit")
    p_emit.add_argument("--repo", type=pathlib.Path, required=True)
    p_emit.add_argument("--profile", type=pathlib.Path, required=True)
    p_emit.add_argument("--pack-image", required=True)
    p_emit.add_argument("--force-knowledge", action="store_true", help="Overwrite existing .factory/knowledge/* files.")
    p_emit.add_argument("--dry-run", action="store_true", help="Preview unified diffs without writing any files.")
    p_emit.add_argument("--pr", action="store_true", help="Commit emitted files on a branch, push origin, and open a PR via gh.")
    p_emit.add_argument("--acknowledge-workspace-hazards", action="store_true", help="Confirm untrusted workspace hooks/MCP were reviewed and neutralized.")
    p_emit.add_argument("--json", action="store_true", help="Emit JSON output (default behavior).")
    p_emit.add_argument("--schema", type=pathlib.Path, default=REPO_ROOT / "schemas" / "factory-profile.schema.json")

    p_kp = sub.add_parser("kp-check")
    p_kp.add_argument("--repo", type=pathlib.Path, required=True)
    p_kp.add_argument("--json", action="store_true", help="Emit JSON output (default behavior).")

    p_val = sub.add_parser("validate-dockerfile")
    p_val.add_argument("--dockerfile", type=pathlib.Path, required=True)
    p_val.add_argument("--verify-binary", action="append", default=[], help="Repeatable smoke-check command expected after USER.")
    p_val.add_argument("--strict", action="store_true", help="Fail closed on security and smoke-check findings.")
    p_val.add_argument("--json", action="store_true", help="Emit JSON output (default behavior).")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Dispatches scan, validate, emit, or legacy check/kp-check/validate-dockerfile subcommands."""
    args = parse_args(argv)
    try:
        if args.cmd == "validate":
            if not args.repo.is_dir():
                raise ValueError(f"Repository directory does not exist: {args.repo}")
            report = validate_factory_repo(
                args.repo,
                config_path=args.config,
                schemas_dir=REPO_ROOT / "schemas",
                strict_dockerfile=not args.advisory_dockerfile,
            )
            print(json.dumps(report, indent=2))
            return 0 if report["ok"] else 1

        if args.cmd == "validate-dockerfile":
            report = validate_customer_dockerfile(
                args.dockerfile,
                strict=args.strict,
                verify_binaries=args.verify_binary or None,
            )
            print(json.dumps(report, indent=2))
            return 0 if report["ok"] else 1

        if args.cmd == "kp-check":
            if not args.repo.is_dir():
                raise ValueError(f"Repository directory does not exist: {args.repo}")
            report = check_knowledge_plane(args.repo)
            print(json.dumps(report, indent=2))
            return 0 if report["ok"] else 1

        if args.cmd == "scan":
            if not args.repo.is_dir():
                raise ValueError(f"Repository directory does not exist: {args.repo}")
            tc_manifest = _resolve_toolchain_manifest(args.toolchain_manifest, args.pack)
            payload = (
                detect_repo_drift(args.repo, tc_manifest, config_path=args.config)
                if args.drift
                else scan_repository_facts(
                    args.repo,
                    tc_manifest,
                    pack=args.pack,
                    track=args.track,
                    roster_preset=args.roster_preset,
                )
            )
            if args.emit_draft and not args.drift:
                draft = build_draft_profile(
                    payload,
                    pack=args.pack,
                    track=args.track,
                    roster_preset=args.roster_preset,
                    schema_version="2" if args.format == "v2" else "1",
                )
                args.emit_draft.parent.mkdir(parents=True, exist_ok=True)
                args.emit_draft.write_text(yaml.safe_dump(draft, sort_keys=False), encoding="utf-8")
                payload["draft_profile_path"] = str(args.emit_draft)
            encoded = json.dumps(payload, indent=2) + "\n"
            if args.out:
                args.out.parent.mkdir(parents=True, exist_ok=True)
                args.out.write_text(encoded, encoding="utf-8")
            else:
                print(encoded, end="")
            return 0

        profile = load_yaml(args.profile)
        if not isinstance(profile, dict):
            raise ValueError(f"Profile must be a YAML mapping: {args.profile}")

        if args.cmd == "check":
            is_v2 = str(profile.get("schema_version") or "1") == "2"
            schema_path = args.schema or (
                REPO_ROOT / "schemas" / ("factory.schema.json" if is_v2 else "factory-profile.schema.json")
            )
            report = check_v2_readiness(profile, schema_path) if is_v2 else check_readiness(profile, schema_path)
            print(json.dumps(report, indent=2))
            return 0 if report["ready"] else 1

        result = emit_layer3_overlay(
            args.repo,
            profile,
            args.pack_image,
            args.schema,
            force_knowledge=args.force_knowledge,
            dry_run=args.dry_run,
            acknowledge_hazards=args.acknowledge_workspace_hazards,
        )
        if args.pr and args.dry_run:
            result["pr_landing"] = {"status": "skipped", "reason": "dry_run"}
        elif args.pr:
            base_branch = str((profile.get("git_flow") or {}).get("base_branch") or "main")
            result["pr_landing"] = open_onboarding_pr(args.repo.resolve(), str(profile["slug"]), base_branch, result["emitted_files"])
        print(json.dumps(result, indent=2))
        if args.dry_run and result.get("blocking_hazards") and not args.acknowledge_workspace_hazards:
            return 2
        return 0
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
