"""Zero-token static repository scanner, role proposer, and Day-2 drift detector (Wave 2).

Combines universal <2s Tier-A structural discovery (onboard_tier_a) with manifest parsers
(onboard_parsers) and extended stack detectors (onboard_stack_detectors) to produce facts,
pack recommendations, lean/full role proposals, and the 2-block /grill-me interview bank
without importing jsonschema during scan.
"""
from __future__ import annotations

import pathlib
from typing import Any

from scripts.lib.dockerfile_recipes import INSTALL_RECIPES
from scripts.lib.io_utils import load_json, load_yaml
from scripts.lib.onboard_parsers import (
    detect_binaries_and_commands,
    detect_git_and_ci,
    detect_hooks_and_ai_divergence,
    detect_knowledge_sources,
    detect_modernization_gaps,
)
from scripts.lib.onboard_questions import select_grill_questions
from scripts.lib.onboard_roles import propose_roles, recommend_pack
from scripts.lib.onboard_stack_detectors import detect_extended_signals
from scripts.lib.onboard_tier_a import scan_tier_a_signals

HEAVY_TEST_BINARIES = {"playwright", "playwright-node"}
SUPPORTED_RECIPE_BINARIES = frozenset(INSTALL_RECIPES.keys())
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent


def _resolve_pack_manifest(explicit: pathlib.Path | None, pack_name: str) -> pathlib.Path | None:
    """Auto-resolves packs/<pack>/toolchain-manifest.json when scan runs without --pack (HC-09 F2)."""
    if explicit is not None:
        return explicit
    for cand in (
        REPO_ROOT / "packs" / pack_name / "toolchain-manifest.json",
        pathlib.Path(f"/opt/gcp-fde/{pack_name}-toolchain-manifest.json"),
    ):
        if cand.is_file():
            return cand
    return None


