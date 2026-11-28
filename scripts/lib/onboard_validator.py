"""Unified fail-closed Wave 2 factory validator and human provenance guard (M1, M7, H3).

Extracted from onboard_factory_v2.py to keep both modules cleanly under 250 lines.
Enforces strict repo containment on --config, auto-discovers monorepo `.factory/*/factory.yaml`
siblings, detects cross-factory prefix/coordinator/skill collisions, validates human `confirmed_by`
provenance (blocking LLM/bot tokens), enforces AGENTS.md <= 6 KB without blocking legacy customer
prose, and runs the 4-rule Dockerfile linter.
"""
from __future__ import annotations

import pathlib
import re
from typing import Any

import yaml

from scripts.lib.dockerfile_recipes import validate_customer_dockerfile
from scripts.lib.io_utils import assert_no_symlink_escape, assert_read_path_inside_repo
from scripts.lib.onboard_roles import PACK_PREFIXES
from scripts.lib.onboard_tier_a import scan_tier_a_signals
from scripts.lib.schema_validator import validate_against_schema

AGENTS_MD_MAX_BYTES = 6144
FACTORY_BLOCK_MAX_BYTES = 2048
FORBIDDEN_PROVENANCE_TOKENS = frozenset({
    "llm",
    "ai",
    "agent",
    "auto",
    "bot",
    "tbd",
    "todo",
    "unknown",
    "none",
    "placeholder",
    "gemini",
    "claude",
    "gpt",
    "openai",
    "anthropic",
    "copilot",
    "assistant",
})
TOKEN_SPLIT_RE = re.compile(r"[^a-z0-9]+")
FACTORY_BLOCK_RE = re.compile(
    r"<!-- gcp-fde-factory(?::[a-z0-9-]+)?:start -->.*?<!-- gcp-fde-factory(?::[a-z0-9-]+)?:end -->",
    re.DOTALL,
)


def validate_confirmed_by(profile: dict[str, Any]) -> list[str]:
    """Enforces human provenance in confirmed_by rejecting empty, short, or AI/bot tokens (M1)."""
    raw = str(profile.get("confirmed_by") or "").strip()
    if len(raw) < 3 or raw.lower() == "n/a":
        return ["confirmed_by is required and must identify the human PO or Engineer who approved onboarding."]
    tokens = [t for t in TOKEN_SPLIT_RE.split(raw.lower()) if t]
    if not tokens or any(tok in FORBIDDEN_PROVENANCE_TOKENS for tok in tokens):
        return [
            f"confirmed_by '{raw}' rejected as non-human or placeholder provenance. "
            "Record a real human name or email (for example 'Ana Silva <ana@example.com>')."
        ]
    return []


def check_v2_readiness(profile: dict[str, Any], schema_path: pathlib.Path) -> dict[str, Any]:
    """Validates a Wave 2 factory.yaml mapping against factory.schema.json and semantic rules (M7)."""
    issues = validate_against_schema(profile, schema_path)
    warnings: list[str] = []
    # Return early on structural schema errors so malformed types never trigger AttributeError (M7).
    if issues:
        return {"ready": False, "missing_or_weak": issues, "warnings": warnings}

    issues.extend(validate_confirmed_by(profile))

    cmds = profile.get("commands") or {}
    if "configure lint command" in str(cmds.get("lint", "")):
        issues.append("commands.lint still contains the placeholder value. Confirm the real lint command.")
    if not str(cmds.get("test", "")).strip():
        issues.append("commands.test must not be empty. Confirm the canonical test command.")

    pack = str(profile.get("pack") or "")
    pack_prefix = PACK_PREFIXES.get(pack, pack)
    if pack == "generic":
        dt = str(profile.get("deploy_target") or "")
        if not dt:
            issues.append("Pack 'generic' requires an explicit 'deploy_target' (cloud-run, gke, custom, or none).")
        elif dt in ("agent-engine", "ces"):
            issues.append(f"Pack 'generic' does not support deploy_target '{dt}'. Use cloud-run, gke, custom, or none.")

    mono = profile.get("monorepo") if isinstance(profile.get("monorepo"), dict) else {}
    if mono.get("enabled"):
        prefix = str(mono.get("agent_prefix") or "").strip()
        if not prefix or prefix == pack_prefix:
            issues.append(
                f"monorepo.enabled=true requires a unique monorepo.agent_prefix distinct from pack prefix '{pack_prefix}' (H3)."
            )

    roster = profile.get("roster") or {}
    if int(roster.get("max_wip") or 0) >= 4 and int(roster.get("reviewer_replicas") or 1) < 2:
        warnings.append("roster.max_wip >= 4 with reviewer_replicas < 2 may bottleneck PR reviews. Set reviewer_replicas: 2.")

    if str(profile.get("git_support_tier") or "native_github") == "best_effort":
        intake = profile.get("intake") or {}
        if intake.get("enabled") and str(intake.get("provider") or "github") != "github":
            warnings.append("External Delta Watcher natively polls GitHub; non-GitHub hosts operate in best_effort manual mode.")

    return {"ready": len(issues) == 0, "missing_or_weak": issues, "warnings": warnings}


