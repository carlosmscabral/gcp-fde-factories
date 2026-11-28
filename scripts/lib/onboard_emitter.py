"""Deterministic Readiness Gate, atomic AGENTS.md merge, and Layer 3 overlay emitter (v0.6.0).

Pre-validates every target path against symlink escapes before writing any file on disk,
writes each artifact atomically via os.replace, and preserves agent-authored Dockerfiles
and Knowledge Plane files across re-emissions.
"""
from __future__ import annotations

import hashlib
import pathlib
import re
from typing import Any

import yaml

from scripts.lib.dockerfile_recipes import render_conditional_dockerfile
from scripts.lib.io_utils import assert_no_symlink_escape, atomic_write_bytes
from scripts.lib.onboard_factory_v2 import (
    build_unified_factory_yaml,
    check_v2_readiness,
    plan_optional_v2_knowledge_files,
    render_surgical_agents_block,
    resolve_conventions_skill_dir,
    resolve_factory_dir_rel,
)
from scripts.lib.onboard_git_ops import compute_unified_diffs
from scripts.lib.onboard_hub_config import build_hub_project_overlay, merge_modernization_backlog
from scripts.lib.onboard_kp import plan_knowledge_plane
from scripts.lib.onboard_security import compute_hazard_digests, detect_hooks_and_ai_divergence
from scripts.lib.schema_validator import validate_against_schema

START_MARKER = "<!-- gcp-fde-factory:start -->"
END_MARKER = "<!-- gcp-fde-factory:end -->"
START_LINE_RE = re.compile(r"^[ \t]*<!-- gcp-fde-factory:start -->[ \t]*$", re.MULTILINE)
END_LINE_RE = re.compile(r"^[ \t]*<!-- gcp-fde-factory:end -->[ \t]*$", re.MULTILINE)
GENERATED_DOCKERFILE_HEADER = "# Conditional Layer 3 derived customer image"


def check_readiness(profile: dict[str, Any], schema_path: pathlib.Path) -> dict[str, Any]:
    """Evaluates whether an onboarding profile passes the deterministic Readiness Gate."""
    issues = validate_against_schema(profile, schema_path)
    warnings: list[str] = []

    if not issues:
        cmds = profile.get("commands", {})
        if "configure lint command" in str(cmds.get("lint", "")):
            issues.append("commands.lint still contains the placeholder value. Confirm the real lint command.")
        if not str(cmds.get("test", "")).strip():
            issues.append("commands.test must not be empty. Confirm the canonical test command.")

        if profile.get("pack") == "generic":
            dt = str(profile.get("deploy_target") or "")
            if not dt:
                issues.append("Pack 'generic' requires an explicit 'deploy_target' (cloud-run, gke, custom, or none).")
            elif dt in ("agent-engine", "ces"):
                issues.append(f"Pack 'generic' does not support deploy_target '{dt}'. Use cloud-run, gke, custom, or none.")

        roster = profile.get("roster") or {}
        if int(roster.get("max_wip") or 0) >= 4 and int(roster.get("reviewer_replicas") or 1) < 2:
            warnings.append("roster.max_wip >= 4 with reviewer_replicas < 2 may bottleneck PR reviews. Set reviewer_replicas: 2.")

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
            needs_l2 = profile.get("deploy_target") != "none"
            if not pyr.get("l1_offline") or (needs_l2 and not pyr.get("l2_sandbox")):
                issues.append(
                    "Complete track requires 'evaluation_pyramid' with 'l1_offline' (and 'l2_sandbox' when deploy_target != none)."
                )
            if profile.get("pack") == "generic" and needs_l2 and not str(cmds.get("e2e") or "").strip():
                issues.append("Pack 'generic' on complete track with deploy_target != none requires a non-empty commands.e2e.")

    return {"ready": len(issues) == 0, "missing_or_weak": issues, "warnings": warnings}


