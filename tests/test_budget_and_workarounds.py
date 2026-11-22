"""Tests for Layer 0+1+2 context budgeting, skill name collision detection, and 90-day TTL."""
from __future__ import annotations

import datetime as dt
import pathlib

import yaml

from scripts.lib.budget_engine import check_context_budget, check_workarounds_ttl

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_gecx_context_budget_and_workarounds_pass() -> None:
    """Confirms packs/gecx fits inside total Layers 0+1+2 limits and all workarounds are fresh."""
    errs, report = check_context_budget(
        REPO_ROOT,
        REPO_ROOT / "packs/gecx",
        REPO_ROOT / "packs/gecx/repo-scaffold/.factory/hub-project.yaml",
    )
    assert errs == []
    assert "gecx-deployer" in report["roles"]
    assert "gecx-eval-tester" in report["roles"]
    assert check_workarounds_ttl(REPO_ROOT / "WORKAROUNDS.yaml", today=dt.date(2026, 11, 22)) == []


def test_overlay_skill_name_collision_fails_closed(tmp_path: pathlib.Path) -> None:
    """Confirms customer overlay skills cannot collide with active pack skills unless excluded."""
    overlay = tmp_path / "hub-project.yaml"
    overlay.write_text(
        yaml.safe_dump({
            "schema_version": "1",
            "pack": "gecx",
            "pack_version": "0.1.0",
            "mode": "sandbox-direct",
            "diversity_profile": "cross-vendor",
            "limits": {"default_max_duration": "2h", "default_max_turns": 60, "auto_suspend_idle": True},
            "exclude_skills": [],
            "overlay_skills": [{"dir": "skills/gecx-foundry-adapter", "version": "1.0.0"}],
        })
    )
    errs, _ = check_context_budget(REPO_ROOT, REPO_ROOT / "packs/gecx", overlay)
    assert any("collides with active pack skill" in e for e in errs)


def test_expired_workaround_triggers_ttl_failure() -> None:
    """Confirms WORKAROUNDS.yaml entries older than 90 days fail CI."""
    errs = check_workarounds_ttl(REPO_ROOT / "WORKAROUNDS.yaml", today=dt.date(2027, 4, 1))
    assert len(errs) >= 1
    assert any("WK-001" in e for e in errs)
