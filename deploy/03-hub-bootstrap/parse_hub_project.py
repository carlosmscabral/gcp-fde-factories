#!/usr/bin/env python3
"""Validated YAML parser and Vertex AI harness renderer for .factory/hub-project.yaml.

Enforces pack matching, blocks ../ path traversal on overlay_skills, defaults weekly Kaizen
scheduling to enabled=true, and fails closed if Claude Vertex AI is requested without explicit
manual Vertex AI Model Garden opt-in (`harnesses.claude_model_garden_enabled: true`).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

import yaml

MODEL_GARDEN_URL = "https://console.cloud.google.com/vertex-ai/publishers/anthropic/model-garden/claude-opus-5-5"

DEFAULT_CONFIG: dict[str, Any] = {
    "pack": "",
    "mode": "sandbox-direct",
    "diversity_profile": "cross-model",
    "limits": {
        "default_max_duration": "2h",
        "default_max_turns": 60,
        "auto_suspend_idle": True,
    },
    "exclude_skills": [],
    "overlay_skills": [],
    "kaizen": {
        "enabled": True,
        "schedule_cron": "0 17 * * 5",
        "time_zone": "America/Sao_Paulo",
        "coordinator_agent": "coordinator",
    },
    "harnesses": {
        "default": "antigravity-vertex",
        "claude_model_garden_enabled": False,
        "vertex_gemini_location": "global",
        "vertex_claude_region": "global",
    },
    "model_routing": {},
}


def parse_hub_project(repo_dir: pathlib.Path, expected_pack: str = "") -> dict[str, Any]:
    """Loads and validates .factory/hub-project.yaml under repo_dir, returning normalized JSON."""
    repo = repo_dir.resolve()
    cfg_path = repo / ".factory" / "hub-project.yaml"
    if not cfg_path.is_file():
        return json.loads(json.dumps(DEFAULT_CONFIG))

    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{cfg_path} must contain a YAML mapping.")

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
        "schedule_cron": str(raw_kz.get("schedule_cron") or "0 17 * * 5"),
        "time_zone": str(raw_kz.get("time_zone") or "America/Sao_Paulo"),
        "coordinator_agent": str(raw_kz.get("coordinator_agent") or "coordinator"),
    }

    raw_h = raw.get("harnesses") if isinstance(raw.get("harnesses"), dict) else {}
    has_explicit_h = "harnesses" in raw and isinstance(raw.get("harnesses"), dict)
    claude_enabled = bool(
        raw_h["claude_model_garden_enabled"]
        if "claude_model_garden_enabled" in raw_h
        else (diversity == "cross-vendor" and not has_explicit_h)
    )
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
            "(Antigravity gemini-4-neon-high + gemini-4-carbon-high)."
        )

    return {
        "pack": pack,
        "mode": mode,
        "diversity_profile": diversity,
        "limits": limits,
        "exclude_skills": [str(s) for s in (raw.get("exclude_skills") or [])],
        "overlay_skills": overlays,
        "kaizen": kaizen,
        "harnesses": harnesses,
        "model_routing": raw_routing,
    }


def render_harness_config(
    src_yaml: pathlib.Path,
    dst_yaml: pathlib.Path,
    inference_project: str,
    gemini_location: str,
    claude_region: str,
) -> None:
    """Materializes customer Vertex AI project and location into a staged harness config.yaml."""
    data = yaml.safe_load(src_yaml.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected YAML mapping in {src_yaml}")
    env = dict(data.get("env") or {})
    harness = str(data.get("harness") or "")
    if harness == "claude":
        env["CLAUDE_CODE_USE_VERTEX"] = "1"
        env["GOOGLE_CLOUD_LOCATION"] = claude_region
        env["CLOUD_ML_REGION"] = claude_region
        if inference_project:
            env["GOOGLE_CLOUD_PROJECT"] = inference_project
            env["ANTHROPIC_VERTEX_PROJECT_ID"] = inference_project
    elif harness == "antigravity":
        env["GOOGLE_GENAI_USE_VERTEXAI"] = "true"
        env["GOOGLE_CLOUD_LOCATION"] = gemini_location
        if inference_project:
            env["GOOGLE_CLOUD_PROJECT"] = inference_project
    data["env"] = env
    dst_yaml.parent.mkdir(parents=True, exist_ok=True)
    dst_yaml.write_text(yaml.safe_dump(data, sort_keys=False, width=120), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint parsing .factory/hub-project.yaml or rendering staged Vertex AI harness configs."""
    parser = argparse.ArgumentParser(description="Parse .factory/hub-project.yaml or render harness configs.")
    parser.add_argument("--repo", type=pathlib.Path)
    parser.add_argument("--expected-pack", default="")
    parser.add_argument("--render-harness-src", type=pathlib.Path)
    parser.add_argument("--render-harness-dst", type=pathlib.Path)
    parser.add_argument("--inference-project", default="")
    parser.add_argument("--gemini-location", default="global")
    parser.add_argument("--claude-region", default="global")
    args = parser.parse_args(argv)
    try:
        if args.render_harness_src and args.render_harness_dst:
            render_harness_config(
                args.render_harness_src,
                args.render_harness_dst,
                args.inference_project,
                args.gemini_location,
                args.claude_region,
            )
            return 0
        if not args.repo:
            parser.error("--repo is required unless --render-harness-src/dst are provided.")
        result = parse_hub_project(args.repo, expected_pack=args.expected_pack)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"HUB-PROJECT PARSE ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
