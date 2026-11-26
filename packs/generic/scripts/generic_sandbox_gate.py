#!/usr/bin/env python3
"""Profile-driven Level 1 offline and Level 2 sandbox verification gate for packs/generic (ADR-016).

Enforces strict L1 environment allowlisting (scrubbing all GOOGLE_*/CLOUDSDK_* credentials and
pointing GCE_METADATA_HOST to a closed loopback port), fails closed on L2 when deploy_target
requires live E2E, and supports --base-ref so PR diffs cannot weaken profile commands.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import tempfile
from typing import Any

import yaml

PLACEHOLDER_MARKER = "configure lint command"
L1_ENV_ALLOWLIST = frozenset({
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "SHELL",
    "LANG",
    "LC_ALL",
    "TERM",
    "TMPDIR",
    "VIRTUAL_ENV",
    "PYTHONDONTWRITEBYTECODE",
    "PYTHONUNBUFFERED",
    "GOPATH",
    "GOCACHE",
    "CARGO_HOME",
    "RUSTUP_HOME",
    "NODE_OPTIONS",
})


def build_l1_offline_env(base_env: dict[str, str], empty_gcloud_dir: pathlib.Path) -> dict[str, str]:
    """Builds a scrubbed Level 1 environment allowlist blocking GCP tokens and metadata probes."""
    env = {
        k: v
        for k, v in base_env.items()
        if k in L1_ENV_ALLOWLIST and not k.startswith(("GOOGLE_", "CLOUDSDK_", "GCP_", "GCLOUD_"))
    }
    env["CLOUDSDK_CONFIG"] = str(empty_gcloud_dir)
    env["GCE_METADATA_HOST"] = "127.0.0.1:1"
    env["GOOGLE_APPLICATION_CREDENTIALS"] = ""
    return env


def _git_head_sha(repo: pathlib.Path) -> str:
    """Resolves HEAD commit SHA when repo is a Git repository, or returns 'uncommitted'."""
    proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo), capture_output=True, text=True, check=False)
    return proc.stdout.strip() if proc.returncode == 0 and proc.stdout.strip() else "uncommitted"


def _load_profile(repo: pathlib.Path, base_ref: str) -> dict[str, Any]:
    """Loads .factory/factory-profile.yaml from base_ref (anti-self-certification) or working tree."""
    if base_ref:
        proc = subprocess.run(
            ["git", "show", f"{base_ref}:.factory/factory-profile.yaml"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise ValueError(f"Could not read .factory/factory-profile.yaml from git ref '{base_ref}': {proc.stderr.strip()}")
        raw = yaml.safe_load(proc.stdout)
    else:
        profile_path = repo / ".factory" / "factory-profile.yaml"
        if not profile_path.is_file():
            raise ValueError(f"Missing {profile_path}")
        raw = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Invalid factory-profile.yaml mapping.")
    return raw


def _run_step(name: str, command: str, cwd: pathlib.Path, env: dict[str, str]) -> dict[str, Any]:
    """Executes one PO-confirmed verification command from factory-profile.yaml."""
    # Commands come strictly from PO-confirmed .factory/factory-profile.yaml (prefer --base-ref in CI).
    proc = subprocess.run(command, shell=True, cwd=str(cwd), env=env, capture_output=True, text=True, check=False)
    return {
        "step": name,
        "command": command,
        "returncode": proc.returncode,
        "ok": proc.returncode == 0,
        "stdout_tail": proc.stdout[-1200:],
        "stderr_tail": proc.stderr[-1200:],
    }


def run_generic_gate(repo_dir: pathlib.Path, level: int = 1, base_ref: str = "") -> dict[str, Any]:
    """Runs Level 1 scrubbed offline checks or Level 2 sandbox E2E checks declared in factory-profile.yaml."""
    repo = repo_dir.resolve()
    commit_sha = _git_head_sha(repo)
    try:
        profile = _load_profile(repo, base_ref)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        return {"ok": False, "level": level, "status": "error", "commit_sha": commit_sha, "error": str(exc), "steps": []}

    commands = profile.get("commands") or {}
    deploy_target = str(profile.get("deploy_target") or "none")
    monorepo = profile.get("monorepo") or {}
    subdir = str(monorepo.get("subdir") or "").strip() if monorepo.get("enabled") else ""
    work_dir = (repo / subdir).resolve() if subdir else repo
    try:
        work_dir.relative_to(repo)
    except ValueError:
        return {"ok": False, "level": level, "status": "error", "commit_sha": commit_sha, "error": f"monorepo.subdir escapes repo root: {subdir}", "steps": []}

    steps: list[dict[str, Any]] = []
    if level == 1:
        lint_cmd = str(commands.get("lint") or "").strip()
        test_cmd = str(commands.get("test") or "").strip()
        build_cmd = str(commands.get("build") or "").strip()
        if not lint_cmd or PLACEHOLDER_MARKER in lint_cmd:
            return {"ok": False, "level": 1, "status": "failed", "commit_sha": commit_sha, "error": "commands.lint is empty or placeholder.", "steps": []}
        if not test_cmd:
            return {"ok": False, "level": 1, "status": "failed", "commit_sha": commit_sha, "error": "commands.test is empty.", "steps": []}
        with tempfile.TemporaryDirectory(prefix="generic-l1-gcloud-") as empty_gcloud:
            env = build_l1_offline_env(dict(os.environ), pathlib.Path(empty_gcloud))
            if build_cmd:
                steps.append(_run_step("build", build_cmd, work_dir, env))
            steps.append(_run_step("lint", lint_cmd, work_dir, env))
            steps.append(_run_step("test", test_cmd, work_dir, env))
        all_ok = all(s["ok"] for s in steps)
        return {
            "ok": all_ok,
            "level": 1,
            "status": "passed" if all_ok else "failed",
            "verdict_status": "offline-verified" if all_ok else "failed",
            "commit_sha": commit_sha,
            "deploy_target": deploy_target,
            "work_dir": str(work_dir),
            "not_verifiable_in_sandbox": list(profile.get("not_verifiable_in_sandbox") or []),
            "steps": steps,
        }

    if deploy_target == "none":
        return {
            "ok": True,
            "level": 2,
            "status": "skipped",
            "verdict_status": "offline-only-deploy-none",
            "reason": "deploy_target is none.",
            "commit_sha": commit_sha,
            "deploy_target": deploy_target,
            "not_verifiable_in_sandbox": list(profile.get("not_verifiable_in_sandbox") or []),
            "steps": [],
        }

    e2e_cmd = str(commands.get("e2e") or "").strip()
    if not e2e_cmd:
        return {
            "ok": False,
            "level": 2,
            "status": "failed",
            "verdict_status": "failed",
            "commit_sha": commit_sha,
            "deploy_target": deploy_target,
            "error": f"deploy_target is '{deploy_target}' but commands.e2e is empty. Configure an E2E check or set deploy_target: none.",
            "steps": [],
        }

    step = _run_step("e2e", e2e_cmd, work_dir, dict(os.environ))
    steps.append(step)
    return {
        "ok": step["ok"],
        "level": 2,
        "status": "passed" if step["ok"] else "failed",
        "verdict_status": "live-sandbox-verified" if step["ok"] else "failed",
        "commit_sha": commit_sha,
        "deploy_target": deploy_target,
        "work_dir": str(work_dir),
        "not_verifiable_in_sandbox": list(profile.get("not_verifiable_in_sandbox") or []),
        "steps": steps,
    }


def main(argv: list[str] | None = None) -> int:
    """Parses CLI arguments and prints structured JSON verification results."""
    parser = argparse.ArgumentParser(description="Run profile-driven Level 1 or Level 2 generic factory checks.")
    parser.add_argument("--repo", type=pathlib.Path, default=pathlib.Path("."))
    parser.add_argument("--level", type=int, choices=(1, 2), default=1)
    parser.add_argument("--base-ref", default="", help="Read commands from git ref (e.g. origin/main) to prevent PR self-certification.")
    parser.add_argument("--out", type=pathlib.Path, default=None)
    args = parser.parse_args(argv)

    result = run_generic_gate(args.repo, level=args.level, base_ref=args.base_ref)
    encoded = json.dumps(result, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
