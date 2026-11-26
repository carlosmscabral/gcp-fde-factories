"""Evidence-based Factory Pack recommender and SEP role curator (ADR-016).

Maps static repository discovery facts to Preston agent-team (SEP) roles and FDE specialists.
Records explicit reasons for every disabled specialist so Stage 03 syncs a clean Hub roster.
"""
from __future__ import annotations

from typing import Any

CORE_SEP_ROLES: tuple[str, ...] = (
    "coordinator",
    "eng-manager",
    "architect",
    "developer",
    "code-reviewer",
    "security-auditor",
    "kaizen-analyst",
)

PACK_DEPLOYER_ROLES: dict[str, str] = {
    "adk": "adk-deployer",
    "gecx": "gecx-deployer",
    "generic": "generic-deployer",
}

PACK_EVAL_ROLES: dict[str, str] = {
    "adk": "adk-eval-tester",
    "gecx": "gecx-eval-tester",
}

PACK_PREFIXES: dict[str, str] = {
    "adk": "adk",
    "gecx": "gecx",
    "generic": "sw",
}

PACK_DEFAULT_VERSIONS: dict[str, str] = {
    "adk": "0.5.0",
    "gecx": "0.5.0",
    "generic": "0.6.0",
}


def recommend_pack(scan_facts: dict[str, Any]) -> dict[str, str]:
    """Recommends adk, gecx, or generic based on detected manifests and stacks."""
    stacks = set(scan_facts.get("stacks") or [])
    if "adk" in stacks:
        return {
            "pack": "adk",
            "prefix": PACK_PREFIXES["adk"],
            "reason": "Detected Google ADK dependencies or agents-cli / Gemini Enterprise manifests.",
        }
    if "gecx" in stacks:
        return {
            "pack": "gecx",
            "prefix": PACK_PREFIXES["gecx"],
            "reason": "Detected CES / GECX app directory or cxas dependency.",
        }
    return {
        "pack": "generic",
        "prefix": PACK_PREFIXES["generic"],
        "reason": "No ADK or GECX manifests detected. Recommended generic software factory (sw-*).",
    }


def propose_roles(
    scan_facts: dict[str, Any],
    pack: str,
    deploy_target: str | None = None,
    mode: str = "sandbox-direct",
    track: str = "complete",
    max_wip: int = 3,
) -> dict[str, Any]:
    """Proposes enabled and disabled SEP specialist roles with concrete repository evidence."""
    enabled: list[dict[str, str]] = [
        {"role": role, "reason": "Core scion-frontiers/agent-team (SEP) and FDE governance backbone."}
        for role in CORE_SEP_ROLES
    ]
    disabled: list[dict[str, str]] = []

    frontend = list(scan_facts.get("frontend_frameworks") or [])
    heavy_tests = list(scan_facts.get("heavy_test_binaries") or [])
    deploy_signals = list(scan_facts.get("deploy_signals") or [])
    effective_deploy = deploy_target or str(scan_facts.get("suggested_deploy_target") or ("none" if pack == "generic" else "cloud-run"))
    commands = scan_facts.get("commands") or {}

    if frontend:
        enabled.append({"role": "web-builder", "reason": f"Detected frontend stack ({', '.join(frontend)})."})
    else:
        disabled.append({"role": "web-builder", "reason": "No frontend UI framework detected in repository."})

    if pack == "generic" or track == "complete" or heavy_tests or commands.get("e2e"):
        enabled.append({"role": "test-engineer", "reason": "Automated unit, integration, or E2E test engineering."})
    else:
        disabled.append({"role": "test-engineer", "reason": "Omitted on express track without E2E test suite."})

    if effective_deploy != "none" or frontend or heavy_tests:
        enabled.append({"role": "qa-tester", "reason": f"Live verification enabled for deploy_target={effective_deploy}."})
    else:
        disabled.append({"role": "qa-tester", "reason": "Library or CLI target without deployed service or UI (deploy_target=none)."})

    deployer_role = PACK_DEPLOYER_ROLES.get(pack)
    if deployer_role:
        if mode == "ci-only":
            disabled.append({"role": deployer_role, "reason": "Execution mode is ci-only so CI pipelines own deployments."})
        elif pack == "generic" and effective_deploy == "none":
            disabled.append({"role": deployer_role, "reason": "No cloud deployment target configured (deploy_target=none)."})
        else:
            detail = ", ".join(deploy_signals) if deploy_signals else effective_deploy
            enabled.append({"role": deployer_role, "reason": f"Sandbox deployment role for target ({detail})."})

    eval_role = PACK_EVAL_ROLES.get(pack)
    if eval_role:
        if mode == "ci-only":
            disabled.append({"role": eval_role, "reason": "Execution mode is ci-only so CI runs live evaluations."})
        else:
            enabled.append({"role": eval_role, "reason": f"Live Sandbox evaluation specialist for pack '{pack}'."})

    for role, complete_reason in (
        ("investigator", "Root-cause investigation for Chunky and Large SEP issues."),
        ("doc-writer", "Maintains .factory/knowledge/ and repository docs without drift."),
        ("researcher", "Bounded external research and Kaizen Option A skill discovery."),
        ("release-notes", "Generates daily and release changelogs from merged PRs."),
    ):
        if track == "complete" or role in ("investigator", "doc-writer"):
            enabled.append({"role": role, "reason": complete_reason})
        else:
            disabled.append({"role": role, "reason": "Optional on express track. Enable when continuous research or release notes are needed."})

    reviewer_replicas = 2 if max_wip >= 4 else 1
    sizing_note = (
        f"max_wip={max_wip} >= 4: configure reviewer_replicas=2 so code review stays ahead of developers."
        if max_wip >= 4
        else f"max_wip={max_wip}: 1 code-reviewer replica is sufficient."
    )
    return {
        "pack": pack,
        "pack_prefix": PACK_PREFIXES.get(pack, pack),
        "enabled_roles": enabled,
        "disabled_roles": disabled,
        "max_wip": max_wip,
        "reviewer_replicas": reviewer_replicas,
        "sizing_note": sizing_note,
    }
