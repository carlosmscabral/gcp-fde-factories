"""Tests for repo-scaffold parity, Delta Watcher idempotency, CLI canary snapshot, and IAM least-privilege guards."""
from __future__ import annotations

import importlib.util
import pathlib
import re
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


def test_stage01_iam_enforces_least_privilege_for_gecx_adk_and_kaizen() -> None:
    """Confirms deploy/01-landing-zone/iam.tf has zero wildcards, zero CES predefined roles, and strict ADK split-SA IAM."""
    iam_tf = (REPO_ROOT / "deploy/01-landing-zone/iam.tf").read_text(encoding="utf-8")
    code_only = "\n".join(line for line in iam_tf.splitlines() if not line.lstrip().startswith("#"))
    assert 'role    = "roles/ces.' not in code_only
    assert "ces.conversations." not in code_only
    assert "contactcenterinsights." not in code_only
    assert '".*"' not in code_only

    # ADK-03: sandbox_evaluator must use custom sandboxEvaluatorPredict role, NEVER roles/aiplatform.user.
    all_iam_blocks = re.findall(r'resource "google_project_iam_member" "[^"]+" \{[^}]+\}', code_only)
    eval_blocks = [blk for blk in all_iam_blocks if "sandbox_evaluator.email" in blk]
    assert eval_blocks
    assert all("roles/aiplatform.user" not in blk for blk in eval_blocks)
    assert "sandboxEvaluatorPredict" in code_only

    # ADK-17: adkSandboxDeployer custom role must NOT grant project-wide storage.objects.*.
    role_blocks = re.findall(r'resource "google_project_iam_custom_role" "[^"]+" \{[\s\S]+?\n\}', code_only)
    adk_dep_blocks = [blk for blk in role_blocks if 'role_id     = "adkSandboxDeployer"' in blk or '"adkSandboxDeployer"' in blk]
    assert len(adk_dep_blocks) == 1
    assert "storage.objects." not in adk_dep_blocks[0]

    # KZ-10: kaizen_viewer must be included in assignable_sa_map so Hub can impersonate it when enabled.
    assert "kaizen_viewer" in code_only


def test_delta_watcher_wakes_only_on_changes() -> None:
    """Confirms Delta Watcher emits zero events when issue timestamps remain unchanged."""
    watcher = _load_watcher()
    items = [{"kind": "issue", "number": 7, "updated_at": "2026-11-22T20:00:00Z"}]
    deltas1, state1 = watcher.compute_deltas({}, items)
    assert len(deltas1) == 1
    deltas2, state2 = watcher.compute_deltas(state1, items)
    assert deltas2 == []
    assert state2 == state1
