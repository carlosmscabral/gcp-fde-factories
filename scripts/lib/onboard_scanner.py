"""Zero-token static repository scanner and Day-2 drift detector (v0.4.0).

Orchestrates structured manifest parsers from onboard_parsers to produce discovery reports
and computes Day-2 drift relative to .factory/factory-profile.yaml.
"""
from __future__ import annotations

import pathlib
from typing import Any

from scripts.lib.dockerfile_recipes import INSTALL_RECIPES
from scripts.lib.io_utils import load_json, load_yaml
from scripts.lib.onboard_parsers import (
    detect_binaries_and_commands,
    detect_git_and_ci,
    detect_knowledge_sources,
    detect_modernization_gaps,
)

AI_FILE_CANDIDATES = (
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    ".cursorrules",
    ".github/copilot-instructions.md",
)

HEAVY_TEST_BINARIES = {"playwright", "playwright-node", "jdk", "mvn"}
SUPPORTED_RECIPE_BINARIES = frozenset(INSTALL_RECIPES.keys())


def _truncate_note(text: str, limit: int = 200) -> str:
    """Bounds a drift note to schema maxLength without splitting surrogate bytes."""
    clean = " ".join(text.split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."


def scan_repository_facts(
    repo_dir: pathlib.Path,
    toolchain_manifest_path: pathlib.Path | None = None,
) -> dict[str, Any]:
    """Scans repo_dir statically and computes the toolchain delta against the target pack."""
    repo = repo_dir.resolve()
    binaries, commands, stacks, versions = detect_binaries_and_commands(repo)
    git_ci = detect_git_and_ci(repo)
    knowledge = detect_knowledge_sources(repo)
    gaps = detect_modernization_gaps(repo, git_ci)

    ai_files = [rel for rel in AI_FILE_CANDIDATES if (repo / rel).is_file()]
    if (repo / ".claude" / "skills").is_dir():
        ai_files.append(".claude/skills/")

    baked: set[str] = set()
    heavy_candidates = set(HEAVY_TEST_BINARIES)
    if toolchain_manifest_path and toolchain_manifest_path.is_file():
        manifest = load_json(toolchain_manifest_path)
        baked = set(manifest.get("baked_binaries", {}).keys())
        heavy_candidates.update(manifest.get("heavy_test_candidates", []))

    missing_all = sorted(b for b in binaries if b not in baked)
    installable_missing = [b for b in missing_all if b in SUPPORTED_RECIPE_BINARIES]
    unsupported_missing = [b for b in missing_all if b not in SUPPORTED_RECIPE_BINARIES]
    heavy_missing = sorted(b for b in installable_missing if b in heavy_candidates)
    core_missing = sorted(b for b in installable_missing if b not in heavy_candidates)

    for binary in unsupported_missing:
        gap_id = "GAP-TOOLCHAIN-" + "".join(ch if ch.isalnum() else "-" for ch in binary.upper()).strip("-")
        gaps.append({
            "id": gap_id[:40],
            "title": f"Add manual Dockerfile recipe for unsupported binary '{binary}'",
            "severity": "medium",
            "effort": "M",
            "status": "open",
            "benefit": f"Provides pinned container support for '{binary}' outside the standard recipe allowlist.",
        })

    return {
        "repo_path": str(repo),
        "stacks": stacks,
        "runtime_versions": versions,
        "detected_binaries": binaries,
        "missing_binaries": core_missing,
        "heavy_test_binaries": heavy_missing,
        "unsupported_binaries": unsupported_missing,
        "commands": commands,
        "ai_files_detected": ai_files,
        "git_flow": git_ci,
        "knowledge_sources": knowledge,
        "modernization_gaps": gaps,
    }


def detect_repo_drift(
    repo_dir: pathlib.Path,
    toolchain_manifest_path: pathlib.Path | None = None,
) -> dict[str, Any]:
    """Compares current repo scan against .factory/factory-profile.yaml for Day-2 Kaizen drift."""
    scan = scan_repository_facts(repo_dir, toolchain_manifest_path)
    profile_path = repo_dir / ".factory" / "factory-profile.yaml"
    notes: list[str] = []
    all_missing_vs_pack = set(scan["missing_binaries"]) | set(scan["heavy_test_binaries"])

    if not profile_path.is_file():
        missing_list = sorted(all_missing_vs_pack) if toolchain_manifest_path else []
        return {
            "drift_detected": bool(missing_list),
            "missing_binaries": missing_list,
            "notes": [_truncate_note("No .factory/factory-profile.yaml found. Run factory-onboard for baseline.")],
        }

    prof = load_yaml(profile_path)
    if not isinstance(prof, dict):
        raise ValueError(".factory/factory-profile.yaml must contain a YAML mapping.")

    prev_bins = set(prof.get("detected_binaries") or [])
    curr_bins = set(scan["detected_binaries"])
    added_bins = sorted(curr_bins - prev_bins)
    removed_bins = sorted(prev_bins - curr_bins)
    if added_bins:
        notes.append(_truncate_note(f"New repository binaries detected since onboarding: {', '.join(added_bins)}."))
    if removed_bins:
        notes.append(_truncate_note(f"Repository binaries removed since onboarding: {', '.join(removed_bins)}."))

    # Exclude binaries already covered by the emitted Layer 3 customer Dockerfiles.
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
