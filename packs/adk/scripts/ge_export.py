#!/usr/bin/env python3
"""Thin CLI entrypoint for validating, exporting, registering, patching, and deleting Gemini Enterprise agents.

Delegates payload construction, schema validation, and REST calls to packs/adk/scripts/lib/ge_payload.py.
Requires explicit ADK_DEPLOYER_OAUTH_TOKEN for live mutations (no silent ambient token fallback).
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent.parent
for candidate in (REPO_ROOT, SCRIPT_DIR.parent.parent, SCRIPT_DIR, pathlib.Path("/opt/gcp-fde")):
    if candidate.exists() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

try:
    from packs.adk.scripts.lib.ge_payload import (
        default_ge_schema,
        delete_ge_agent,
        export_ge_bundle,
        patch_ge_agent,
        register_ge_agent,
        validate_ge_manifest,
    )
except ModuleNotFoundError:
    from lib.ge_payload import (
        default_ge_schema,
        delete_ge_agent,
        export_ge_bundle,
        patch_ge_agent,
        register_ge_agent,
        validate_ge_manifest,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parses CLI subcommands for Gemini Enterprise export and Sandbox registration."""
    schema_default = default_ge_schema(REPO_ROOT)
    parser = argparse.ArgumentParser(description="Validate, export, and register ADK agents in Gemini Enterprise.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_val = sub.add_parser("validate")
    p_val.add_argument("--manifest", type=pathlib.Path, required=True)
    p_val.add_argument("--schema", type=pathlib.Path, default=schema_default)

    p_exp = sub.add_parser("export")
    p_exp.add_argument("--manifest", type=pathlib.Path, required=True)
    p_exp.add_argument("--out", type=pathlib.Path, required=True)
    p_exp.add_argument("--display-name", default="")
    p_exp.add_argument("--commit-sha", default="")
    p_exp.add_argument("--evals-hash", default="")
    p_exp.add_argument("--schema", type=pathlib.Path, default=schema_default)

    p_reg = sub.add_parser("register")
    p_reg.add_argument("--manifest", type=pathlib.Path, required=True)
    p_reg.add_argument("--display-name", default="")
    p_reg.add_argument("--reasoning-engine", default="")
    p_reg.add_argument("--quota-project", default="")
    p_reg.add_argument("--schema", type=pathlib.Path, default=schema_default)

    p_patch = sub.add_parser("patch")
    p_patch.add_argument("--agent-name", required=True)
    p_patch.add_argument("--manifest", type=pathlib.Path, required=True)
    p_patch.add_argument("--display-name", default="")
    p_patch.add_argument("--reasoning-engine", default="")
    p_patch.add_argument("--quota-project", required=True)
    p_patch.add_argument("--schema", type=pathlib.Path, default=schema_default)

    p_del = sub.add_parser("delete")
    p_del.add_argument("--agent-name", required=True)
    p_del.add_argument("--endpoint-location", default="", choices=["", "global", "us", "eu"])
    p_del.add_argument("--quota-project", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Runs the selected Gemini Enterprise export or registration subcommand."""
    args = parse_args(argv)
    if args.cmd == "delete":
        token = os.environ.get("ADK_DEPLOYER_OAUTH_TOKEN", "").strip()
        if not token:
            print("Missing explicit ADK_DEPLOYER_OAUTH_TOKEN for delete.", file=sys.stderr)
            return 1
        try:
            status, body = delete_ge_agent(args.agent_name, args.endpoint_location, token, args.quota_project)
        except ValueError as exc:
            print(f"GE DELETE REFUSED: {exc}", file=sys.stderr)
            return 1
        print(json.dumps({"status": status, "body": body}, indent=2))
        return 0 if 200 <= status < 300 else 1

    spec = json.loads(args.manifest.read_text(encoding="utf-8"))
    if args.cmd == "validate":
        errors = validate_ge_manifest(spec, args.schema)
        if errors:
            for err in errors:
                print(f"GE MANIFEST ERROR: {err}", file=sys.stderr)
            return 1
        print(f"GE MANIFEST OK ({spec['export_mode']}): {spec['display_name']}")
        return 0

    if args.cmd == "export":
        try:
            manifest = export_ge_bundle(
                spec,
                args.out,
                args.schema,
                display_name_override=args.display_name,
                commit_sha=args.commit_sha,
                evals_tree_sha256=args.evals_hash,
            )
        except ValueError as exc:
            print(f"GE EXPORT ERROR: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(manifest, indent=2))
        return 0

    errors = validate_ge_manifest(spec, args.schema)
    if errors:
        for err in errors:
            print(f"GE MANIFEST ERROR: {err}", file=sys.stderr)
        return 1
    token = os.environ.get("ADK_DEPLOYER_OAUTH_TOKEN", "").strip()
    if not token:
        print(f"Missing explicit ADK_DEPLOYER_OAUTH_TOKEN for {args.cmd}.", file=sys.stderr)
        return 1

    if args.cmd == "patch":
        try:
            status, body = patch_ge_agent(
                args.agent_name,
                spec,
                token,
                args.quota_project,
                display_name_override=args.display_name,
                reasoning_engine_override=args.reasoning_engine,
            )
        except ValueError as exc:
            print(f"GE PATCH REFUSED: {exc}", file=sys.stderr)
            return 1
        print(json.dumps({"status": status, "body": body}, indent=2))
        return 0 if 200 <= status < 300 else 1

    quota_proj = args.quota_project or spec["gemini_enterprise"]["project_id"]
    status, body = register_ge_agent(
        spec,
        token,
        quota_proj,
        display_name_override=args.display_name,
        reasoning_engine_override=args.reasoning_engine,
    )
    print(json.dumps({"status": status, "body": body}, indent=2))
    return 0 if 200 <= status < 300 else 1


if __name__ == "__main__":
    raise SystemExit(main())