def discover_factory_configs(repo: pathlib.Path, explicit_config: pathlib.Path | None = None) -> list[pathlib.Path]:
    """Resolves explicit --config strictly inside repo, or discovers root / monorepo sibling factory configs (M7)."""
    if explicit_config is not None:
        raw_target = explicit_config if explicit_config.is_absolute() else (repo / explicit_config)
        safe = assert_read_path_inside_repo(repo, raw_target)
        return [safe]
    if (repo / ".factory" / "factory.yaml").is_file():
        return [assert_read_path_inside_repo(repo, repo / ".factory" / "factory.yaml")]
    siblings = sorted(
        assert_read_path_inside_repo(repo, p)
        for p in (repo / ".factory").glob("*/factory.yaml")
        if p.is_file()
    ) if (repo / ".factory").is_dir() else []
    if siblings:
        return siblings
    if (repo / ".factory" / "factory-profile.yaml").is_file():
        return [assert_read_path_inside_repo(repo, repo / ".factory" / "factory-profile.yaml")]
    return [repo / ".factory" / "factory.yaml"]


def _check_monorepo_sibling_collisions(repo: pathlib.Path) -> list[str]:
    """Scans all .factory/*/factory.yaml files and flags duplicate agent_prefix, coordinator, or overlay dirs (H3)."""
    factory_root = repo / ".factory"
    if not factory_root.is_dir():
        return []
    seen_prefixes: dict[str, str] = {}
    seen_coords: dict[str, str] = {}
    seen_overlays: dict[str, str] = {}
    errors: list[str] = []
    for cfg in sorted(factory_root.glob("*/factory.yaml")):
        try:
            safe = assert_read_path_inside_repo(repo, cfg)
            data = yaml.safe_load(safe.read_text(encoding="utf-8"))
        except (OSError, ValueError, yaml.YAMLError):
            continue
        if not isinstance(data, dict):
            continue
        rel = safe.relative_to(repo).as_posix()
        mono = data.get("monorepo") if isinstance(data.get("monorepo"), dict) else {}
        prefix = str(mono.get("agent_prefix") or "").strip()
        if prefix:
            if prefix in seen_prefixes:
                errors.append(f"Duplicate monorepo.agent_prefix '{prefix}' across {seen_prefixes[prefix]} and {rel}.")
            seen_prefixes[prefix] = rel
        coord = str((data.get("kaizen") or {}).get("coordinator_agent") or "").strip()
        if coord:
            if coord in seen_coords:
                errors.append(f"Duplicate kaizen.coordinator_agent '{coord}' across {seen_coords[coord]} and {rel}.")
            seen_coords[coord] = rel
        for ov in data.get("overlay_skills") or []:
            if isinstance(ov, dict) and ov.get("dir"):
                odir = str(ov["dir"])
                if odir in seen_overlays:
                    errors.append(f"Duplicate overlay_skills dir '{odir}' across {seen_overlays[odir]} and {rel}.")
                seen_overlays[odir] = rel
    return errors


