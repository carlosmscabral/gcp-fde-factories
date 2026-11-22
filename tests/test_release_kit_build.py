"""Tests for offline Release Kit composition with full 15-role Preston hierarchy and 10 Skill Bank skills."""
from __future__ import annotations

import json
import pathlib

import yaml

from scripts.lib.lock_verifier import scan_for_floating_uris
from scripts.lib.release_kit import build_release_kit

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_release_kit_is_offline_prefix_isolated_and_model_free(tmp_path: pathlib.Path) -> None:
    """Verifies Release Kit satisfies Scion v0.4 template rules and full 13+2 role hierarchy."""
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
    assert len(tpl_dirs) == 15
    tpl_names = {d.name for d in tpl_dirs}
    assert {
        "gecx-coordinator",
        "gecx-eng-manager",
        "gecx-architect",
        "gecx-investigator",
        "gecx-security-auditor",
        "gecx-developer",
        "gecx-code-reviewer",
        "gecx-test-engineer",
        "gecx-deployer",
        "gecx-eval-tester",
    }.issubset(tpl_names)

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
        for sk_ref in agent_cfg.get("skills", []):
            assert sk_ref["uri"].startswith("skill://scion/global/")
        for content_file in (tdir / "agents.md", tdir / "system-prompt.md"):
            assert content_file.is_file() and not content_file.is_symlink()
            assert content_file.stat().st_size > 0

    # Verify upstream agent-team instructions and GECX pack delta were actually merged.
    em_agents = (out_dir / "templates" / "gecx-eng-manager" / "agents.md").read_text(encoding="utf-8")
    assert "Pack Override Rules" in em_agents
    assert "Upstream Role Instructions" in em_agents
    assert "Engineering Manager" in em_agents

    # Verify 10 Hub Skill Bank skills: 5 project-attached guardrails + 5 role-scoped SEP skills.
    manifest_disk = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest_disk["skills"]) == 10
    attached = [s["name"] for s in manifest_disk["skills"] if s["attach_to_project"]]
    role_only = [s["name"] for s in manifest_disk["skills"] if not s["attach_to_project"]]
    assert len(attached) == 5
    assert set(role_only) == {
        "software-engineering-process",
        "agent-state-continuity",
        "artifact-durability",
        "code-review",
        "release-notes-daily",
    }
    for sk in manifest_disk["skills"]:
        assert (out_dir / "skills" / sk["name"] / "SKILL.md").exists()
    # Supporting files inside SEP skill (em-brief-template.md) must travel into the kit too.
    assert (
        out_dir / "skills" / "software-engineering-process" / "references" / "em-brief-template.md"
    ).exists()
