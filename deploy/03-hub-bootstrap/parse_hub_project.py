#!/usr/bin/env python3
"""Validated YAML parser, overlay skill checker, and Vertex AI harness renderer for Stage 03.

Enforces hub-project.schema.json validation, pack matching, path-traversal protection on
overlay_skills, 300-line / non-colliding overlay skill budgets, default weekly Kaizen
scheduling, fail-closed Claude Vertex AI opt-in, and fail-closed rejection of placeholder
or zero-digest container images before syncing harness-configs to Scion Hub.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from typing import Any

import yaml

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
MODEL_GARDEN_URL = "https://console.cloud.google.com/vertex-ai/publishers/anthropic/model-garden/claude-opus-5-5"
ZERO_DIGEST = "@sha256:" + ("0" * 64)
MAX_OVERLAY_SKILL_LINES = 300
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def read_scion_project_id(settings_path: pathlib.Path) -> str:
    """Reads and UUID-validates hub.project_id from a Scion v0.4 .scion/settings.yaml file (costela H4)."""
    if not settings_path.is_file():
        return ""
    raw = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return ""
    hub = raw.get("hub")
    if not isinstance(hub, dict):
        return ""
    pid = str(hub.get("project_id") or "").strip()
    if not pid:
        return ""
    if not UUID_RE.fullmatch(pid):
        raise ValueError(f"Invalid hub.project_id UUID in {settings_path}: '{pid}'.")
    return pid

DEFAULT_CONFIG: dict[str, Any] = {
    "pack": "",
    "mode": "sandbox-direct",
    "diversity_profile": "cross-model",
    "limits": {
        "default_max_duration": "2h",
        "default_max_turns": 60,
        "default_max_model_calls": 150,
        "auto_suspend_idle": True,
    },
    "exclude_skills": [],
    "overlay_skills": [],
    "kaizen": {
        "enabled": True,
        "schedule_cron": "0 0 * * *",
        "time_zone": "America/Sao_Paulo",
        "coordinator_agent": "coordinator",
        "enable_gcp_obs": False,
    },
    "harnesses": {
        "default": "antigravity-vertex",
        "claude_model_garden_enabled": False,
        "vertex_gemini_location": "global",
        "vertex_claude_region": "global",
    },
    "model_routing": {},
    "deploy_target": "",
    "monorepo": {"enabled": False, "subdir": "", "agent_prefix": ""},
    "roster": {"enabled_roles": [], "disabled_roles": [], "max_wip": 3, "reviewer_replicas": 1},
    "intake": {
        "enabled": False,
        "provider": "github",
        "max_concurrent_issues": 2,
        "scope_label": "",
        "release_label": "factory:ready",
        "hold_label": "factory:hold",
        "cadence_cron": "*/5 * * * *",
        "time_zone": "America/Sao_Paulo",
        "paused": False,
    },
}


def _find_hub_project_schema() -> pathlib.Path | None:
    """Locates schemas/hub-project.schema.json inside a Release Kit or catalog repo."""
    candidates = (
        SCRIPT_DIR.parent / "schemas" / "hub-project.schema.json",
        SCRIPT_DIR.parent.parent / "schemas" / "hub-project.schema.json",
        pathlib.Path("/opt/gcp-fde/schemas/hub-project.schema.json"),
    )
    for cand in candidates:
        if cand.is_file():
            return cand
    return None


def _validate_hub_schema(raw: dict[str, Any]) -> None:
    """Validates raw YAML mapping against hub-project.schema.json when jsonschema is available."""
    schema_path = _find_hub_project_schema()
    if schema_path is None:
        return
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        return
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    errs = [
        f"{'/'.join(str(p) for p in err.path) or '<root>'}: {err.message}"
        for err in sorted(validator.iter_errors(raw), key=lambda e: list(e.path))
    ]
    if errs:
        raise ValueError("hub-project.schema.json validation failed: " + " | ".join(errs))


def parse_hub_project(repo_dir: pathlib.Path, expected_pack: str = "") -> dict[str, Any]:
    """Loads and validates .factory/hub-project.yaml under repo_dir, returning normalized JSON."""
    repo = repo_dir.resolve()
    cfg_path = repo / ".factory" / "hub-project.yaml"
    if not cfg_path.is_file():
        return json.loads(json.dumps(DEFAULT_CONFIG))

    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{cfg_path} must contain a YAML mapping.")

    _validate_hub_schema(raw)

    pack = str(raw.get("pack") or "")
    if expected_pack and pack and pack != expected_pack:
        raise ValueError(f"Pack mismatch: {cfg_path} declares pack '{pack}', but Release Kit is '{expected_pack}'.")

    mode = str(raw.get("mode") or "sandbox-direct")
    if mode not in ("sandbox-direct", "ci-only"):
        raise ValueError(f"Invalid mode '{mode}' in {cfg_path}. Expected 'sandbox-direct' or 'ci-only'.")

    diversity = str(raw.get("diversity_profile") or "cross-model")
    if diversity not in ("cross-vendor", "cross-model", "single-family"):
        raise ValueError(f"Invalid diversity_profile '{diversity}' in {cfg_path}.")

    raw_limits = raw.get("limits") if isinstance(raw.get("limits"), dict) else {}
    limits = {
        "default_max_duration": str(raw_limits.get("default_max_duration") or "2h"),
        "default_max_turns": int(raw_limits.get("default_max_turns") or 60),
        "default_max_model_calls": int(raw_limits.get("default_max_model_calls") or 150),
        "auto_suspend_idle": bool(raw_limits.get("auto_suspend_idle", True)),
    }

    overlays: list[dict[str, str]] = []
    for item in raw.get("overlay_skills") or []:
        if not isinstance(item, dict) or not item.get("dir"):
            raise ValueError(f"Invalid overlay_skills entry in {cfg_path}: {item!r}")
        rel = str(item["dir"])
        resolved = (repo / rel).resolve()
        try:
            resolved.relative_to(repo)
        except ValueError as exc:
            raise ValueError(f"Overlay skill path escapes repository root: '{rel}'") from exc
        overlays.append({"dir": rel, "version": str(item.get("version") or "1.0.0")})

    raw_kz = raw.get("kaizen") if isinstance(raw.get("kaizen"), dict) else {}
    kaizen = {
        "enabled": bool(raw_kz.get("enabled", True)),
        "schedule_cron": str(raw_kz.get("schedule_cron") or "0 0 * * *"),
        "time_zone": str(raw_kz.get("time_zone") or "America/Sao_Paulo"),
        "coordinator_agent": str(raw_kz.get("coordinator_agent") or "coordinator"),
        "enable_gcp_obs": bool(raw_kz.get("enable_gcp_obs", False)),
    }

    raw_h = raw.get("harnesses") if isinstance(raw.get("harnesses"), dict) else {}
    claude_enabled = bool(raw_h.get("claude_model_garden_enabled", False))
    harnesses = {
        "default": str(raw_h.get("default") or "antigravity-vertex"),
        "claude_model_garden_enabled": claude_enabled,
        "vertex_gemini_location": str(raw_h.get("vertex_gemini_location") or "global"),
        "vertex_claude_region": str(raw_h.get("vertex_claude_region") or "global"),
    }
    if harnesses["default"] not in ("antigravity-vertex", "claude-vertex"):
        raise ValueError(f"Invalid harnesses.default '{harnesses['default']}' in {cfg_path}.")

    raw_routing = raw.get("model_routing") if isinstance(raw.get("model_routing"), dict) else {}
    uses_claude_routing = any(
        isinstance(spec, dict) and spec.get("harness") == "claude-vertex"
        for spec in raw_routing.values()
    )
    if not claude_enabled and (
        diversity == "cross-vendor" or harnesses["default"] == "claude-vertex" or uses_claude_routing
    ):
        raise ValueError(
            "Claude Vertex AI harness requested while harnesses.claude_model_garden_enabled is false. "
            f"Enable claude-opus-5-5 manually in Vertex AI Model Garden ({MODEL_GARDEN_URL}) and set "
            "harnesses.claude_model_garden_enabled: true, OR switch diversity_profile to 'cross-model' "
            "(Antigravity extra-large + large)."
        )

    raw_mono = raw.get("monorepo") if isinstance(raw.get("monorepo"), dict) else {}
    mono_subdir = str(raw_mono.get("subdir") or "").strip()
    if mono_subdir:
        resolved_sub = (repo / mono_subdir).resolve()
        try:
            resolved_sub.relative_to(repo)
        except ValueError as exc:
            raise ValueError(f"monorepo.subdir escapes repository root: '{mono_subdir}'") from exc
    monorepo = {
        "enabled": bool(raw_mono.get("enabled", False)),
        "subdir": mono_subdir,
        "agent_prefix": str(raw_mono.get("agent_prefix") or ""),
    }

    raw_roster = raw.get("roster") if isinstance(raw.get("roster"), dict) else {}
    roster = {
        "enabled_roles": [str(r) for r in (raw_roster.get("enabled_roles") or [])],
        "disabled_roles": [str(r) for r in (raw_roster.get("disabled_roles") or [])],
        "max_wip": int(raw_roster.get("max_wip") or 3),
        "reviewer_replicas": int(raw_roster.get("reviewer_replicas") or 1),
    }

    raw_intake = raw.get("intake") if isinstance(raw.get("intake"), dict) else {}
    intake_provider = str(raw_intake.get("provider") or "github")
    if intake_provider not in ("github", "azure_devops", "gitlab", "jira"):
        raise ValueError(f"Invalid intake.provider '{intake_provider}' in {cfg_path}.")
    intake_cap = int(raw_intake.get("max_concurrent_issues") if raw_intake.get("max_concurrent_issues") is not None else 2)
    if intake_cap < 1 or intake_cap > 3:
        raise ValueError(f"Invalid intake.max_concurrent_issues {intake_cap} in {cfg_path}. Expected 1..3.")
    intake = {
        "enabled": bool(raw_intake.get("enabled", False)),
        "provider": intake_provider,
        "max_concurrent_issues": intake_cap,
        "scope_label": str(raw_intake.get("scope_label") or ""),
        "release_label": str(raw_intake.get("release_label") or "factory:ready"),
        "hold_label": str(raw_intake.get("hold_label") or "factory:hold"),
        "cadence_cron": str(raw_intake.get("cadence_cron") or "*/5 * * * *"),
        "time_zone": str(raw_intake.get("time_zone") or "America/Sao_Paulo"),
        "paused": bool(raw_intake.get("paused", False)),
    }

    raw_bf = raw.get("brownfield") if isinstance(raw.get("brownfield"), dict) else {}
    return {
        "pack": pack,
        "mode": mode,
        "deploy_target": str(raw.get("deploy_target") or ""),
        "existing_hub": bool(raw_bf.get("existing_hub", False)),
        "diversity_profile": diversity,
        "limits": limits,
        "exclude_skills": [str(s) for s in (raw.get("exclude_skills") or [])],
        "overlay_skills": overlays,
        "kaizen": kaizen,
        "harnesses": harnesses,
        "model_routing": raw_routing,
        "monorepo": monorepo,
        "roster": roster,
        "intake": intake,
    }


def _assert_real_container_image(image_ref: str, src_path: pathlib.Path) -> None:
    """Fails closed when a harness-config image still holds a placeholder or zero digest."""
    if not image_ref or "REPLACE_" in image_ref or ZERO_DIGEST in image_ref:
        raise ValueError(
            f"Harness config '{src_path.name}' still references placeholder image '{image_ref}'. "
            "Run stage-release-kit.sh --mode rebuild with --antigravity-base-image / --claude-base-image, "
            "or pass --harness-image-antigravity / --harness-image-claude to bootstrap-hub-project.sh apply."
        )


def render_harness_config(
    src_yaml: pathlib.Path,
    dst_yaml: pathlib.Path,
    inference_project: str,
    gemini_location: str,
    claude_region: str,
    image_override: str = "",
    base_yaml: pathlib.Path | None = None,
) -> None:
    """Materializes customer Vertex AI project, region, and validated image onto an upstream Scion harness config.

    When base_yaml is supplied (pulled from the Hub's built-in antigravity or claude harness bundle),
    inherits upstream provisioner, command, model_aliases, thinking levels, and auth rules intact while
    overlaying Vertex AI settings and stripping non-schema catalog keys (schema_version, name, resources).
    """
    overlay = yaml.safe_load(src_yaml.read_text(encoding="utf-8"))
    if not isinstance(overlay, dict):
        raise ValueError(f"Expected YAML mapping in {src_yaml}")

    if base_yaml is not None and base_yaml.is_file():
        base_data = yaml.safe_load(base_yaml.read_text(encoding="utf-8"))
        if not isinstance(base_data, dict):
            raise ValueError(f"Expected YAML mapping in base harness config {base_yaml}")
        data: dict[str, Any] = dict(base_data)
    else:
        data = {}

    for key in ("harness", "image", "user", "model", "auth_selected_type", "args"):
        if key in overlay and overlay[key] not in (None, ""):
            data[key] = overlay[key]
    data.setdefault("user", "scion")
    for forbidden_key in ("schema_version", "name", "resources"):
        data.pop(forbidden_key, None)

    if image_override:
        data["image"] = image_override
    _assert_real_container_image(str(data.get("image") or ""), src_yaml)

    env = dict(data.get("env") or {})
    if isinstance(overlay.get("env"), dict):
        env.update(overlay["env"])
    harness = str(data.get("harness") or "")
    if harness == "claude":
        env["CLAUDE_CODE_USE_VERTEX"] = "1"
        env["GOOGLE_CLOUD_LOCATION"] = claude_region
        env["CLOUD_ML_REGION"] = claude_region
        if inference_project:
            env["GOOGLE_CLOUD_PROJECT"] = inference_project
            env["GOOGLE_CLOUD_QUOTA_PROJECT"] = inference_project
            env["ANTHROPIC_VERTEX_PROJECT_ID"] = inference_project
    elif harness == "antigravity":
        env["GOOGLE_GENAI_USE_VERTEXAI"] = "true"
        env["GOOGLE_CLOUD_LOCATION"] = gemini_location
        env["AGY_ADC_AUTH"] = "true"
        if inference_project:
            # Antigravity CLI 1.5.14 in AGY_ADC_AUTH mode routes Vertex AI through ADC quotaProject (HC-02 F8).
            env["GOOGLE_CLOUD_PROJECT"] = inference_project
            env["GOOGLE_CLOUD_QUOTA_PROJECT"] = inference_project
    data["env"] = env
    dst_yaml.parent.mkdir(parents=True, exist_ok=True)
    dst_yaml.write_text(yaml.safe_dump(data, sort_keys=False, width=120), encoding="utf-8")


def check_overlay_skill(skill_dir: pathlib.Path, pack_skill_names: set[str]) -> None:
    """Verifies an overlay skill directory has SKILL.md <= 300 lines and zero pack name collision."""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        raise ValueError(f"Overlay skill missing SKILL.md: {skill_dir}")
    sname = skill_dir.name
    if sname in pack_skill_names:
        raise ValueError(f"Overlay skill '{sname}' collides with an installed pack skill name.")
    text = skill_md.read_text(encoding="utf-8")
    lines = len(text.splitlines())
    if lines > MAX_OVERLAY_SKILL_LINES:
        raise ValueError(f"Overlay skill '{sname}' has {lines} lines (budget max: {MAX_OVERLAY_SKILL_LINES}).")
    if re.search(r"(?:^|\s)gh://", text):
        raise ValueError(f"Overlay skill '{sname}' contains a forbidden floating gh:// URI.")


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint parsing hub-project.yaml, checking overlay skills, or rendering harness configs."""
    parser = argparse.ArgumentParser(description="Parse .factory/hub-project.yaml or render harness configs.")
    parser.add_argument("--repo", type=pathlib.Path)
    parser.add_argument("--expected-pack", default="")
    parser.add_argument("--render-harness-src", type=pathlib.Path)
    parser.add_argument("--render-harness-dst", type=pathlib.Path)
    parser.add_argument("--base-harness-yaml", type=pathlib.Path, default=None)
    parser.add_argument("--inference-project", default="")
    parser.add_argument("--gemini-location", default="global")
    parser.add_argument("--claude-region", default="global")
    parser.add_argument("--pin-image", default="")
    parser.add_argument("--check-overlay-skill", type=pathlib.Path)
    parser.add_argument("--pack-skills-json", default="[]")
    parser.add_argument("--read-scion-project-id", type=pathlib.Path)
    args = parser.parse_args(argv)
    try:
        if args.read_scion_project_id:
            print(read_scion_project_id(args.read_scion_project_id))
            return 0
        if args.check_overlay_skill:
            pack_names = set(json.loads(args.pack_skills_json))
            check_overlay_skill(args.check_overlay_skill, pack_names)
            return 0
        if args.render_harness_src and args.render_harness_dst:
            render_harness_config(
                args.render_harness_src,
                args.render_harness_dst,
                args.inference_project,
                args.gemini_location,
                args.claude_region,
                image_override=args.pin_image,
                base_yaml=args.base_harness_yaml,
            )
            return 0
        if not args.repo:
            parser.error("--repo is required unless --render-harness-src/dst or --check-overlay-skill is set.")
        result = parse_hub_project(args.repo, expected_pack=args.expected_pack)
    except (OSError, ValueError, yaml.YAMLError, json.JSONDecodeError) as exc:
        print(f"HUB-PROJECT PARSE ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
