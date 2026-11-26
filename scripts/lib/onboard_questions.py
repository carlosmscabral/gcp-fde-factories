"""Declarative 6-pillar /grill-me selector and pre-filled draft profile builder (ADR-016).

Loads core-gcp-fde/data/grill-questions.yaml from the catalog repository, Release Kit, or
container image (/opt/gcp-fde/data/) and selects only questions relevant to the chosen pack,
track, and static scan facts.
"""
from __future__ import annotations

import pathlib
import re
from typing import Any

from scripts.lib.io_utils import load_yaml
from scripts.lib.onboard_roles import (
    PACK_DEFAULT_VERSIONS,
    propose_roles,
    recommend_pack,
)

SLUG_CLEAN_RE = re.compile(r"[^a-z0-9-]+")


def _find_questions_yaml(explicit_path: pathlib.Path | None = None) -> pathlib.Path:
    """Locates grill-questions.yaml across explicit path, repo root, Release Kit, or container."""
    if explicit_path and explicit_path.is_file():
        return explicit_path
    here = pathlib.Path(__file__).resolve()
    repo_root = here.parent.parent.parent
    candidates = (
        repo_root / "core-gcp-fde" / "data" / "grill-questions.yaml",
        repo_root / "data" / "grill-questions.yaml",
        pathlib.Path("/opt/gcp-fde/data/grill-questions.yaml"),
    )
    for cand in candidates:
        if cand.is_file():
            return cand
    raise FileNotFoundError("Could not locate core-gcp-fde/data/grill-questions.yaml.")


def _sanitize_slug(raw_name: str) -> str:
    """Converts a directory name into a schema-valid lowercase slug (2..33 chars)."""
    cleaned = SLUG_CLEAN_RE.sub("-", raw_name.lower()).strip("-")
    if not cleaned or not cleaned[0].isalpha():
        cleaned = f"app-{cleaned}" if cleaned else "app-factory"
    if len(cleaned) < 2:
        cleaned = f"{cleaned}-app"
    return cleaned[:33].rstrip("-") or "app-factory"


def _prefill_for_field(field_path: str, scan_facts: dict[str, Any], pack: str, roster: dict[str, Any]) -> Any:
    """Extracts pre-filled static scan evidence so /grill-me never re-asks discovered facts."""
    mapping: dict[str, Any] = {
        "pack": pack,
        "commands": scan_facts.get("commands"),
        "monorepo": scan_facts.get("monorepo"),
        "missing_binaries": {
            "missing_binaries": scan_facts.get("missing_binaries", []),
            "heavy_test_binaries": scan_facts.get("heavy_test_binaries", []),
            "unsupported_binaries": scan_facts.get("unsupported_binaries", []),
        },
        "absorbed_conventions": {
            "ai_files_detected": scan_facts.get("ai_files_detected", []),
            "advisory_findings": scan_facts.get("advisory_findings", []),
        },
        "deploy_target": scan_facts.get("suggested_deploy_target"),
        "roster": roster,
    }
    return mapping.get(field_path)


def select_grill_questions(
    pack: str,
    track: str,
    scan_facts: dict[str, Any],
    questions_path: pathlib.Path | None = None,
) -> list[dict[str, Any]]:
    """Filters the 6-pillar question bank for the selected pack, track, and repository signals."""
    raw = load_yaml(_find_questions_yaml(questions_path))
    questions = raw.get("questions") if isinstance(raw, dict) else []
    monorepo_detected = bool((scan_facts.get("monorepo") or {}).get("detected"))
    has_missing_toolchain = bool(
        (scan_facts.get("missing_binaries") or [])
        or (scan_facts.get("heavy_test_binaries") or [])
        or (scan_facts.get("unsupported_binaries") or [])
    )
    roster = propose_roles(scan_facts, pack=pack, track=track)

    selected: list[dict[str, Any]] = []
    for item in questions:
        if not isinstance(item, dict):
            continue
        packs = item.get("applies_to_packs") or ["all"]
        tracks = item.get("applies_to_tracks") or ["express", "complete"]
        pack_match = "all" in packs or pack in packs
        if not pack_match:
            continue
        track_match = track in tracks or (
            pack == "generic" and track == "express" and bool(item.get("required_for_generic_express"))
        )
        if not track_match:
            continue
        if item.get("only_when_monorepo") and not monorepo_detected:
            continue
        if item.get("only_when_missing_toolchain") and not has_missing_toolchain and pack != "generic":
            continue

        entry = {
            "id": str(item["id"]),
            "pillar": str(item["pillar"]),
            "field_path": str(item["field_path"]),
            "prompt": str(item["prompt"]),
            "why_we_ask": str(item["why_we_ask"]),
            "challenge_prompt": str(item["challenge_prompt"]),
        }
        prefilled = _prefill_for_field(entry["field_path"], scan_facts, pack, roster)
        if prefilled is not None:
            entry["prefilled_from_scan"] = prefilled
        selected.append(entry)
    return selected