def _find_unquoted_marker_spans(text: str, marker: str) -> list[tuple[int, int]]:
    """Finds line-anchored marker byte spans while ignoring lines inside triple-backtick code fences (L3)."""
    spans: list[tuple[int, int]] = []
    in_fence = False
    offset = 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
        elif not in_fence and stripped == marker:
            spans.append((offset, offset + len(line.rstrip("\r\n"))))
        offset += len(line)
    return spans


def compute_merged_agents_md(existing: str | None, block_body: str, scope_id: str = "") -> str:
    """Computes an idempotent, CRLF-preserving delimited merge without corrupting customer prose or code fences.

    Uses scoped markers (`<!-- gcp-fde-factory:<scope_id>:start -->`) when scope_id is provided so
    multiple sibling factories inside one monorepo coexist cleanly in root AGENTS.md.
    """
    start_m = f"<!-- gcp-fde-factory:{scope_id}:start -->" if scope_id else START_MARKER
    end_m = f"<!-- gcp-fde-factory:{scope_id}:end -->" if scope_id else END_MARKER

    eol = "\r\n" if (existing and "\r\n" in existing) else "\n"
    normalized_body = eol.join(block_body.strip().splitlines())
    wrapped = f"{start_m}{eol}{normalized_body}{eol}{end_m}{eol}"

    if existing is None or not existing.strip():
        return wrapped

    starts = _find_unquoted_marker_spans(existing, start_m)
    ends = _find_unquoted_marker_spans(existing, end_m)
    if len(starts) != len(ends) or len(starts) > 1:
        raise ValueError(
            "AGENTS.md has malformed factory markers (orphan or duplicate markers). Repair markers manually before emit."
        )
    if len(starts) == 1:
        if ends[0][0] < starts[0][1]:
            raise ValueError("AGENTS.md has END marker before START marker. Repair markers manually before emit.")
        before = existing[: starts[0][0]].rstrip("\r\n")
        after = existing[ends[0][1] :].lstrip("\r\n")
        prefix = (before + eol + eol) if before else ""
        suffix = (eol + after) if after else ""
        return prefix + wrapped + suffix

    return existing.rstrip("\r\n") + eol + eol + wrapped


