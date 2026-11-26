"""Non-destructive hub-project.yaml and modernization-backlog.yaml builders (v0.6.0).

Extracted from scripts/lib/onboard_emitter.py to keep modules under 300 lines.
Applies consistent profile-wins semantics for profile-owned fields while preserving
Day-2 operational overrides (exclude_skills, custom overlay_skills, enable_gcp_obs)
and refusing symlink traversal before any read.
"""
from __future__ import annotations

import pathlib
from typing import Any

import yaml

from scripts.lib.io_utils import assert_no_symlink_escape
from scripts.lib.model_routing import build_default_harnesses_and_routing
from scripts.lib.onboard_roles import PACK_PREFIXES
from scripts.lib.schema_validator import validate_against_schema


def build_hub_project_overlay(
    repo: pathlib.Path,
    profile: dict[str, Any],
    *,
    conv_dir_rel: str,
    skill_ver: str,
    core_df_rel: str | None,
    tester_df_rel: str | None,
    hub_schema_path: pathlib.Path,
) -> tuple[dict[str, Any], str]:
    """Builds and schema-validates .factory/hub-project.yaml with profile-wins consistency."""
    hub_proj_path = assert_no_symlink_escape(repo, repo / ".factory" / "hub-project.yaml")
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

    pack = str(profile["pack"])
    pack_prefix = PACK_PREFIXES.get(pack, pack)
    monorepo_cfg = profile.get("monorepo") if isinstance(profile.get("monorepo"), dict) else None
    mono_enabled = bool(monorepo_cfg and monorepo_cfg.get("enabled"))
    coord_prefix = str(monorepo_cfg.get("agent_prefix") or pack_prefix) if mono_enabled else pack_prefix
    existing_coord = str((existing_hub.get("kaizen") or {}).get("coordinator_agent") or "")
    # Update coordinator name when monorepo.agent_prefix changes; avoid bare 'coordinator' on v0.6.0+.
    if mono_enabled or not existing_coord or existing_coord == "coordinator":
        coordinator_name = f"{coord_prefix}-coordinator"
    else:
        coordinator_name = existing_coord

    hub_project: dict[str, Any] = {
        "schema_version": "1",
        "pack": pack,
        "pack_version": profile["pack_version"],
        "mode": profile["mode"],
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
            "coordinator_agent": coordinator_name,
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
    deploy_target = str(profile.get("deploy_target") or "")
    # Omit default pack-implicit deploy_target on adk/gecx to stay compatible with v0.5.0 kits (M13).
    if deploy_target and not (pack == "adk" and deploy_target == "agent-engine") and not (pack == "gecx" and deploy_target == "ces"):
        hub_project["deploy_target"] = deploy_target
    if mono_enabled and monorepo_cfg is not None:
        hub_project["monorepo"] = {
            "enabled": True,
            "subdir": str(monorepo_cfg.get("subdir") or ""),
            "agent_prefix": coord_prefix,
        }
    roster_cfg = profile.get("roster") if isinstance(profile.get("roster"), dict) else None
    if roster_cfg:
        hub_project["roster"] = {
            "enabled_roles": [str(r) for r in (roster_cfg.get("enabled_roles") or [])],
            "disabled_roles": [
                str(d["role"] if isinstance(d, dict) else d) for d in (roster_cfg.get("disabled_roles") or [])
            ],
            "max_wip": int(roster_cfg.get("max_wip") or 3),
            "reviewer_replicas": int(roster_cfg.get("reviewer_replicas") or 1),
        }

    if hub_schema_path.is_file():
        hub_errs = validate_against_schema(hub_project, hub_schema_path)
        if hub_errs:
            raise ValueError("Generated hub-project.yaml failed schema validation: " + " | ".join(hub_errs))
    return hub_project, coordinator_name


def merge_modernization_backlog(repo: pathlib.Path, profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Merges modernization gaps by ID so PO-marked 'done' statuses survive re-emission."""
    backlog_path = assert_no_symlink_escape(repo, repo / ".factory" / "modernization-backlog.yaml")
    existing_gaps: dict[str, dict[str, Any]] = {}
    if backlog_path.is_file():
        prev_bl = yaml.safe_load(backlog_path.read_text(encoding="utf-8"))
        if isinstance(prev_bl, dict):
            for gap in prev_bl.get("gaps") or []:
                if isinstance(gap, dict) and gap.get("id"):
                    existing_gaps[str(gap["id"])] = gap
    for gap in profile.get("modernization_gaps") or []:
        gid = str(gap["id"])
        if gid in existing_gaps:
            existing_gaps[gid] = {**gap, "status": existing_gaps[gid].get("status", "open")}
        else:
            existing_gaps[gid] = dict(gap)
    return list(existing_gaps.values())
