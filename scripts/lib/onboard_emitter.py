"""Deterministic Readiness Gate, atomic AGENTS.md merge, and Layer 3 overlay emitter (v0.4.0).

Delegates Dockerfile recipe rendering to scripts/lib/dockerfile_recipes.py.
Enforces Adopt-First invariants: atomic writes, non-destructive hub-project/backlog merge,
CRLF preservation, symlink refusal, and AGENTS/CLAUDE/GEMINI scaffold parity preservation.
"""
from __future__ import annotations

import hashlib
import pathlib
import re
from typing import Any

import yaml

from scripts.lib.dockerfile_recipes import render_conditional_dockerfile
from scripts.lib.model_routing import build_default_harnesses_and_routing
from scripts.lib.schema_validator import validate_against_schema

START_MARKER = "<!-- gcp-fde-factory:start -->"
END_MARKER = "<!-- gcp-fde-factory:end -->"
START_LINE_RE = re.compile(r"^[ \t]*<!-- gcp-fde-factory:start -->[ \t]*$", re.MULTILINE)
END_LINE_RE = re.compile(r"^[ \t]*<!-- gcp-fde-factory:end -->[ \t]*$", re.MULTILINE)


def check_readiness(profile: dict[str, Any], schema_path: pathlib.Path) -> dict[str, Any]:
    """Evaluates whether an onboarding profile passes the deterministic Readiness Gate."""
    issues = validate_against_schema(profile, schema_path)

    if not issues:
        cmds = profile.get("commands", {})
        if "configure lint command" in str(cmds.get("lint", "")):
            issues.append("commands.lint still contains the placeholder value. Confirm the real lint command.")

        if profile.get("track") == "complete":
            if len(str(profile.get("mission", "")).strip()) < 10:
                issues.append("Complete track requires a non-empty 'mission' (>= 10 chars) confirmed by the PO.")
            if not profile.get("non_goals"):
                issues.append("Complete track requires at least one entry in 'non_goals'.")
            if not profile.get("requirements"):
                issues.append("Complete track requires at least one REQ-NNN entry in 'requirements'.")
            if not profile.get("invariants"):
                issues.append("Complete track requires at least one verifiable entry in 'invariants'.")
            pyr = profile.get("evaluation_pyramid") or {}
            if not (pyr.get("l1_offline") and pyr.get("l2_sandbox")):
                issues.append("Complete track requires 'evaluation_pyramid' with 'l1_offline' and 'l2_sandbox'.")

    return {"ready": len(issues) == 0, "missing_or_weak": issues}


def compute_merged_agents_md(existing: str | None, block_body: str) -> str:
    """Computes an idempotent, CRLF-preserving delimited merge without corrupting customer prose."""
    eol = "\r\n" if (existing and "\r\n" in existing) else "\n"
    normalized_body = eol.join(block_body.strip().splitlines())
    wrapped = f"{START_MARKER}{eol}{normalized_body}{eol}{END_MARKER}{eol}"

    if existing is None or not existing.strip():
        return wrapped

    starts = list(START_LINE_RE.finditer(existing))
    ends = list(END_LINE_RE.finditer(existing))
    if len(starts) != len(ends) or len(starts) > 1:
        raise ValueError(
            "AGENTS.md has malformed factory markers (orphan or duplicate markers). Repair markers manually before emit."
        )
    if len(starts) == 1:
        if ends[0].start() < starts[0].end():
            raise ValueError("AGENTS.md has END marker before START marker. Repair markers manually before emit.")
        before = existing[: starts[0].start()].rstrip("\r\n")
        after = existing[ends[0].end() :].lstrip("\r\n")
        prefix = (before + eol + eol) if before else ""
        suffix = (eol + after) if after else ""
        return prefix + wrapped + suffix

    return existing.rstrip("\r\n") + eol + eol + wrapped


def merge_delimited_agents_md(agents_md_path: pathlib.Path, block_body: str) -> str:
    """Inserts or updates the factory block in AGENTS.md safely, refusing symlinks."""
    if agents_md_path.is_symlink():
        raise ValueError(f"Refusing to write through symlink: {agents_md_path}")
    existing: str | None = None
    if agents_md_path.exists():
        raw = agents_md_path.read_bytes()
        try:
            existing = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"AGENTS.md must be UTF-8 encoded: {exc}") from exc
    merged = compute_merged_agents_md(existing, block_body)
    agents_md_path.write_bytes(merged.encode("utf-8"))
    return merged