def _truncate_note(text: str, limit: int = 200) -> str:
    """Bounds a drift note to schema maxLength without splitting surrogate bytes."""
    clean = " ".join(text.split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."


def scan_repository_facts(
    repo_dir: pathlib.Path,
    toolchain_manifest_path: pathlib.Path | None = None,
    pack: str | None = None,
    track: str = "complete",
    roster_preset: str = "lean",
) -> dict[str, Any]:
    """Scans repo_dir statically (<2s, zero jsonschema) and computes Tier-A facts, roles, and /grill-me bank."""
    repo = repo_dir.resolve()
    tier_a = scan_tier_a_signals(repo)
    binaries, commands, stacks, versions = detect_binaries_and_commands(repo)
    ext = detect_extended_signals(repo)

    merged_binaries = sorted(set(binaries) | set(ext["extra_binaries"]))
    merged_stacks = sorted(set(stacks) | set(ext["extra_stacks"]))
    merged_versions = {**versions, **tier_a["version_pins"]}
    merged_commands = dict(commands)
    for key, val in ext["extra_commands"].items():
        if not merged_commands.get(key) or "configure lint command" in str(merged_commands.get(key)):
            merged_commands[key] = val
    if not merged_commands.get("test") and (
        "python" in merged_stacks
        or (
            not merged_stacks
            and (
                pack in ("adk", "gecx")
                or (toolchain_manifest_path and toolchain_manifest_path.parent.name in ("adk", "gecx"))
            )
        )
    ):
        merged_commands["test"] = "pytest -q"

    git_ci = detect_git_and_ci(repo)
    if (repo / "Jenkinsfile").is_file() and git_ci.get("ci_platform") == "none":
        git_ci["ci_platform"] = "jenkins"
        git_ci["workflows"] = sorted(set(git_ci.get("workflows") or []) | {"Jenkinsfile"})

    knowledge = detect_knowledge_sources(repo)
    untrusted_hooks, ai_divergence, advisory_findings = detect_hooks_and_ai_divergence(repo)
    gaps = detect_modernization_gaps(repo, git_ci, untrusted_hooks=untrusted_hooks, ai_divergence=ai_divergence)

    if tier_a["skill_collisions"]:
        advisory_findings.append({
            "code": "SKILL_NAME_COLLISION",
            "severity": "high",
            "blocking": False,
            "paths": tier_a["skill_collisions"],
            "message": f"Local skill directory collides with pack skill name: {', '.join(tier_a['skill_collisions'])}.",
        })
    for warn in tier_a["tier_c_warnings"]:
        advisory_findings.append({
            "code": warn["code"],
            "severity": "medium",
            "blocking": False,
            "message": warn["message"],
        })
    if tier_a["git_support_tier"] == "best_effort":
        advisory_findings.append({
            "code": "NON_GITHUB_BEST_EFFORT",
            "severity": "low",
            "blocking": False,
            "message": (
                f"Detected non-GitHub remote host '{tier_a['remote_host']}'. "
                "Scion clones HTTPS via project GITHUB_TOKEN secret; PR automation and Delta Watcher run in best-effort mode."
            ),
        })

    # Merge extended monorepo layouts (5 canonical layouts from Tier-A) with legacy ext monorepo object.
    monorepo = {
        "detected": bool(tier_a["monorepo"]["detected"] or ext["monorepo"]["detected"]),
        "tool": tier_a["monorepo"]["tool"] or ext["monorepo"]["tool"],
        "layouts": tier_a["monorepo"]["layouts"],
        "candidates": sorted(set(tier_a["monorepo"]["candidates"]) | set(ext["monorepo"]["candidates"]))[:25],
    }

    pack_rec = recommend_pack({"stacks": merged_stacks})
    chosen_pack = pack or pack_rec["pack"]
    effective_manifest = _resolve_pack_manifest(toolchain_manifest_path, chosen_pack)

    baked: set[str] = set()
    heavy_candidates = set(HEAVY_TEST_BINARIES)
    if effective_manifest and effective_manifest.is_file():
        manifest = load_json(effective_manifest)
        baked = set(manifest.get("baked_binaries", {}).keys())
        heavy_candidates.update(manifest.get("heavy_test_candidates", []))

    missing_all = sorted(b for b in merged_binaries if b not in baked)
    installable_missing = [b for b in missing_all if b in SUPPORTED_RECIPE_BINARIES]
    unsupported_missing = [b for b in missing_all if b not in SUPPORTED_RECIPE_BINARIES]
    heavy_missing = sorted(b for b in installable_missing if b in heavy_candidates)
    core_missing = sorted(b for b in installable_missing if b not in heavy_candidates)

    for binary in unsupported_missing:
        gap_id = "GAP-TOOLCHAIN-" + "".join(ch if ch.isalnum() else "-" for ch in binary.upper()).strip("-")
        gaps.append({
            "id": gap_id[:40],
            "title": f"Add .factory/Dockerfile.customer recipe for '{binary}'",
            "severity": "medium",
            "effort": "M",
            "status": "open",
            "benefit": f"Provides pinned container support for '{binary}' verified by Stage 03.",
        })

    facts: dict[str, Any] = {
        "repo_path": str(repo),
        "stacks": merged_stacks,
        "runtime_versions": merged_versions,
        "detected_binaries": merged_binaries,
        "missing_binaries": core_missing,
        "heavy_test_binaries": heavy_missing,
        "unsupported_binaries": unsupported_missing,
        "commands": merged_commands,
        "frontend_frameworks": ext["frontend_frameworks"],
        "monorepo": monorepo,
        "deploy_signals": ext["deploy_signals"],
        "suggested_deploy_target": ext["suggested_deploy_target"],
        "ai_files_detected": tier_a["ai_files"],
        "skill_collisions": tier_a["skill_collisions"],
        "untrusted_hooks_detected": untrusted_hooks,
        "ai_file_divergence": ai_divergence,
        "advisory_findings": advisory_findings,
        "git_flow": git_ci,
        "git_support_tier": tier_a["git_support_tier"],
        "tier_a": tier_a,
        "knowledge_sources": knowledge,
        "modernization_gaps": gaps,
    }

    facts["recommended_pack"] = pack_rec
    facts["selected_pack"] = chosen_pack
    facts["proposed_roles"] = propose_roles(facts, pack=chosen_pack, track=track, roster_preset=roster_preset)
    facts["grill_questions"] = select_grill_questions(
        pack=chosen_pack,
        track=track,
        scan_facts=facts,
        roster_preset=roster_preset,
    )
    return facts


def detect_repo_drift(
    repo_dir: pathlib.Path,
    toolchain_manifest_path: pathlib.Path | None = None,
    config_path: pathlib.Path | None = None,
) -> dict[str, Any]:
    """Compares current repo scan against .factory/factory.yaml (or legacy factory-profile.yaml) for Day-2 drift."""
    scan = scan_repository_facts(repo_dir, toolchain_manifest_path)
    profile_path = config_path or (
        repo_dir / ".factory" / "factory.yaml"
        if (repo_dir / ".factory" / "factory.yaml").is_file()
        else repo_dir / ".factory" / "factory-profile.yaml"
    )
    notes: list[str] = []
    all_missing_vs_pack = set(scan["missing_binaries"]) | set(scan["heavy_test_binaries"])

    if not profile_path.is_file():
        missing_list = sorted(all_missing_vs_pack) if toolchain_manifest_path else []
        return {
            "drift_detected": bool(missing_list),
            "missing_binaries": missing_list,
            "notes": [_truncate_note("No .factory/factory.yaml found. Run factory-onboard for baseline.")],
        }

    prof = load_yaml(profile_path)
    if not isinstance(prof, dict):
        raise ValueError(f"{profile_path} must contain a YAML mapping.")

    prev_bins = set(prof.get("detected_binaries") or [])
    curr_bins = set(scan["detected_binaries"])
    added_bins = sorted(curr_bins - prev_bins)
    removed_bins = sorted(prev_bins - curr_bins)
    if added_bins:
        notes.append(_truncate_note(f"New repository binaries detected since onboarding: {', '.join(added_bins)}."))
    if removed_bins:
        notes.append(_truncate_note(f"Repository binaries removed since onboarding: {', '.join(removed_bins)}."))

    covered_by_profile = set(prof.get("missing_binaries") or []) | set(prof.get("heavy_test_binaries") or [])
    unsatisfied = sorted(all_missing_vs_pack - covered_by_profile) if toolchain_manifest_path else []

    prev_ai = set(prof.get("ai_files_detected") or [])
    curr_ai = set(scan["ai_files_detected"])
    added_ai = sorted(curr_ai - prev_ai)
    if added_ai:
        notes.append(_truncate_note(f"New AI instruction files detected: {', '.join(added_ai)}."))

    prev_wf = set((prof.get("git_flow") or {}).get("workflows") or [])
    curr_wf = set(scan["git_flow"].get("workflows") or [])
    added_wf = sorted(curr_wf - prev_wf)
    if added_wf:
        notes.append(_truncate_note(f"New CI workflows detected: {', '.join(added_wf)}."))

    return {
        "drift_detected": bool(added_bins or removed_bins or added_ai or added_wf or unsatisfied),
        "missing_binaries": unsatisfied,
        "notes": notes,
    }
