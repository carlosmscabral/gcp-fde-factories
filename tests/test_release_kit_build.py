"""Tests for offline Release Kit composition, zero external URIs, and stripped hardcoded models."""
from __future__ import annotations

import json
import pathlib

import yaml

from scripts.lib.lock_verifier import scan_for_floating_uris
from scripts.lib.release_kit import build_release_kit

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_release_kit_is_offline_prefix_isolated_and_model_free(tmp_path: pathlib.Path) -> None:
    """Verifies Release Kit output satisfies Phase 1a offline handoff acceptance criteria."""
    out_dir = tmp_path / "gecx-kit"
    manifest = build_release_kit(REPO_ROOT, REPO_ROOT / "packs/gecx", out_dir)

    assert manifest["pack"] == "gecx"
    assert manifest["external_uris_remaining"] == 0
    assert (out_dir / "NOTICE").exists()
    assert (out_dir / "compat.yaml").exists()
    assert (out_dir / "skills.lock").exists()
    assert (out_dir / "bootstrap" / "bootstrap-hub-project.sh").exists()
    assert (out_dir / "bootstrap" / "stage-release-kit.sh").exists()
    assert (out_dir / "bootstrap" / "cloudbuild.yaml").exists()

    # Every generated template must follow Scion v0.4 template rules:
    # directory basename = name, zero external URIs, no model/harness_config, no env keys, no symlinks.
    assert scan_for_floating_uris(out_dir / "templates") == []
    tpl_dirs = sorted(p for p in (out_dir / "templates").iterdir() if p.is_dir())
    assert len(tpl_dirs) == 5
    forbidden_keys = {
        "name",
        "model",
        "harness",
        "harness_config",
        "default_harness_config",
        "image",
        "resources",
        "volumes",
        "kubernetes",
        "hub",
        "telemetry",
        "persistence",
    }
    for tdir in tpl_dirs:
        assert tdir.name.startswith("gecx-")
        assert not tdir.name.startswith("gecx-gecx-")
        cfg_file = tdir / "scion-agent.yaml"
        assert cfg_file.is_file() and not cfg_file.is_symlink()
        agent_cfg = yaml.safe_load(cfg_file.read_text(encoding="utf-8"))
        assert forbidden_keys.isdisjoint(agent_cfg.keys())
        assert agent_cfg["schema_version"] == "1"
        assert agent_cfg["description"]
        assert agent_cfg["agent_instructions"] == "agents.md"
        assert agent_cfg["system_prompt"] == "system-prompt.md"
        for content_file in (tdir / "agents.md", tdir / "system-prompt.md"):
            assert content_file.is_file() and not content_file.is_symlink()
            assert content_file.stat().st_size > 0

    # Every skill directory basename must match manifest skill name for scion skills publish.
    manifest_disk = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    for sk in manifest_disk["skills"]:
        assert (out_dir / "skills" / sk["name"] / "SKILL.md").exists()
