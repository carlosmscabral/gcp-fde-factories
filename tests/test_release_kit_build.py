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

    # Every generated template must carry the gecx- prefix, zero external URIs, and no fixed model.
    assert scan_for_floating_uris(out_dir / "templates") == []
    tpl_dirs = sorted(p for p in (out_dir / "templates").iterdir() if p.is_dir())
    assert len(tpl_dirs) == 5
    for tdir in tpl_dirs:
        assert tdir.name.startswith("gecx-")
        assert not tdir.name.startswith("gecx-gecx-")
        agent_cfg = yaml.safe_load((tdir / "scion-agent.yaml").read_text(encoding="utf-8"))
        assert "model" not in agent_cfg
        assert "harness_config" not in agent_cfg

    # Every skill directory basename must match manifest skill name for scion skills publish.
    manifest_disk = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    for sk in manifest_disk["skills"]:
        assert (out_dir / "skills" / sk["name"] / "SKILL.md").exists()
