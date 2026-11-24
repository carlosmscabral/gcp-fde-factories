"""Opinionated Vertex AI-first harness and per-role model routing presets (Scion v0.4.0-preview.3).

Uses Scion's generic semantic tier aliases (`small`, `medium`, `large`, `extra-large`) and
canonical `thinking_level` (`0-100`) instead of hardcoded model versions so concrete models
evolve automatically with upstream Scion releases (while still allowing explicit ID overrides).
"""
from __future__ import annotations

from typing import Any


def build_default_harnesses_and_routing(
    diversity_profile: str,
    raw_harnesses: dict[str, Any] | None = None,
    raw_routing: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Builds Vertex AI-first harnesses config and generic tier model_routing for a project overlay."""
    in_h = raw_harnesses if isinstance(raw_harnesses, dict) else {}
    claude_enabled = bool(
        in_h["claude_model_garden_enabled"]
        if "claude_model_garden_enabled" in in_h
        else (diversity_profile == "cross-vendor")
    )
    harnesses: dict[str, Any] = {
        "default": str(in_h.get("default") or "antigravity-vertex"),
        "claude_model_garden_enabled": claude_enabled,
        "vertex_gemini_location": str(in_h.get("vertex_gemini_location") or "global"),
        "vertex_claude_region": str(in_h.get("vertex_claude_region") or "global"),
    }

    if diversity_profile == "cross-vendor" and claude_enabled:
        preset_routing: dict[str, dict[str, Any]] = {
            "default": {"harness": "antigravity-vertex", "model": "extra-large", "thinking_level": 100},
            "developer": {"harness": "antigravity-vertex", "model": "extra-large", "thinking_level": 100},
            "architect": {"harness": "antigravity-vertex", "model": "extra-large", "thinking_level": 100},
            "code-reviewer": {"harness": "claude-vertex", "model": "large", "thinking_level": 75},
            "security-auditor": {"harness": "claude-vertex", "model": "large", "thinking_level": 75},
            "kaizen-analyst": {"harness": "antigravity-vertex", "model": "extra-large", "thinking_level": 75},
            "doc-writer": {"harness": "antigravity-vertex", "model": "medium", "thinking_level": 50},
        }
    elif diversity_profile == "cross-model":
        preset_routing = {
            "default": {"harness": "antigravity-vertex", "model": "extra-large", "thinking_level": 100},
            "developer": {"harness": "antigravity-vertex", "model": "extra-large", "thinking_level": 100},
            "architect": {"harness": "antigravity-vertex", "model": "extra-large", "thinking_level": 100},
            "code-reviewer": {"harness": "antigravity-vertex", "model": "large", "thinking_level": 100},
            "security-auditor": {"harness": "antigravity-vertex", "model": "large", "thinking_level": 100},
            "kaizen-analyst": {"harness": "antigravity-vertex", "model": "extra-large", "thinking_level": 75},
            "doc-writer": {"harness": "antigravity-vertex", "model": "medium", "thinking_level": 50},
        }
    else:
        preset_routing = {
            "default": {"harness": "antigravity-vertex", "model": "extra-large", "thinking_level": 100},
            "doc-writer": {"harness": "antigravity-vertex", "model": "medium", "thinking_level": 50},
        }

    if isinstance(raw_routing, dict):
        merged = dict(preset_routing)
        for role, spec in raw_routing.items():
            if isinstance(spec, dict) and spec.get("harness") and spec.get("model"):
                merged[str(role)] = dict(spec)
        return harnesses, merged
    return harnesses, preset_routing