def _render_conventions_skill(profile: dict[str, Any]) -> str:
    """Renders skills/<slug>-repo-conventions/SKILL.md within the 300-line skill budget."""
    slug = profile["slug"]
    gf = profile["git_flow"]
    cmds = profile["commands"]
    ai_list = ", ".join(profile.get("ai_files_detected") or []) or "none"
    absorbed = profile.get("absorbed_conventions") or []
    absorbed_lines = "".join(f"- {rule}\n" for rule in absorbed) if absorbed else "- Follow pre-existing repository AI instructions.\n"
    return (
        f"---\n"
        f"name: {slug}-repo-conventions\n"
        f"description: Repository commands, Git Flow rules, and absorbed conventions for {slug}.\n"
        f"---\n\n"
        f"# Repository Conventions (`{slug}`)\n\n"
        f"## 1. Canonical Repository Commands\n"
        f"- Lint command: `{cmds['lint']}`\n"
        f"- Test command: `{cmds['test']}`\n"
        f"- Build command: `{cmds.get('build') or 'not configured'}`\n"
        f"- E2E command: `{cmds.get('e2e') or 'see pack verification gate'}`\n"
        f"- source: https://github.com/GoogleCloudPlatform/scion\n\n"
        f"## 2. Git Flow and Absorbed Rules\n"
        f"- Base branch: `{gf['base_branch']}`\n"
        f"- Branch naming pattern: `{gf['branch_pattern']}`\n"
        f"- Commit convention: `{gf['commit_convention']}`\n"
        f"- CI platform: `{gf['ci_platform']}` (PR template: `{gf.get('pr_template') or 'none'}`)\n"
        f"- Pre-existing AI coding files preserved in place: `{ai_list}`\n"
        f"{absorbed_lines}"
        f"- source: https://github.com/scion-frontiers/agent-team\n"
    )


def _content_semver(skill_text: str) -> str:
    """Derives a deterministic SemVer patch version from skill content for immutable Scion publishes."""
    patch = int(hashlib.sha256(skill_text.encode("utf-8")).hexdigest()[:6], 16) % 9000 + 1
    return f"1.0.{patch}"


