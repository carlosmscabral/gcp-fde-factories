"""Streamlined 2-block /grill-me selector and pre-filled v2 draft factory.yaml builder (Wave 2).

Loads core-gcp-fde/data/grill-questions.yaml and generates pre-filled unified v2 factory.yaml
drafts (or legacy v1 drafts when explicitly requested) so the LLM never re-asks Tier-A facts
and surfaces the lean (5-role) vs full (agent-team) tradeoff explicitly to the PO.
"""
from __future__ import annotations

import pathlib
import re
from typing import Any

from scripts.lib.dockerfile_recipes import INSTALL_RECIPES
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


def _default_intake_from_scan(scan_facts: dict[str, Any]) -> dict[str, Any]:
    """Derives an opt-in External Delta Watcher default from detected repository CI/hosting signals."""
    tier_a = scan_facts.get("tier_a") or {}
    remote_host = str(tier_a.get("remote_host") or "")
    ci_platform = str((scan_facts.get("git_flow") or {}).get("ci_platform") or "github-actions")
    provider_map = {
        "github-actions": "github",
        "azure-devops": "azure_devops",
        "gitlab-ci": "gitlab",
    }
    provider = remote_host if remote_host in ("github", "gitlab", "azure_devops") else provider_map.get(ci_platform, "github")
    return {
        "enabled": False,
        "provider": provider,
        "max_concurrent_issues": 2,
        "scope_label": "",
        "release_label": "factory:ready",
        "hold_label": "factory:hold",
        "cadence_cron": "*/5 * * * *",
        "time_zone": "America/Sao_Paulo",
        "paused": False,
    }


def _prefill_for_field(field_path: str, scan_facts: dict[str, Any], pack: str, roster: dict[str, Any]) -> Any:
    """Extracts pre-filled Tier-A scan evidence so /grill-me never re-asks discovered facts."""
    tier_a = scan_facts.get("tier_a") or {}
    mapping: dict[str, Any] = {
        "mission": {
            "recommended_pack": pack,
            "monorepo": scan_facts.get("monorepo"),
            "git_support_tier": scan_facts.get("git_support_tier", "native_github"),
        },
        "pack": pack,
        "commands": {
            "commands": scan_facts.get("commands"),
            "ci_workflow_pointers": tier_a.get("ci_workflow_pointers", []),
            "task_wrappers": tier_a.get("task_wrappers", []),
            "package_json_script_keys": tier_a.get("package_json_script_keys", []),
        },
        "monorepo": scan_facts.get("monorepo"),
        "toolchain": {
            "runtime_versions": scan_facts.get("runtime_versions", {}),
            "missing_binaries": scan_facts.get("missing_binaries", []),
            "heavy_test_binaries": scan_facts.get("heavy_test_binaries", []),
            "unsupported_binaries": scan_facts.get("unsupported_binaries", []),
            "private_registries": tier_a.get("private_registries", []),
            "env_example_keys": tier_a.get("env_example_keys", []),
            "local_services": tier_a.get("local_services", []),
            "tier_c_warnings": tier_a.get("tier_c_warnings", []),
        },
        "absorbed_conventions": {
            "ai_files_detected": scan_facts.get("ai_files_detected", []),
            "skill_collisions": scan_facts.get("skill_collisions", []),
            "advisory_findings": scan_facts.get("advisory_findings", []),
        },
        "mode": {
            "mode": "sandbox-direct",
            "deploy_target": scan_facts.get("suggested_deploy_target"),
            "diversity_profile": "cross-model",
        },
        "roster": roster,
        "intake": _default_intake_from_scan(scan_facts),
        "invariants": {"modernization_gaps_for_wave_0": scan_facts.get("modernization_gaps", [])},
    }
    return mapping.get(field_path)


def select_grill_questions(
    pack: str,
    track: str = "complete",
    scan_facts: dict[str, Any] | None = None,
    questions_path: pathlib.Path | None = None,
    roster_preset: str = "lean",
) -> list[dict[str, Any]]:
    """Returns the streamlined 2-block /grill-me interview pre-filled with Tier-A evidence."""
    facts = scan_facts or {}
    raw = load_yaml(_find_questions_yaml(questions_path))
    questions = raw.get("questions") if isinstance(raw, dict) else []
    roster = propose_roles(facts, pack=pack, track=track, roster_preset=roster_preset)

    selected: list[dict[str, Any]] = []
    for item in questions:
        if not isinstance(item, dict):
            continue
        packs = item.get("applies_to_packs") or ["all"]
        if "all" not in packs and pack not in packs:
            continue
        entry: dict[str, Any] = {
            "id": str(item["id"]),
            "block": str(item.get("block") or "po"),
            "pillar": str(item["pillar"]),
            "field_path": str(item["field_path"]),
            "prompt": str(item["prompt"]),
            "why_we_ask": str(item["why_we_ask"]),
            "challenge_prompt": str(item["challenge_prompt"]),
        }
        prefilled = _prefill_for_field(entry["field_path"], facts, pack, roster)
        if prefilled is not None:
            entry["prefilled_from_scan"] = prefilled
        selected.append(entry)
    return selected


