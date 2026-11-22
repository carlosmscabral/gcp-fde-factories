"""Tests for repo-scaffold parity, Delta Watcher idempotency, CLI canary snapshot, and IAM policy guards."""
from __future__ import annotations

import importlib.util
import pathlib
import sys

from canaries.gecx.check_cli_contract import check_contract_snapshot

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load_watcher():
    """Dynamically imports scripts/delta-watcher/watcher.py (hyphenated parent dir)."""
    spec = importlib.util.spec_from_file_location(
        "delta_watcher", REPO_ROOT / "scripts/delta-watcher/watcher.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["delta_watcher"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_repo_scaffold_agents_claude_gemini_parity() -> None:
    """Confirms AGENTS.md, CLAUDE.md, and GEMINI.md are byte-identical in packs/gecx/repo-scaffold."""
    scaffold = REPO_ROOT / "packs/gecx/repo-scaffold"
    agents = (scaffold / "AGENTS.md").read_bytes()
    assert (scaffold / "CLAUDE.md").read_bytes() == agents
    assert (scaffold / "GEMINI.md").read_bytes() == agents


def test_cli_contract_snapshot_covers_all_required_cxas_1_11_flags() -> None:
    """Confirms the Spike-captured cxas 1.11.0 contract snapshot contains all required flags."""
    assert check_contract_snapshot(REPO_ROOT / "canaries/gecx/cxas_1.11.0_cli_contract.json") == []


def test_stage01_iam_contains_zero_predefined_ces_roles_or_wildcards() -> None:
    """Confirms deploy/01-landing-zone/iam.tf never grants predefined roles/ces.* or wildcard permissions."""
    iam_tf = (REPO_ROOT / "deploy/01-landing-zone/iam.tf").read_text(encoding="utf-8")
    code_only = "\n".join(line for line in iam_tf.splitlines() if not line.lstrip().startswith("#"))
    assert 'role    = "roles/ces.' not in code_only
    assert "ces.conversations." not in code_only
    assert "contactcenterinsights." not in code_only
    assert '".*"' not in code_only


def test_delta_watcher_wakes_only_on_changes() -> None:
    """Confirms Delta Watcher emits zero events when issue timestamps remain unchanged."""
    watcher = _load_watcher()
    items = [{"kind": "issue", "number": 7, "updated_at": "2026-11-22T20:00:00Z"}]
    deltas1, state1 = watcher.compute_deltas({}, items)
    assert len(deltas1) == 1
    deltas2, state2 = watcher.compute_deltas(state1, items)
    assert deltas2 == []
    assert state2 == state1
