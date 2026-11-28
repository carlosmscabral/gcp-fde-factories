"""Wave 2 unified .factory/[<prefix>/]factory.yaml builder and zero-placeholder Day-0 planner.

Consolidates factory-profile.yaml + hub-project.yaml into a single .factory/[<prefix>/]factory.yaml,
preserves Day-2 operational overrides (M6), derives non-colliding monorepo coordinator names and
harness_config_prefix hints (H2, H3), renders surgical <6 KB AGENTS.md blocks, and omits empty
Day-0 Knowledge Plane placeholders. Validation logic lives in scripts/lib/onboard_validator.py.
"""
from __future__ import annotations

import hashlib
import pathlib
from typing import Any

import yaml

from scripts.lib.io_utils import assert_no_symlink_escape
from scripts.lib.model_routing import build_default_harnesses_and_routing
from scripts.lib.onboard_roles import PACK_PREFIXES
from scripts.lib.onboard_tier_a import read_git_origin_url
from scripts.lib.onboard_validator import (
    AGENTS_MD_MAX_BYTES,
    check_v2_readiness,
    validate_confirmed_by,
    validate_factory_repo,
)
from scripts.lib.schema_validator import validate_against_schema

__all__ = [
    "AGENTS_MD_MAX_BYTES",
    "build_unified_factory_yaml",
    "check_v2_readiness",
    "compute_harness_config_prefix",
    "plan_optional_v2_knowledge_files",
    "render_surgical_agents_block",
    "resolve_conventions_skill_dir",
    "resolve_factory_dir_rel",
    "validate_confirmed_by",
    "validate_factory_repo",
]


def resolve_factory_dir_rel(profile: dict[str, Any]) -> str:
    """Returns '.factory/<agent_prefix>' for monorepo subprojects or '.factory' for single-factory repos."""
    mono = profile.get("monorepo") if isinstance(profile.get("monorepo"), dict) else {}
    if mono.get("enabled") and str(mono.get("agent_prefix") or "").strip():
        return f".factory/{str(mono['agent_prefix']).strip()}"
    return ".factory"


def resolve_conventions_skill_dir(profile: dict[str, Any]) -> str:
    """Returns a non-colliding repo-conventions skill directory across monorepo siblings (H3)."""
    slug = str(profile["slug"])
    mono = profile.get("monorepo") if isinstance(profile.get("monorepo"), dict) else {}
    if mono.get("enabled") and str(mono.get("agent_prefix") or "").strip():
        prefix = str(mono["agent_prefix"]).strip()
        return f"skills/{slug}-{prefix}-repo-conventions"
    return f"skills/{slug}-repo-conventions"


def compute_harness_config_prefix(
    pack: str,
    slug: str,
    monorepo: dict[str, Any] | None,
    has_custom_dockerfile: bool,
    origin_url: str = "",
) -> str:
    """Computes a collision-free harness-config prefix across shared Hubs (H2, M10)."""
    pack_prefix = PACK_PREFIXES.get(pack, pack)
    if not has_custom_dockerfile:
        return pack_prefix
    mono = monorepo if isinstance(monorepo, dict) else {}
    mono_prefix = str(mono.get("agent_prefix") or "").strip() if mono.get("enabled") else ""
    base = f"{pack_prefix}-{slug or 'customer'}"
    if mono_prefix and mono_prefix != pack_prefix:
        base = f"{base}-{mono_prefix}"
    if origin_url.strip():
        short_hash = hashlib.sha256(origin_url.strip().encode("utf-8")).hexdigest()[:6]
        return f"{base}-{short_hash}"
    return base