def build_draft_profile(
    scan_facts: dict[str, Any],
    pack: str | None = None,
    track: str = "complete",
    pack_version: str | None = None,
    roster_preset: str = "lean",
    schema_version: str = "2",
) -> dict[str, Any]:
    """Builds a pre-filled unified factory.yaml (v2) draft from static scan facts for PO confirmation."""
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

    proposed = propose_roles(
        scan_facts,
        pack=chosen_pack,
        deploy_target=deploy_target,
        track=track,
        roster_preset=roster_preset,
    )
    monorepo_info = scan_facts.get("monorepo") or {}
    l2_default = {
        "generic": "python3 /opt/generic-factory/generic_sandbox_gate.py --level 2",
        "adk": "python3 /opt/adk-factory/adk_sandbox_gate.py",
        "gecx": "python3 /opt/gecx-foundry/gecx_sandbox_gate.py",
    }.get(chosen_pack, "python3 /opt/generic-factory/generic_sandbox_gate.py --level 2")

    git_flow = scan_facts.get("git_flow") or {
        "base_branch": "main",
        "branch_pattern": "feat/<issue>-<slug>",
        "commit_convention": "conventional-commits",
        "ci_platform": "none",
        "pr_template": None,
        "workflows": [],
        "has_codeowners": False,
    }
    commands = scan_facts.get("commands") or {
        "build": "",
        "lint": "echo 'configure lint command'",
        "test": "pytest -q",
        "e2e": "",
    }

    if schema_version == "1":
        draft_v1: dict[str, Any] = {
            "schema_version": "1",
            "slug": slug,
            "pack": chosen_pack,
            "pack_version": version,
            "track": track,
            "existing_hub": True,
            "mode": "sandbox-direct",
            "deploy_target": deploy_target,
            "diversity_profile": "cross-model",
            "autonomy": "supervised",
            "git_flow": git_flow,
            "commands": commands,
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
            "kaizen_schedule_cron": "0 0 * * *",
            "kaizen_time_zone": "America/Sao_Paulo",
            "intake": _default_intake_from_scan(scan_facts),
        }
        if monorepo_info.get("detected"):
            draft_v1["monorepo"] = {
                "enabled": True,
                "tool": str(monorepo_info.get("tool") or "custom"),
                "subdir": "",
                "agent_prefix": proposed["pack_prefix"],
            }
        return draft_v1

    # Derive verify_binaries strictly from known recipe smoke commands so strict Dockerfile linting matches (M5).
    verify_bins: list[str] = []
    for b in list(scan_facts.get("missing_binaries") or []):
        recipe = INSTALL_RECIPES.get(b)
        if recipe:
            for part in recipe.smoke_cmd.split("&&"):
                cmd = " ".join(part.strip().split())
                if cmd and cmd not in verify_bins:
                    verify_bins.append(cmd)
    draft: dict[str, Any] = {
        "schema_version": "2",
        "slug": slug,
        "pack": chosen_pack,
        "pack_version": version,
        "confirmed_by": "",
        "existing_hub": False,
        "mode": "sandbox-direct",
        "deploy_target": deploy_target,
        "diversity_profile": "cross-model",
        "autonomy": "supervised",
        "git_support_tier": str(scan_facts.get("git_support_tier") or "native_github"),
        "mission": "",
        "non_goals": [],
        "git_flow": git_flow,
        "commands": commands,
        "toolchain": {
            "dockerfile": None,
            "tester_dockerfile": None,
            "verify_binaries": verify_bins,
            "pinned_image": None,
        },
        "detected_binaries": list(scan_facts.get("detected_binaries") or []),
        "missing_binaries": list(scan_facts.get("missing_binaries") or []),
        "heavy_test_binaries": list(scan_facts.get("heavy_test_binaries") or []),
        "ai_files_detected": list(scan_facts.get("ai_files_detected") or []),
        "acknowledged_workspace_hazards": [],
        "absorbed_conventions": [],
        "knowledge_sources": list(scan_facts.get("knowledge_sources") or []),
        "requirements": [],
        "invariants": [],
        "decisions": [],
        "glossary": [],
        "evaluation_pyramid": {
            "l1_offline": str(commands.get("test") or "pytest -q"),
            **({} if deploy_target == "none" else {"l2_sandbox": l2_default}),
        },
        "not_verifiable_in_sandbox": [],
        "roster": {
            "preset": proposed["preset"],
            "enabled_roles": [r["role"] for r in proposed["enabled_roles"]],
            "disabled_roles": proposed["disabled_roles"],
            "max_wip": proposed["max_wip"],
            "reviewer_replicas": proposed["reviewer_replicas"],
        },
        "wave_0": list(scan_facts.get("modernization_gaps") or []),
        "waves": [],
        "intake": _default_intake_from_scan(scan_facts),
    }
    if monorepo_info.get("detected"):
        # Leave agent_prefix empty so PO chooses a unique subproject prefix instead of colliding on pack_prefix (H3).
        draft["monorepo"] = {
            "enabled": True,
            "tool": str(monorepo_info.get("tool") or "custom"),
            "subdir": "",
            "agent_prefix": "",
        }
    return draft
