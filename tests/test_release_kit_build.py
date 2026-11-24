"""Tests for offline Release Kit composition across packs/gecx and packs/adk (16 roles + 11 skills)."""
from __future__ import annotations

import json
import pathlib

import yaml

from scripts.lib.lock_verifier import scan_for_floating_uris
from scripts.lib.release_kit import build_release_kit

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

FORBIDDEN_TEMPLATE_KEYS = {
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


def _assert_templates_follow_scion_v04_rules(
    out_dir: pathlib.Path, prefix: str, expected_count: int
) -> set[str]:
    """Asserts every generated template obeys offline Scion v0.4 rules and prefix isolation."""
    assert scan_for_floating_uris(out_dir / "templates") == []
    tpl_dirs = sorted(p for p in (out_dir / "templates").iterdir() if p.is_dir())
    assert len(tpl_dirs) == expected_count

    for tdir in tpl_dirs:
        assert tdir.name.startswith(f"{prefix}-")
        assert not tdir.name.startswith(f"{prefix}-{prefix}-")
        cfg_file = tdir / "scion-agent.yaml"
        assert cfg_file.is_file() and not cfg_file.is_symlink()
        agent_cfg = yaml.safe_load(cfg_file.read_text(encoding="utf-8"))
        assert FORBIDDEN_TEMPLATE_KEYS.isdisjoint(agent_cfg.keys())
        assert agent_cfg["schema_version"] == "1"
        assert agent_cfg["description"]
        assert agent_cfg["agent_instructions"] == "agents.md"
        assert agent_cfg["system_prompt"] == "system-prompt.md"
        for sk_ref in agent_cfg.get("skills", []):
            assert sk_ref["uri"].startswith("skill://scion/global/")
        for content_file in (tdir / "agents.md", tdir / "system-prompt.md"):
            assert content_file.is_file() and not content_file.is_symlink()
            assert content_file.stat().st_size > 0
        agents_text = (tdir / "agents.md").read_text(encoding="utf-8")
        assert f"`{prefix}-*`" in agents_text

    return {d.name for d in tpl_dirs}


def test_release_kit_is_offline_prefix_isolated_and_model_free(tmp_path: pathlib.Path) -> None:
    """Verifies packs/gecx Release Kit satisfies Scion v0.4 rules and full 13+3 role hierarchy."""
    out_dir = tmp_path / "gecx-kit"
    manifest = build_release_kit(REPO_ROOT, REPO_ROOT / "packs/gecx", out_dir)

    assert manifest["pack"] == "gecx"
    assert manifest["pack_prefix"] == "gecx"
    assert manifest["external_uris_remaining"] == 0
    assert manifest["toolchain_manifest"] == "packs/gecx/toolchain-manifest.json"
    assert (out_dir / "NOTICE").exists()
    assert (out_dir / "compat.yaml").exists()
    assert (out_dir / "skills.lock").exists()
    assert (out_dir / "core-gcp-fde" / "scripts" / "kaizen_collect.py").exists()
    assert (out_dir / "core-gcp-fde" / "scripts" / "factory_onboard.py").exists()
    assert (out_dir / "packs" / "gecx" / "toolchain-manifest.json").exists()
    assert (out_dir / "bootstrap" / "bootstrap-hub-project.sh").exists()
    assert (out_dir / "bootstrap" / "stage-release-kit.sh").exists()
    assert (out_dir / "bootstrap" / "cloudbuild.yaml").exists()

    tpl_names = _assert_templates_follow_scion_v04_rules(out_dir, "gecx", expected_count=16)
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
        "gecx-kaizen-analyst",
    }.issubset(tpl_names)

    kaizen_meta = next(t for t in manifest["templates"] if t["name"] == "gecx-kaizen-analyst")
    assert kaizen_meta["hub_role"] == "baseline"
    assert "gcp-kaizen-analyst" in kaizen_meta["role_skills"]

    # Verify upstream agent-team instructions and GECX pack delta were actually merged.
    em_agents = (out_dir / "templates" / "gecx-eng-manager" / "agents.md").read_text(encoding="utf-8")
    assert "Pack Override Rules" in em_agents
    assert "Upstream Role Instructions" in em_agents
    assert "Engineering Manager" in em_agents

    # Verify 11 Hub Skill Bank skills: 5 project-attached guardrails + 6 role-scoped skills (5 SEP + Kaizen Analyst).
    manifest_disk = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest_disk["skills"]) == 11
    attached = [s["name"] for s in manifest_disk["skills"] if s["attach_to_project"]]
    role_only = [s["name"] for s in manifest_disk["skills"] if not s["attach_to_project"]]
    assert len(attached) == 5
    assert set(role_only) == {
        "gcp-kaizen-analyst",
        "software-engineering-process",
        "agent-state-continuity",
        "artifact-durability",
        "code-review",
        "release-notes-daily",
    }
    for sk in manifest_disk["skills"]:
        assert (out_dir / "skills" / sk["name"] / "SKILL.md").exists()
    assert (
        out_dir / "skills" / "software-engineering-process" / "references" / "em-brief-template.md"
    ).exists()

    # Regression guard for live-discovered Scion v0.4 CLI/jq bugs in bootstrap-hub-project.sh.
    bootstrap_sh = (out_dir / "bootstrap" / "bootstrap-hub-project.sh").read_text(encoding="utf-8")
    assert "templates pull" in bootstrap_sh and "--to " in bootstrap_sh
    assert "templates pull \"$name\" --out" not in bootstrap_sh
    assert ".attach_to_project // true" not in bootstrap_sh


def test_adk_release_kit_is_offline_prefix_isolated_and_model_free(tmp_path: pathlib.Path) -> None:
    """Verifies packs/adk Release Kit builds 16 adk-* templates, 11 skills, and GE export tools."""
    out_dir = tmp_path / "adk-kit"
    manifest = build_release_kit(REPO_ROOT, REPO_ROOT / "packs/adk", out_dir)

    assert manifest["pack"] == "adk"
    assert manifest["pack_prefix"] == "adk"
    assert manifest["external_uris_remaining"] == 0
    assert manifest["toolchain_manifest"] == "packs/adk/toolchain-manifest.json"
    assert (out_dir / "packs" / "adk" / "scripts" / "ge_export.py").exists()
    assert (out_dir / "packs" / "adk" / "toolchain-manifest.json").exists()

    tpl_names = _assert_templates_follow_scion_v04_rules(out_dir, "adk", expected_count=16)
    assert {
        "adk-coordinator",
        "adk-eng-manager",
        "adk-deployer",
        "adk-eval-tester",
        "adk-kaizen-analyst",
    }.issubset(tpl_names)

    # Confirm adk-coordinator uses adk-* preamble and zero gecx-* prefix leaks.
    coord_agents = (out_dir / "templates" / "adk-coordinator" / "agents.md").read_text(encoding="utf-8")
    assert "`adk-*`" in coord_agents
    assert "`gecx-*`" not in coord_agents

    kaizen_meta = next(t for t in manifest["templates"] if t["name"] == "adk-kaizen-analyst")
    assert kaizen_meta["hub_role"] == "baseline"
    assert len(manifest["skills"]) == 11
    attached = {s["name"] for s in manifest["skills"] if s["attach_to_project"]}
    assert {"adk-domain-guardrails", "adk-ge-export-contract", "gcp-fde-guardrails"}.issubset(attached)