def build_unified_factory_yaml(
    repo: pathlib.Path,
    profile: dict[str, Any],
    *,
    factory_dir_rel: str,
    conv_dir_rel: str,
    skill_ver: str,
    core_df_rel: str | None,
    tester_df_rel: str | None,
    factory_schema_path: pathlib.Path,
) -> tuple[dict[str, Any], str]:
    """Builds and validates consolidated .factory/[<prefix>/]factory.yaml preserving Day-2 overrides (M6, H3)."""
    cfg_rel = f"{factory_dir_rel}/factory.yaml"
    cfg_path = assert_no_symlink_escape(repo, repo / cfg_rel)
    existing = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) if cfg_path.is_file() else {}
    existing = existing if isinstance(existing, dict) else {}

    preserved_overlays = [
        ov for ov in (existing.get("overlay_skills") or [])
        if isinstance(ov, dict) and ov.get("dir") != conv_dir_rel
    ]
    preserved_overlays.append({"dir": conv_dir_rel, "version": skill_ver})

    default_limits = {
        "default_max_duration": "2h",
        "default_max_turns": 60,
        "default_max_model_calls": 150,
        "auto_suspend_idle": True,
    }
    merged_limits = {**default_limits, **(existing.get("limits") or {}), **(profile.get("limits") or {})}
    harnesses_cfg, model_routing_cfg = build_default_harnesses_and_routing(
        diversity_profile=str(profile["diversity_profile"]),
        raw_harnesses={**(existing.get("harnesses") or {}), **(profile.get("harnesses") or {})} or None,
        raw_routing={**(existing.get("model_routing") or {}), **(profile.get("model_routing") or {})} or None,
    )

    pack = str(profile["pack"])
    pack_prefix = PACK_PREFIXES.get(pack, pack)
    mono_cfg = profile.get("monorepo") if isinstance(profile.get("monorepo"), dict) else None
    mono_enabled = bool(mono_cfg and mono_cfg.get("enabled"))
    coord_prefix = str(mono_cfg.get("agent_prefix") or pack_prefix) if mono_enabled else pack_prefix
    existing_coord = str(((existing.get("kaizen") or {}).get("coordinator_agent")) or "")
    requested_coord = str(((profile.get("kaizen") or {}).get("coordinator_agent")) or "")
    # Derive monorepo coordinator from agent_prefix unless operator explicitly specified a custom name (H3, M6).
    if requested_coord and (not mono_enabled or requested_coord != f"{pack_prefix}-coordinator"):
        coordinator_name = requested_coord
    elif existing_coord and existing_coord != "coordinator" and (not mono_enabled or existing_coord.startswith(f"{coord_prefix}-")):
        coordinator_name = existing_coord
    else:
        coordinator_name = f"{coord_prefix}-coordinator"

    # Preserve PO-marked 'done' status on wave_0 items without resurrecting items the PO removed (M6).
    prev_w0 = {str(g["id"]): g for g in (existing.get("wave_0") or []) if isinstance(g, dict) and g.get("id")}
    merged_w0: list[dict[str, Any]] = []
    for item in (profile.get("wave_0") or []):
        gid = str(item["id"])
        if gid in prev_w0:
            merged_w0.append({**item, "status": prev_w0[gid].get("status", "open")})
        else:
            merged_w0.append(dict(item))

    existing_tc = existing.get("toolchain") if isinstance(existing.get("toolchain"), dict) else {}
    profile_tc = profile.get("toolchain") if isinstance(profile.get("toolchain"), dict) else {}
    toolchain_cfg = {
        "dockerfile": profile_tc.get("dockerfile") or core_df_rel or existing_tc.get("dockerfile"),
        "tester_dockerfile": profile_tc.get("tester_dockerfile") or tester_df_rel or existing_tc.get("tester_dockerfile"),
        "verify_binaries": list(profile_tc.get("verify_binaries") or existing_tc.get("verify_binaries") or []),
        "pinned_image": profile_tc.get("pinned_image") or existing_tc.get("pinned_image"),
    }

    existing_kz = existing.get("kaizen") if isinstance(existing.get("kaizen"), dict) else {}
    profile_kz = profile.get("kaizen") if isinstance(profile.get("kaizen"), dict) else {}
    # Preserve Day-2 kaizen settings from existing config unless explicitly overridden in profile (M6).
    kaizen_cfg = {
        "enabled": bool(profile_kz["enabled"] if "enabled" in profile_kz else existing_kz.get("enabled", True)),
        "schedule_cron": str(profile_kz.get("schedule_cron") or existing_kz.get("schedule_cron") or "0 0 * * *"),
        "time_zone": str(profile_kz.get("time_zone") or existing_kz.get("time_zone") or "America/Sao_Paulo"),
        "coordinator_agent": coordinator_name,
        "enable_gcp_obs": bool(profile_kz.get("enable_gcp_obs", existing_kz.get("enable_gcp_obs", False))),
    }

    # Merge existing -> profile so Day-2 edited fields survive re-emission without clobbering (M6).
    unified = {**existing, **profile}
    unified.update({
        "schema_version": "2",
        "limits": merged_limits,
        "harnesses": harnesses_cfg,
        "model_routing": model_routing_cfg,
        "exclude_skills": list(profile.get("exclude_skills") or existing.get("exclude_skills") or []),
        "overlay_skills": preserved_overlays,
        "toolchain": toolchain_cfg,
        "kaizen": kaizen_cfg,
        "wave_0": merged_w0,
    })

    if factory_schema_path.is_file():
        errs = validate_against_schema(unified, factory_schema_path)
        if errs:
            raise ValueError("Generated factory.yaml failed schema validation: " + " | ".join(errs))
    return unified, coordinator_name