def _validate_single_config(
    repo: pathlib.Path,
    cfg_path: pathlib.Path,
    sdir: pathlib.Path,
    strict_dockerfile: bool,
) -> tuple[str, list[str], list[str]]:
    """Validates one factory config file, its links, REQ traceability, and Dockerfile."""
    errors: list[str] = []
    warnings: list[str] = []
    if not cfg_path.is_file():
        return "2", [f"Missing factory config: {cfg_path}"], warnings

    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return "2", [f"{cfg_path} must contain a YAML mapping."], warnings

    ver = str(raw.get("schema_version") or "1")
    if ver == "2":
        gate = check_v2_readiness(raw, sdir / "factory.schema.json")
    else:
        from scripts.lib.onboard_emitter import check_readiness
        gate = check_readiness(raw, sdir / "factory-profile.schema.json")
    errors.extend(gate["missing_or_weak"])
    warnings.extend(gate["warnings"])
    if errors:
        return ver, errors, warnings

    for src in raw.get("knowledge_sources") or []:
        try:
            target = assert_read_path_inside_repo(repo, repo / str(src))
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if not target.exists():
            errors.append(f"Broken knowledge_sources path: '{src}' does not exist.")

    req_ids = {str(r["id"]) for r in (raw.get("requirements") or []) if isinstance(r, dict) and r.get("id")}
    seen_tids: set[str] = set()
    for task in raw.get("waves") or []:
        if not isinstance(task, dict):
            continue
        tid = str(task.get("id") or "")
        if tid in seen_tids:
            errors.append(f"Duplicate Wave-1 task ID '{tid}'.")
        seen_tids.add(tid)
        for ref in task.get("req_ids") or []:
            if str(ref) not in req_ids:
                errors.append(f"Wave task '{tid}' references unknown requirement ID '{ref}'.")

    tc = raw.get("toolchain") if isinstance(raw.get("toolchain"), dict) else {}
    for df_key, bins in (("dockerfile", list(tc.get("verify_binaries") or [])), ("tester_dockerfile", [])):
        df_rel = tc.get(df_key)
        if not df_rel:
            continue
        try:
            df_path = assert_no_symlink_escape(repo, repo / str(df_rel))
        except ValueError as exc:
            errors.append(str(exc))
            continue
        df_rep = validate_customer_dockerfile(df_path, strict=strict_dockerfile, verify_binaries=bins)
        if not df_rep["ok"]:
            errors.extend(df_rep["structural_errors"])
            errors.extend(f"[{f['code']}] {f['message']}" for f in df_rep["advisory_findings"])

    return ver, errors, warnings


def validate_factory_repo(
    repo_dir: pathlib.Path,
    *,
    config_path: pathlib.Path | None = None,
    schemas_dir: pathlib.Path | None = None,
    strict_dockerfile: bool = True,
) -> dict[str, Any]:
    """Unified fail-closed validator across single-factory and multi-factory monorepo layouts (M7, H3)."""
    repo = repo_dir.resolve()
    sdir = schemas_dir or (pathlib.Path(__file__).resolve().parent.parent.parent / "schemas")
    try:
        configs = discover_factory_configs(repo, config_path)
    except ValueError as exc:
        return {"ok": False, "config_path": str(config_path or ""), "errors": [str(exc)], "warnings": []}

    errors: list[str] = []
    warnings: list[str] = []
    schema_ver = "2"
    for cfg in configs:
        schema_ver, cfg_errs, cfg_warns = _validate_single_config(repo, cfg, sdir, strict_dockerfile)
        errors.extend(cfg_errs)
        warnings.extend(cfg_warns)

    errors.extend(_check_monorepo_sibling_collisions(repo))

    # Validate AGENTS.md size: hard-fail if our emitted block > 2 KB or total > 6 KB without large pre-existing prose (M7).
    agents_path = repo / "AGENTS.md"
    if not agents_path.is_file():
        errors.append("Missing AGENTS.md in repository root.")
    else:
        agents_bytes = agents_path.read_bytes()
        agents_text = agents_bytes.decode("utf-8", errors="ignore")
        blocks = FACTORY_BLOCK_RE.findall(agents_text)
        factory_bytes = sum(len(b.encode("utf-8")) for b in blocks)
        customer_bytes = len(FACTORY_BLOCK_RE.sub("", agents_text).strip().encode("utf-8"))
        if factory_bytes > FACTORY_BLOCK_MAX_BYTES:
            errors.append(f"Emitted factory overlay in AGENTS.md is {factory_bytes} bytes (max {FACTORY_BLOCK_MAX_BYTES}).")
        elif len(agents_bytes) > AGENTS_MD_MAX_BYTES:
            if customer_bytes > AGENTS_MD_MAX_BYTES:
                warnings.append(
                    f"Pre-existing customer AGENTS.md prose is {customer_bytes} bytes (above {AGENTS_MD_MAX_BYTES} B target). Consider trimming."
                )
            else:
                errors.append(
                    f"AGENTS.md is {len(agents_bytes)} bytes (exceeds anti-bloat budget of {AGENTS_MD_MAX_BYTES} bytes)."
                )
        for cfg in configs:
            if cfg.is_file() and schema_ver == "2":
                rel_cfg = cfg.relative_to(repo).as_posix()
                if rel_cfg not in agents_text:
                    warnings.append(f"AGENTS.md does not reference '{rel_cfg}'.")

    for col in scan_tier_a_signals(repo)["skill_collisions"]:
        errors.append(f"Skill name collision: {col}.")

    return {
        "ok": len(errors) == 0,
        "schema_version": schema_ver,
        "config_path": str(configs[0]) if len(configs) == 1 else [str(c) for c in configs],
        "errors": errors,
        "warnings": warnings,
    }