def _render_conventions_skill(profile: dict[str, Any]) -> str:
    """Renders skills/<slug>-repo-conventions/SKILL.md within the 300-line skill budget."""
    slug = profile["slug"]
    gf = profile["git_flow"]
    cmds = profile["commands"]
    ai_list = ", ".join(profile.get("ai_files_detected") or []) or "none"
    absorbed = profile.get("absorbed_conventions") or []
    absorbed_lines = (
        "".join(f"- {rule}\n" for rule in absorbed)
        if absorbed
        else "- Reconcile pre-existing repository AI files against SEP guardrails before execution. If a repo rule conflicts with PR-only workflow or Verification Gates, SEP guardrails win.\n"
    )
    return (
        f"---\nname: {slug}-repo-conventions\n"
        f"description: Repository commands, Git Flow rules, and absorbed conventions for {slug}.\n---\n\n"
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


def _ensure_scion_gitignore_bytes(existing: bytes | None) -> bytes | None:
    """Appends .scion/agents/ to .gitignore idempotently while preserving CRLF/LF endings (HC-05 F5)."""
    if existing is None:
        return b"# Scion project-local agent runtime metadata\n.scion/agents/\n"
    text = existing.decode("utf-8", errors="replace")
    if any(ln.strip() in (".scion/agents/", ".scion/agents") for ln in text.splitlines()):
        return None
    eol = "\r\n" if "\r\n" in text else "\n"
    suffix = "" if (not text or text.endswith(("\n", "\r"))) else eol
    return (text + suffix + f"# Scion project-local agent runtime metadata{eol}.scion/agents/{eol}").encode("utf-8")


def emit_layer3_overlay(
    repo_dir: pathlib.Path,
    profile: dict[str, Any],
    pack_image_ref: str,
    profile_schema_path: pathlib.Path,
    *,
    force_knowledge: bool = False,
    dry_run: bool = False,
    acknowledge_hazards: bool = False,
) -> dict[str, Any]:
    """Pre-validates security hazards, paths, and symlinks, then emits or previews Layer 3 files.

    When profile.schema_version == '2' (Wave 2 unified format), emits a single consolidated
    .factory/[<prefix>/]factory.yaml, surgical <6 KB AGENTS.md block, and zero empty Day-0
    Knowledge Plane placeholders. Legacy schema_version == '1' profiles retain v0.6.0 emission.
    """
    repo = repo_dir.resolve()
    if not repo.is_dir():
        raise ValueError(f"Target repository directory does not exist: {repo}")

    is_v2 = str(profile.get("schema_version") or "1") == "2"
    effective_schema = (profile_schema_path.parent / "factory.schema.json") if is_v2 else profile_schema_path
    gate = check_v2_readiness(profile, effective_schema) if is_v2 else check_readiness(profile, effective_schema)
    if not gate["ready"]:
        raise ValueError("Readiness Gate failed: " + " | ".join(gate["missing_or_weak"]))

    detected_hazards, _, _ = detect_hooks_and_ai_divergence(repo)
    hazard_digests = compute_hazard_digests(repo, detected_hazards)
    acknowledged = set(str(h) for h in (profile.get("acknowledged_workspace_hazards") or []))
    unacknowledged_hazards = [
        h
        for h in detected_hazards
        if hazard_digests[h] not in acknowledged and h not in acknowledged
    ]
    if unacknowledged_hazards and not acknowledge_hazards and not dry_run:
        expected_tokens = [hazard_digests[h] for h in unacknowledged_hazards]
        raise ValueError(
            "Blocking untrusted workspace hazards detected: "
            + ", ".join(expected_tokens)
            + ". Review them and pass --acknowledge-workspace-hazards or list exact path@sha256 digests in profile.acknowledged_workspace_hazards."
        )

    slug = profile["slug"]
    factory_dir_rel = resolve_factory_dir_rel(profile) if is_v2 else ".factory"
    # In v2, only auto-generate recipe Dockerfiles for allowlisted binaries when no custom toolchain.dockerfile exists.
    custom_df_declared = bool(is_v2 and (profile.get("toolchain") or {}).get("dockerfile"))
    recipe_missing = [b for b in (profile.get("missing_binaries") or []) if not custom_df_declared]
    recipe_heavy = [b for b in (profile.get("heavy_test_binaries") or []) if not custom_df_declared]
    core_df_text = render_conditional_dockerfile(pack_image_ref, recipe_missing, tester_only=False) if recipe_missing else None
    core_df_rel = f"{factory_dir_rel}/Dockerfile.customer" if core_df_text else None
    tester_base = f"{slug}-customer:local" if core_df_text else pack_image_ref
    tester_df_text = (
        render_conditional_dockerfile(tester_base, recipe_heavy, tester_only=True, allow_local_stage_ref=bool(core_df_text))
        if recipe_heavy
        else None
    )
    tester_df_rel = f"{factory_dir_rel}/Dockerfile.customer-tester" if tester_df_text else None

    skill_text = _render_conventions_skill(profile)
    skill_ver = _content_semver(skill_text)
    conv_dir_rel = resolve_conventions_skill_dir(profile) if is_v2 else f"skills/{slug}-repo-conventions"

    # Phase 1: Validate all paths/symlinks and compute every payload BEFORE writing any file on disk.
    writes: list[tuple[pathlib.Path, bytes, str]] = []
    unlinks: list[pathlib.Path] = []
    preserved_custom_dockerfiles: list[str] = []

    if is_v2:
        unified_cfg, coordinator_name = build_unified_factory_yaml(
            repo,
            profile,
            factory_dir_rel=factory_dir_rel,
            conv_dir_rel=conv_dir_rel,
            skill_ver=skill_ver,
            core_df_rel=core_df_rel,
            tester_df_rel=tester_df_rel,
            factory_schema_path=effective_schema,
        )
        kp_plan = plan_optional_v2_knowledge_files(
            repo,
            unified_cfg,
            factory_dir_rel,
            coordinator_name,
            force_knowledge=force_knowledge,
        )
        cfg_rel = f"{factory_dir_rel}/factory.yaml"
        writes.append((assert_no_symlink_escape(repo, repo / cfg_rel), yaml.safe_dump(unified_cfg, sort_keys=False).encode("utf-8"), cfg_rel))
        block = render_surgical_agents_block(unified_cfg, factory_dir_rel, conv_dir_rel)
    else:
        hub_project, coordinator_name = build_hub_project_overlay(
            repo,
            profile,
            conv_dir_rel=conv_dir_rel,
            skill_ver=skill_ver,
            core_df_rel=core_df_rel,
            tester_df_rel=tester_df_rel,
            hub_schema_path=profile_schema_path.parent / "hub-project.schema.json",
        )
        merged_gaps = merge_modernization_backlog(repo, profile)
        kp_plan = plan_knowledge_plane(repo, profile, coordinator_name, force_knowledge=force_knowledge)
        yaml_files = (
            (".factory/hub-project.yaml", hub_project),
            (".factory/factory-profile.yaml", profile),
            (
                ".factory/knowledge-index.yaml",
                {
                    "schema_version": "1",
                    "sources": profile.get("knowledge_sources", []),
                    "knowledge_files": kp_plan["knowledge_files"],
                    "requirements": profile.get("requirements", []),
                    "invariants": profile.get("invariants", []),
                },
            ),
            (".factory/modernization-backlog.yaml", {"schema_version": "1", "gaps": merged_gaps}),
        )
        for rel, payload in yaml_files:
            path = assert_no_symlink_escape(repo, repo / rel)
            writes.append((path, yaml.safe_dump(payload, sort_keys=False).encode("utf-8"), rel))
        block = (
            f"## Google Cloud FDE Factory Overlay (`{profile['pack']}@{profile['pack_version']}`)\n"
            f"- Factory overlay config: `.factory/hub-project.yaml` and `.factory/factory-profile.yaml`\n"
            f"- In-place knowledge index: `.factory/knowledge-index.yaml`\n"
            f"- Initial Wave-1 backlog: `.factory/waves/wave-1.yaml`\n"
            f"- Coordinator standby brief: `.factory/coordinator-bootstrap-brief.md`\n"
            f"- Repository conventions skill: `{conv_dir_rel}/SKILL.md`\n"
            f"- Modernization backlog: `.factory/modernization-backlog.yaml`"
        )

    agents_scope = (
        str((profile.get("monorepo") or {}).get("agent_prefix") or "").strip()
        if is_v2 and isinstance(profile.get("monorepo"), dict) and profile["monorepo"].get("enabled")
        else ""
    )
    agents_path = assert_no_symlink_escape(repo, repo / "AGENTS.md")
    existing_agents_raw = agents_path.read_bytes() if agents_path.exists() else None
    existing_agents_str = existing_agents_raw.decode("utf-8") if existing_agents_raw is not None else None
    merged_agents_bytes = compute_merged_agents_md(existing_agents_str, block, scope_id=agents_scope).encode("utf-8")
    mirror_siblings = (
        existing_agents_raw is not None
        and (repo / "CLAUDE.md").is_file()
        and (repo / "GEMINI.md").is_file()
        and not (repo / "CLAUDE.md").is_symlink()
        and not (repo / "GEMINI.md").is_symlink()
        and (repo / "CLAUDE.md").read_bytes() == existing_agents_raw
        and (repo / "GEMINI.md").read_bytes() == existing_agents_raw
    )

    gitignore_path = assert_no_symlink_escape(repo, repo / ".gitignore")
    updated_gi_bytes = _ensure_scion_gitignore_bytes(gitignore_path.read_bytes() if gitignore_path.exists() else None)

    for rel_df, content in ((f"{factory_dir_rel}/Dockerfile.customer", core_df_text), (f"{factory_dir_rel}/Dockerfile.customer-tester", tester_df_text)):
        df_path = assert_no_symlink_escape(repo, repo / rel_df)
        is_generated = df_path.is_file() and df_path.read_text(encoding="utf-8", errors="ignore").startswith(GENERATED_DOCKERFILE_HEADER)
        if content:
            if df_path.is_file() and not is_generated:
                preserved_custom_dockerfiles.append(rel_df)
            else:
                writes.append((df_path, content.encode("utf-8"), rel_df))
        elif is_generated and not custom_df_declared:
            unlinks.append(df_path)

    skill_path = assert_no_symlink_escape(repo, repo / conv_dir_rel / "SKILL.md")
    writes.append((skill_path, skill_text.encode("utf-8"), f"{conv_dir_rel}/SKILL.md"))
    writes.extend(kp_plan["writes"])

    writes.append((agents_path, merged_agents_bytes, "AGENTS.md"))
    if updated_gi_bytes is not None:
        writes.append((gitignore_path, updated_gi_bytes, ".gitignore"))
    skipped_bridges: list[str] = []
    if mirror_siblings:
        for sib in ("CLAUDE.md", "GEMINI.md"):
            writes.append((assert_no_symlink_escape(repo, repo / sib), merged_agents_bytes, sib))
    else:
        # Bridge standalone pre-existing CLAUDE.md strictly as raw UTF-8 bytes preserving CRLF/LF (BG-H6, H5).
        claude_path = repo / "CLAUDE.md"
        if claude_path.is_file() and not claude_path.is_symlink():
            claude_raw_bytes = claude_path.read_bytes()
            if existing_agents_raw is not None and claude_raw_bytes == existing_agents_raw:
                writes.append((assert_no_symlink_escape(repo, claude_path), merged_agents_bytes, "CLAUDE.md"))
            else:
                try:
                    claude_raw = claude_raw_bytes.decode("utf-8", errors="strict")
                except UnicodeDecodeError:
                    skipped_bridges.append("CLAUDE.md (non-UTF-8 encoding preserved untouched)")
                else:
                    if "@AGENTS.md" not in claude_raw:
                        bridged_claude = compute_merged_agents_md(claude_raw, "@AGENTS.md").encode("utf-8")
                        writes.append((assert_no_symlink_escape(repo, claude_path), bridged_claude, "CLAUDE.md"))

    config_rel = f"{factory_dir_rel}/factory.yaml" if is_v2 else ".factory/hub-project.yaml"
    if dry_run:
        diffs = compute_unified_diffs(repo, writes, unlinks)
        return {
            "dry_run": True,
            "config_path": config_rel,
            "would_emit_files": [rel for _, _, rel in writes],
            "would_unlink_files": [p.relative_to(repo).as_posix() for p in unlinks],
            "blocking_hazards": unacknowledged_hazards,
            "hazard_digests": hazard_digests,
            "skipped_bridges": skipped_bridges,
            "preserved_knowledge_files": kp_plan["preserved"],
            "preserved_custom_dockerfiles": preserved_custom_dockerfiles,
            "coordinator_agent": coordinator_name,
            "diffs": diffs,
        }

    # Phase 2: All checks passed. Commit atomically via temp-file rename.
    created: list[str] = []
    for path in unlinks:
        path.unlink()
    for path, data, rel in writes:
        atomic_write_bytes(path, data)
        created.append(rel)

    return {
        "config_path": config_rel,
        "emitted_files": created,
        "preserved_knowledge_files": kp_plan["preserved"],
        "preserved_custom_dockerfiles": preserved_custom_dockerfiles,
        "acknowledged_hazards": detected_hazards,
        "hazard_digests": hazard_digests,
        "skipped_bridges": skipped_bridges,
        "coordinator_agent": coordinator_name,
        "custom_dockerfile": core_df_rel,
        "tester_dockerfile": tester_df_rel,
        "conventions_skill_version": skill_ver,
    }