def render_surgical_agents_block(profile: dict[str, Any], factory_dir_rel: str, conv_dir_rel: str) -> str:
    """Renders a compact, non-discoverable AGENTS.md overlay block (well under the 6 KB budget)."""
    cmds = profile.get("commands") or {}
    invs = list(profile.get("invariants") or [])[:5]
    non_goals = list(profile.get("non_goals") or [])[:3]
    preset = str((profile.get("roster") or {}).get("preset") or "lean")
    lines = [
        f"## Factory Overlay (`{profile['slug']}` · `{profile['pack']}@{profile['pack_version']}` · roster `{preset}`)",
        f"- Config: `{factory_dir_rel}/factory.yaml` | Brief: `{factory_dir_rel}/coordinator-bootstrap-brief.md` | Skill: `{conv_dir_rel}/SKILL.md`",
        f"- Fast checks: lint `{cmds.get('lint', '')}` | test `{cmds.get('test', '')}`"
        + (f" | build `{cmds['build']}`" if cmds.get("build") else ""),
    ]
    if invs:
        lines.append("- Hard invariants: " + " · ".join(invs))
    if non_goals:
        lines.append("- Non-goals: " + " · ".join(non_goals))
    return "\n".join(lines)


def plan_optional_v2_knowledge_files(
    repo: pathlib.Path,
    profile: dict[str, Any],
    factory_dir_rel: str,
    coordinator_name: str,
    *,
    force_knowledge: bool = False,
) -> dict[str, Any]:
    """Plans zero-placeholder Day-0 artifacts: emits knowledge docs only when PO supplied content."""
    planned: list[tuple[pathlib.Path, bytes, str]] = []
    preserved: list[str] = []

    optional_docs: list[tuple[str, str]] = []
    if profile.get("requirements"):
        req_lines = [f"# Requirements (`{profile['slug']}`)", ""]
        for req in profile["requirements"]:
            req_lines.append(f"## {req['id']}: {req['summary']}")
            for ac in req.get("acceptance_criteria") or []:
                req_lines.append(f"- {ac}")
            req_lines.append("")
        optional_docs.append((f"{factory_dir_rel}/knowledge/requirements.md", "\n".join(req_lines).rstrip() + "\n"))
    if profile.get("decisions"):
        dec_lines = [f"# Architecture Decisions (`{profile['slug']}`)", ""]
        for dec in profile["decisions"]:
            dec_lines.append(f"- **{dec['id']} ({dec.get('status', 'accepted')}) — {dec['title']}:** {dec['decision']}")
        optional_docs.append((f"{factory_dir_rel}/knowledge/decisions.md", "\n".join(dec_lines) + "\n"))
    if profile.get("glossary"):
        gl_lines = [f"# Domain Glossary (`{profile['slug']}`)", ""]
        for item in profile["glossary"]:
            gl_lines.append(f"- **{item['term']}:** {item['definition']}")
        optional_docs.append((f"{factory_dir_rel}/knowledge/glossary.md", "\n".join(gl_lines) + "\n"))

    for rel, content in optional_docs:
        path = assert_no_symlink_escape(repo, repo / rel)
        if path.exists() and not force_knowledge:
            preserved.append(rel)
        else:
            planned.append((path, content.encode("utf-8"), rel))

    roster = profile.get("roster") or {}
    preset = str(roster.get("preset") or "lean")
    enabled = roster.get("enabled_roles") or []
    disabled = [d["role"] if isinstance(d, dict) else str(d) for d in (roster.get("disabled_roles") or [])]
    mono = profile.get("monorepo") if isinstance(profile.get("monorepo"), dict) else {}
    subdir = str(mono.get("subdir") or "").strip() if mono.get("enabled") else ""
    w0_open = [g for g in (profile.get("wave_0") or []) if isinstance(g, dict) and g.get("status", "open") != "done"]
    tc = profile.get("toolchain") if isinstance(profile.get("toolchain"), dict) else {}
    origin_url = read_git_origin_url(repo)
    hc_prefix = compute_harness_config_prefix(
        str(profile["pack"]),
        str(profile["slug"]),
        mono,
        bool(tc.get("dockerfile") or tc.get("tester_dockerfile")),
        origin_url=origin_url,
    )

    brief_lines = [
        f"# Coordinator Standby Brief (`{coordinator_name}`)",
        "",
        f"- Factory config: `{factory_dir_rel}/factory.yaml` (confirmed by `{profile['confirmed_by']}`)",
        f"- Pack: `{profile['pack']}@{profile['pack_version']}` | Preset: `{preset}` | Autonomy: `{profile['autonomy']}` | Deploy: `{profile.get('deploy_target', 'default')}`",
        f"- Harness config prefix for ALL spawned workers: `harness_config_prefix={hc_prefix}` (pass `--harness-config {hc_prefix}-<harness>` on every `scion start`)",
    ]
    if tc.get("tester_dockerfile"):
        brief_lines.append(
            f"- Heavy tester harness config (qa-tester / E2E): `--harness-config {hc_prefix}-tester-antigravity-vertex`"
        )
    brief_lines.extend([
        f"- Scope: `{subdir or 'repository root'}` | Git hosting: `{profile.get('git_support_tier', 'native_github')}`",
        f"- Enabled roles: `{', '.join(enabled) if enabled else 'preset defaults'}`",
        f"- Disabled roles (do not spawn): `{', '.join(disabled) if disabled else 'none'}`",
        f"- Open Wave-0 modernization gaps: `{len(w0_open)}` | Seeded Wave-1 tasks: `{len(profile.get('waves') or [])}`",
        "",
        "## First-Turn Standby Gate",
        f"1. Read `{factory_dir_rel}/factory.yaml` and `AGENTS.md`.",
        "2. Post a concise readiness summary in Scion Chat listing Wave-1 tasks, active roster preset, and open Wave-0 items.",
        "3. Do NOT spawn workers or open PRs yet. Run `sciontool status blocked` until the Product Owner approves execution.",
    ])
    brief_rel = f"{factory_dir_rel}/coordinator-bootstrap-brief.md"
    planned.append((assert_no_symlink_escape(repo, repo / brief_rel), ("\n".join(brief_lines) + "\n").encode("utf-8"), brief_rel))
    return {"writes": planned, "preserved": preserved}