def emit_layer3_overlay(
    repo_dir: pathlib.Path,
    profile: dict[str, Any],
    pack_image_ref: str,
    profile_schema_path: pathlib.Path,
) -> dict[str, Any]:
    """Computes and atomically emits the Layer 3 .factory/ overlay after Readiness Gate validation."""
    repo = repo_dir.resolve()
    if not repo.is_dir():
        raise ValueError(f"Target repository directory does not exist: {repo}")

    gate = check_readiness(profile, profile_schema_path)
    if not gate["ready"]:
        raise ValueError("Readiness Gate failed: " + " | ".join(gate["missing_or_weak"]))

    slug = profile["slug"]
    core_df_text = render_conditional_dockerfile(pack_image_ref, profile.get("missing_binaries") or [], tester_only=False)
    core_df_rel = ".factory/Dockerfile.customer" if core_df_text else None
    tester_base = f"{slug}-customer:local" if core_df_text else pack_image_ref
    tester_df_text = render_conditional_dockerfile(
        tester_base,
        profile.get("heavy_test_binaries") or [],
        tester_only=True,
        allow_local_stage_ref=bool(core_df_text),
    )
    tester_df_rel = ".factory/Dockerfile.customer-tester" if tester_df_text else None

    skill_text = _render_conventions_skill(profile)
    skill_ver = _content_semver(skill_text)
    conv_dir_rel = f"skills/{slug}-repo-conventions"

    # Non-destructively merge existing hub-project.yaml (preserve exclude_skills, custom overlays, limits).
    hub_proj_path = repo / ".factory" / "hub-project.yaml"
    existing_hub = yaml.safe_load(hub_proj_path.read_text(encoding="utf-8")) if hub_proj_path.is_file() else {}
    existing_hub = existing_hub if isinstance(existing_hub, dict) else {}
    preserved_overlays = [
        ov for ov in (existing_hub.get("overlay_skills") or [])
        if isinstance(ov, dict) and ov.get("dir") != conv_dir_rel
    ]
    preserved_overlays.append({"dir": conv_dir_rel, "version": skill_ver})

    default_limits = {
        "default_max_duration": "2h",
        "default_max_turns": 60,
        "default_max_model_calls": 150,
        "auto_suspend_idle": True,
    }
    merged_limits = {**default_limits, **(existing_hub.get("limits") or {}), **(profile.get("limits") or {})}
    harnesses_cfg, model_routing_cfg = build_default_harnesses_and_routing(
        diversity_profile=str(profile["diversity_profile"]),
        raw_harnesses={**(existing_hub.get("harnesses") or {}), **(profile.get("harnesses") or {})} or None,
        raw_routing={**(existing_hub.get("model_routing") or {}), **(profile.get("model_routing") or {})} or None,
    )
    hub_project = {
        "schema_version": "1",
        "pack": profile["pack"],
        "pack_version": profile["pack_version"],
        "mode": existing_hub.get("mode") or profile["mode"],
        "diversity_profile": profile["diversity_profile"],
        "limits": merged_limits,
        "harnesses": harnesses_cfg,
        "model_routing": model_routing_cfg,
        "exclude_skills": list(existing_hub.get("exclude_skills") or []),
        "overlay_skills": preserved_overlays,
        "kaizen": {
            "enabled": bool(profile.get("kaizen_enabled", True)),
            "schedule_cron": profile.get("kaizen_schedule_cron", "0 17 * * 5"),
            "time_zone": profile.get("kaizen_time_zone", "America/Sao_Paulo"),
            "coordinator_agent": str((existing_hub.get("kaizen") or {}).get("coordinator_agent") or "coordinator"),
            "enable_gcp_obs": bool((existing_hub.get("kaizen") or {}).get("enable_gcp_obs", False)),
        },
        "brownfield": {
            "track": profile["track"],
            "existing_hub": bool(profile["existing_hub"]),
            "custom_image_dockerfile": core_df_rel,
            "tester_image_dockerfile": tester_df_rel,
            "profile_path": ".factory/factory-profile.yaml",
        },
    }

    # Merge modernization backlog by gap ID so PO statuses survive re-emission.
    backlog_path = repo / ".factory" / "modernization-backlog.yaml"
    existing_gaps: dict[str, dict[str, Any]] = {}
    if backlog_path.is_file():
        prev_bl = yaml.safe_load(backlog_path.read_text(encoding="utf-8"))
        if isinstance(prev_bl, dict):
            for g in prev_bl.get("gaps") or []:
                if isinstance(g, dict) and g.get("id"):
                    existing_gaps[str(g["id"])] = g
    for g in profile.get("modernization_gaps") or []:
        gid = str(g["id"])
        if gid in existing_gaps:
            existing_gaps[gid] = {**g, "status": existing_gaps[gid].get("status", "open")}
        else:
            existing_gaps[gid] = dict(g)

    # Pre-compute AGENTS.md merge before writing ANY file on disk (atomic failure behavior).
    agents_path = repo / "AGENTS.md"
    if agents_path.is_symlink():
        raise ValueError(f"Refusing to write through symlink: {agents_path}")
    existing_agents_raw = agents_path.read_bytes() if agents_path.exists() else None
    existing_agents_str = existing_agents_raw.decode("utf-8") if existing_agents_raw is not None else None
    block = (
        f"## Google Cloud FDE Factory Overlay (`{profile['pack']}@{profile['pack_version']}`)\n"
        f"- Factory overlay config: `.factory/hub-project.yaml` and `.factory/factory-profile.yaml`\n"
        f"- In-place knowledge index: `.factory/knowledge-index.yaml`\n"
        f"- Repository conventions skill: `{conv_dir_rel}/SKILL.md`\n"
        f"- Modernization backlog: `.factory/modernization-backlog.yaml`"
    )
    merged_agents_bytes = compute_merged_agents_md(existing_agents_str, block).encode("utf-8")

    # Detect whether AGENTS/CLAUDE/GEMINI were byte-identical before emit (preserve CI parity).
    mirror_siblings = (
        existing_agents_raw is not None
        and (repo / "CLAUDE.md").is_file()
        and (repo / "GEMINI.md").is_file()
        and not (repo / "CLAUDE.md").is_symlink()
        and not (repo / "GEMINI.md").is_symlink()
        and (repo / "CLAUDE.md").read_bytes() == existing_agents_raw
        and (repo / "GEMINI.md").read_bytes() == existing_agents_raw
    )

    # All validations and merges succeeded; commit outputs cleanly and remove stale generated Dockerfiles.
    factory_dir = repo / ".factory"
    factory_dir.mkdir(parents=True, exist_ok=True)
    created: list[str] = []

    for rel_df, content in ((".factory/Dockerfile.customer", core_df_text), (".factory/Dockerfile.customer-tester", tester_df_text)):
        df_path = repo / rel_df
        if content:
            df_path.write_text(content, encoding="utf-8")
            created.append(rel_df)
        elif df_path.is_file():
            df_path.unlink()

    skill_dir = repo / conv_dir_rel
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(skill_text, encoding="utf-8")
    created.append(f"{conv_dir_rel}/SKILL.md")

    hub_proj_path.write_text(yaml.safe_dump(hub_project, sort_keys=False), encoding="utf-8")
    (factory_dir / "factory-profile.yaml").write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
    (factory_dir / "knowledge-index.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "1",
                "sources": profile.get("knowledge_sources", []),
                "requirements": profile.get("requirements", []),
                "invariants": profile.get("invariants", []),
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    backlog_path.write_text(
        yaml.safe_dump({"schema_version": "1", "gaps": list(existing_gaps.values())}, sort_keys=False),
        encoding="utf-8",
    )
    created.extend([
        ".factory/hub-project.yaml",
        ".factory/factory-profile.yaml",
        ".factory/knowledge-index.yaml",
        ".factory/modernization-backlog.yaml",
    ])

    agents_path.write_bytes(merged_agents_bytes)
    created.append("AGENTS.md")
    if mirror_siblings:
        (repo / "CLAUDE.md").write_bytes(merged_agents_bytes)
        (repo / "GEMINI.md").write_bytes(merged_agents_bytes)
        created.extend(["CLAUDE.md", "GEMINI.md"])

    return {
        "emitted_files": created,
        "custom_dockerfile": core_df_rel,
        "tester_dockerfile": tester_df_rel,
        "conventions_skill_version": skill_ver,
    }
