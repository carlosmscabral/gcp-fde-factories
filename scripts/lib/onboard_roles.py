"""Evidence-based Factory Pack recommender and SEP role curator (Wave 2 lean/full presets).

Defaults to the lean 5-role roster (coordinator, developer, code-reviewer, security-auditor,
test-engineer) backed by Kim et al. (arXiv:2512.08296) to cap error amplification and token
tax, while offering explicit opt-in to the full scion-frontiers/agent-team (SEP) roster for
complex multi-stream projects with clear PO tradeoffs and Day-2 upgradeability.
"""
from __future__ import annotations

from typing import Any

LEAN_CORE_ROLES: tuple[str, ...] = (
    "coordinator",
    "developer",
    "code-reviewer",
    "security-auditor",
    "test-engineer",
)

CORE_SEP_ROLES: tuple[str, ...] = (
    "coordinator",
    "eng-manager",
    "architect",
    "developer",
    "code-reviewer",
    "security-auditor",
    "kaizen-analyst",
)

FULL_ONLY_ROLES: tuple[tuple[str, str], ...] = (
    ("eng-manager", "Full agent-team preset: coordinates multi-stream worktrees and PR queues."),
    ("architect", "Full agent-team preset: produces design RFCs and architectural boundaries."),
    ("kaizen-analyst", "Full agent-team preset: runs scheduled closed-loop telemetry analysis."),
    ("investigator", "Full agent-team preset: deep root-cause triage for Chunky and Large issues."),
    ("doc-writer", "Full agent-team preset: maintains repository docs and ADRs without drift."),
    ("researcher", "Full agent-team preset: bounded external research and Kaizen skill discovery."),
    ("release-notes", "Full agent-team preset: generates daily and release changelogs from merged PRs."),
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

ROSTER_PRESET_TRADEOFFS: dict[str, str] = {
    "lean": (
        "Default 5-role roster (coordinator, developer, code-reviewer, security-auditor, test-engineer): "
        "fastest Day-0 setup, lowest token burn, and ~4.4x error cap. Upgrade to 'full' on Day 2 anytime."
    ),
    "full": (
        "Full scion-frontiers/agent-team SEP roster (adds eng-manager, architect, investigator, doc-writer, "
        "kaizen-analyst, qa-tester, web-builder, researcher, release-notes): suited for complex multi-stream "
        "projects; requires more setup/tuning time and carries higher token cost."
    ),
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
    roster_preset: str = "lean",
) -> dict[str, Any]:
    """Proposes enabled and disabled roles for either the lean (5-role) or full agent-team preset."""
    preset = roster_preset if roster_preset in ("lean", "full") else "lean"
    frontend = list(scan_facts.get("frontend_frameworks") or [])
    heavy_tests = list(scan_facts.get("heavy_test_binaries") or [])
    deploy_signals = list(scan_facts.get("deploy_signals") or [])
    effective_deploy = deploy_target or str(
        scan_facts.get("suggested_deploy_target") or ("none" if pack == "generic" else "cloud-run")
    )
    commands = scan_facts.get("commands") or {}

    enabled: list[dict[str, str]] = []
    disabled: list[dict[str, str]] = []

    deployer_role = PACK_DEPLOYER_ROLES.get(pack)
    eval_role = PACK_EVAL_ROLES.get(pack)

    if preset == "lean":
        for role in LEAN_CORE_ROLES:
            enabled.append({"role": role, "reason": "Lean 5-role backbone (coordinator, developer, review, security, test)."})
        # Only attach cloud deployer/eval roles in lean mode when sandbox-direct actually deploys a cloud target.
        if deployer_role:
            if mode == "ci-only":
                disabled.append({"role": deployer_role, "reason": "Execution mode is ci-only so CI owns deployments."})
            elif pack == "generic" and effective_deploy == "none":
                disabled.append({"role": deployer_role, "reason": "No cloud deployment target configured (deploy_target=none)."})
            else:
                detail = ", ".join(deploy_signals) if deploy_signals else effective_deploy
                enabled.append({"role": deployer_role, "reason": f"Sandbox deployment role for target ({detail})."})
        if eval_role:
            if mode == "ci-only":
                disabled.append({"role": eval_role, "reason": "Execution mode is ci-only so CI runs live evaluations."})
            else:
                enabled.append({"role": eval_role, "reason": f"Live Sandbox evaluation specialist for pack '{pack}'."})
        for role, _ in FULL_ONLY_ROLES:
            disabled.append({
                "role": role,
                "reason": "Deferred under lean preset (enable via roster.preset: full when project complexity warrants).",
            })
        for opt_role in ("web-builder", "qa-tester"):
            disabled.append({
                "role": opt_role,
                "reason": "Deferred under lean preset (developer and test-engineer cover UI/QA until preset: full).",
            })
    else:
        for role in CORE_SEP_ROLES:
            enabled.append({"role": role, "reason": "Core scion-frontiers/agent-team (SEP) and FDE governance backbone."})
        if frontend:
            enabled.append({"role": "web-builder", "reason": f"Detected frontend stack ({', '.join(frontend)})."})
        else:
            disabled.append({"role": "web-builder", "reason": "No frontend UI framework detected in repository."})
        if pack == "generic" or track == "complete" or heavy_tests or commands.get("e2e"):
            enabled.append({"role": "test-engineer", "reason": "Automated unit, integration, or E2E test engineering."})
        else:
            disabled.append({"role": "test-engineer", "reason": "Omitted without E2E test suite."})
        if effective_deploy != "none" or frontend or heavy_tests:
            enabled.append({"role": "qa-tester", "reason": f"Live verification enabled for deploy_target={effective_deploy}."})
        else:
            disabled.append({"role": "qa-tester", "reason": "Library or CLI target without deployed service or UI (deploy_target=none)."})
        if deployer_role:
            if mode == "ci-only":
                disabled.append({"role": deployer_role, "reason": "Execution mode is ci-only so CI pipelines own deployments."})
            elif pack == "generic" and effective_deploy == "none":
                disabled.append({"role": deployer_role, "reason": "No cloud deployment target configured (deploy_target=none)."})
            else:
                detail = ", ".join(deploy_signals) if deploy_signals else effective_deploy
                enabled.append({"role": deployer_role, "reason": f"Sandbox deployment role for target ({detail})."})
        if eval_role:
            if mode == "ci-only":
                disabled.append({"role": eval_role, "reason": "Execution mode is ci-only so CI runs live evaluations."})
            else:
                enabled.append({"role": eval_role, "reason": f"Live Sandbox evaluation specialist for pack '{pack}'."})
        for role, complete_reason in (
            ("investigator", "Root-cause investigation for Chunky and Large SEP issues."),
            ("doc-writer", "Maintains repository docs and ADRs without drift."),
            ("researcher", "Bounded external research and Kaizen Option A skill discovery."),
            ("release-notes", "Generates daily and release changelogs from merged PRs."),
        ):
            enabled.append({"role": role, "reason": complete_reason})

    reviewer_replicas = 2 if max_wip >= 4 else 1
    sizing_note = (
        f"max_wip={max_wip} >= 4: configure reviewer_replicas=2 so code review stays ahead of developers."
        if max_wip >= 4
        else f"max_wip={max_wip}: 1 code-reviewer replica is sufficient."
    )
    return {
        "pack": pack,
        "pack_prefix": PACK_PREFIXES.get(pack, pack),
        "preset": preset,
        "preset_tradeoff": ROSTER_PRESET_TRADEOFFS[preset],
        "enabled_roles": enabled,
        "disabled_roles": disabled,
        "max_wip": max_wip,
        "reviewer_replicas": reviewer_replicas,
        "sizing_note": sizing_note,
    }
