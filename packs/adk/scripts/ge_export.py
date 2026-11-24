#!/usr/bin/env python3
"""Thin CLI entrypoint for validating, exporting, registering, and deleting Gemini Enterprise agents.

Delegates payload construction, schema validation, and REST calls to packs/adk/scripts/lib/ge_payload.py.
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
        delete_ge_agent,
        export_ge_bundle,
        register_ge_agent,
        validate_ge_manifest,
    )
except ModuleNotFoundError:
    from lib.ge_payload import (
        delete_ge_agent,
        export_ge_bundle,
        register_ge_agent,
        validate_ge_manifest,
    )


def _default_schema() -> pathlib.Path:
    """Locates schemas/ge-export.schema.json inside repo or container /opt/gcp-fde."""
    for cand in (
        REPO_ROOT / "schemas" / "ge-export.schema.json",
        pathlib.Path("/opt/gcp-fde/schemas/ge-export.schema.json"),
    ):
        if cand.exists():
            return cand
    return REPO_ROOT / "schemas" / "ge-export.schema.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parses CLI subcommands for Gemini Enterprise export and Sandbox registration."""
    parser = argparse.ArgumentParser(description="Validate, export, and register ADK agents in Gemini Enterprise.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_val = sub.add_parser("validate")
    p_val.add_argument("--manifest", type=pathlib.Path, required=True)
    p_val.add_argument("--schema", type=pathlib.Path, default=_default_schema())

    p_exp = sub.add_parser("export")
    p_exp.add_argument("--manifest", type=pathlib.Path, required=True)
    p_exp.add_argument("--out", type=pathlib.Path, required=True)
    p_exp.add_argument("--display-name", default="")
    p_exp.add_argument("--schema", type=pathlib.Path, default=_default_schema())

    p_reg = sub.add_parser("register")
    p_reg.add_argument("--manifest", type=pathlib.Path, required=True)
    p_reg.add_argument("--display-name", default="")
    p_reg.add_argument("--quota-project", default="")
    p_reg.add_argument("--schema", type=pathlib.Path, default=_default_schema())

    p_del = sub.add_parser("delete")
    p_del.add_argument("--agent-name", required=True)
    p_del.add_argument("--endpoint-location", default="global", choices=["global", "us", "eu"])
    p_del.add_argument("--quota-project", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Runs the selected Gemini Enterprise export or registration subcommand."""
    args = parse_args(argv)
    if args.cmd == "delete":
        token = os.environ.get("ADK_DEPLOYER_OAUTH_TOKEN") or os.environ.get("GOOGLE_OAUTH_ACCESS_TOKEN", "")
        if not token:
            print("Missing ADK_DEPLOYER_OAUTH_TOKEN for delete.", file=sys.stderr)
            return 1
        status, body = delete_ge_agent(args.agent_name, args.endpoint_location, token, args.quota_project)
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
        manifest = export_ge_bundle(spec, args.out, args.schema, display_name_override=args.display_name)
        print(json.dumps(manifest, indent=2))
        return 0

    errors = validate_ge_manifest(spec, args.schema)
    if errors:
        for err in errors:
            print(f"GE MANIFEST ERROR: {err}", file=sys.stderr)
        return 1
    token = os.environ.get("ADK_DEPLOYER_OAUTH_TOKEN") or os.environ.get("GOOGLE_OAUTH_ACCESS_TOKEN", "")
    if not token:
        print("Missing ADK_DEPLOYER_OAUTH_TOKEN for register.", file=sys.stderr)
        return 1
    quota_proj = args.quota_project or spec["gemini_enterprise"]["project_id"]
    status, body = register_ge_agent(spec, token, quota_proj, display_name_override=args.display_name)
    print(json.dumps({"status": status, "body": body}, indent=2))
    return 0 if 200 <= status < 300 else 1


if __name__ == "__main__":
    raise SystemExit(main())