def build_draft_profile(
    scan_facts: dict[str, Any],
    pack: str | None = None,
    track: str = "complete",
    pack_version: str | None = None,
) -> dict[str, Any]:
    """Builds a pre-filled factory-profile.yaml draft from static scan facts for PO confirmation."""
    rec = recommend_pack(scan_facts)
    chosen_pack = pack or rec["pack"]
    version = pack_version or PACK_DEFAULT_VERSIONS.get(chosen_pack, "0.6.0")
    repo_name = pathlib.Path(str(scan_facts.get("repo_path") or "app-factory")).name
    slug = _sanitize_slug(repo_name)

    suggested_deploy = str(scan_facts.get("suggested_deploy_target") or "none")
    if chosen_pack == "adk":
        deploy_target = "agent-engine"
    elif chosen_pack == "gecx":
        deploy_target = "ces"
    else:
        deploy_target = suggested_deploy

    proposed = propose_roles(scan_facts, pack=chosen_pack, deploy_target=deploy_target, track=track)
    monorepo_info = scan_facts.get("monorepo") or {}
    draft: dict[str, Any] = {
        "schema_version": "1",
        "slug": slug,
        "pack": chosen_pack,
        "pack_version": version,
        "track": track,
        "existing_hub": False,
        "mode": "sandbox-direct",
        "deploy_target": deploy_target,
        "diversity_profile": "cross-model",
        "autonomy": "supervised",
        "git_flow": scan_facts.get("git_flow") or {
            "base_branch": "main",
            "branch_pattern": "feat/<issue>-<slug>",
            "commit_convention": "conventional-commits",
            "ci_platform": "none",
            "pr_template": None,
            "workflows": [],
            "has_codeowners": False,
        },
        "commands": scan_facts.get("commands") or {"build": "", "lint": "echo 'configure lint command'", "test": "pytest -q", "e2e": ""},
        "detected_binaries": list(scan_facts.get("detected_binaries") or []),
        "missing_binaries": list(scan_facts.get("missing_binaries") or []),
        "heavy_test_binaries": list(scan_facts.get("heavy_test_binaries") or []),
        "ai_files_detected": list(scan_facts.get("ai_files_detected") or []),
        "absorbed_conventions": [],
        "knowledge_sources": list(scan_facts.get("knowledge_sources") or []),
        "roster": {
            "enabled_roles": [r["role"] for r in proposed["enabled_roles"]],
            "disabled_roles": proposed["disabled_roles"],
            "max_wip": proposed["max_wip"],
            "reviewer_replicas": proposed["reviewer_replicas"],
        },
        "modernization_gaps": list(scan_facts.get("modernization_gaps") or []),
        "kaizen_enabled": True,
        "kaizen_schedule_cron": "0 17 * * 5",
        "kaizen_time_zone": "America/Sao_Paulo",
    }
    if monorepo_info.get("detected"):
        draft["monorepo"] = {
            "enabled": True,
            "tool": str(monorepo_info.get("tool") or "custom"),
            "subdir": "",
            "agent_prefix": proposed["pack_prefix"],
        }
    if track == "complete":
        l2_default = {
            "generic": "python3 /opt/generic-factory/generic_sandbox_gate.py --level 2",
            "adk": "python3 /opt/adk-factory/adk_sandbox_gate.py",
            "gecx": "python3 /opt/gecx-foundry/gecx_sandbox_gate.py",
        }.get(chosen_pack, "python3 /opt/generic-factory/generic_sandbox_gate.py --level 2")
        draft.update({
            "mission": "",
            "non_goals": [],
            "requirements": [],
            "invariants": [],
            "decisions": [],
            "glossary": [],
            "evaluation_pyramid": {
                "l1_offline": str(draft["commands"].get("test") or "pytest -q"),
                **({} if deploy_target == "none" else {"l2_sandbox": l2_default}),
            },
            "not_verifiable_in_sandbox": [],
            "waves": [],
        })
    return draft
