"""Zero-clobber Knowledge Plane planner/emitter and hardened kp-check validator (ADR-016).

Pre-validates all target paths against symlink escapes before emitting any file.
Preserves agent-maintained .factory/knowledge/* and .factory/waves/wave-1.yaml on re-emit
unless force_knowledge=True is passed, and enforces strict fail-closed link/REQ checks.
"""
from __future__ import annotations

import pathlib
import re
from typing import Any

import yaml

from scripts.lib.io_utils import assert_no_symlink_escape
from scripts.lib.onboard_roles import PACK_PREFIXES

VALID_SEP_SIZES = frozenset({"small", "chunky", "large"})
CANONICAL_KNOWLEDGE_FILES: tuple[str, ...] = (
    ".factory/knowledge/requirements.md",
    ".factory/knowledge/invariants.md",
    ".factory/knowledge/decisions/README.md",
    ".factory/knowledge/glossary.md",
    ".factory/waves/wave-1.yaml",
)


def _render_requirements_md(profile: dict[str, Any]) -> str:
    """Renders .factory/knowledge/requirements.md from PO-confirmed mission, non-goals, and REQ-NNN."""
    lines = [
        f"# Requirements and Scope (`{profile['slug']}`)",
        "",
        "## Mission",
        str(profile.get("mission") or "Confirm repository mission with the Product Owner."),
        "",
        "## Explicit Non-Goals",
    ]
    non_goals = profile.get("non_goals") or []
    lines.extend(f"- {ng}" for ng in non_goals) if non_goals else lines.append("- None recorded yet.")
    lines.extend(["", "## Functional Requirements"])
    reqs = profile.get("requirements") or []
    if not reqs:
        lines.append("- No REQ-NNN entries captured during Express onboarding. Add requirements before Wave-1.")
    for req in reqs:
        lines.append(f"### {req['id']}: {req['summary']}")
        for criterion in req.get("acceptance_criteria") or []:
            lines.append(f"- Acceptance criterion: {criterion}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_invariants_md(profile: dict[str, Any]) -> str:
    """Renders .factory/knowledge/invariants.md with verifiable guardrails and sandbox blind spots."""
    lines = [
        f"# Verifiable Invariants (`{profile['slug']}`)",
        "",
        "Code reviewers and security auditors enforce every rule below on every pull request.",
        "",
        "## Hard Invariants",
    ]
    invs = profile.get("invariants") or []
    lines.extend(f"- {inv}" for inv in invs) if invs else lines.append("- Follow pack security and test gates.")
    blindspots = profile.get("not_verifiable_in_sandbox") or []
    if blindspots:
        lines.extend(["", "## Not Verifiable in Sandbox (Human Verification Required)"])
        lines.extend(f"- {item}" for item in blindspots)
    return "\n".join(lines).rstrip() + "\n"


def _render_decisions_readme(profile: dict[str, Any]) -> str:
    """Renders .factory/knowledge/decisions/README.md linking in-place ADRs and new decisions."""
    lines = [f"# Architecture Decisions Index (`{profile['slug']}`)", "", "## Pre-Existing Repository Decision Documents"]
    existing_adrs = [
        s for s in (profile.get("knowledge_sources") or [])
        if "adr" in s.lower() or "rfc" in s.lower() or "architecture" in s.lower()
    ]
    if existing_adrs:
        lines.extend(f"- `{src}` (in-place source of truth)" for src in existing_adrs)
    else:
        lines.append("- None detected during Day-0 scan.")

    lines.extend(["", "## Decisions Captured During Onboarding"])
    decisions = profile.get("decisions") or []
    if decisions:
        for dec in decisions:
            lines.append(f"- **{dec['id']} ({dec.get('status', 'accepted')}) — {dec['title']}:** {dec['decision']}")
    else:
        lines.append("- Add new ADRs here using `ADR-NNN-<slug>.md` without duplicating legacy docs.")
    return "\n".join(lines).rstrip() + "\n"


def _render_glossary_md(profile: dict[str, Any]) -> str:
    """Renders .factory/knowledge/glossary.md with canonical domain terms."""
    lines = [f"# Domain Glossary (`{profile['slug']}`)", ""]
    entries = profile.get("glossary") or []
    if entries:
        for item in entries:
            lines.append(f"- **{item['term']}:** {item['definition']}")
    else:
        lines.append("- Add canonical customer terms here so all agents use one name per concept.")
    return "\n".join(lines).rstrip() + "\n"


def _render_wave1_yaml(profile: dict[str, Any]) -> str:
    """Renders .factory/waves/wave-1.yaml seeded from profile.waves or REQ-NNN defaults."""
    tasks = list(profile.get("waves") or [])
    if not tasks:
        for idx, req in enumerate((profile.get("requirements") or [])[:5], 1):
            tasks.append({
                "id": f"W1-{idx:02d}",
                "title": req["summary"][:100],
                "req_ids": [req["id"]],
                "size": "small",
                "owner_role": "developer",
                "status": "pending",
                "acceptance_criteria": list(req.get("acceptance_criteria") or []),
            })
    payload = {
        "schema_version": "1",
        "wave": "wave-1",
        "slug": profile["slug"],
        "work_tracker": "github-issues" if profile["git_flow"]["ci_platform"] == "github-actions" else "local-waves-yaml",
        "tasks": tasks,
    }
    return yaml.safe_dump(payload, sort_keys=False)


def _render_coordinator_brief(profile: dict[str, Any], coordinator_name: str) -> str:
    """Renders the PO-gated standby bootstrap brief passed to scion start --task-file."""
    pack = str(profile["pack"])
    prefix = PACK_PREFIXES.get(pack, pack)
    monorepo = profile.get("monorepo") if isinstance(profile.get("monorepo"), dict) else {}
    mono_enabled = bool(monorepo.get("enabled"))
    subdir = str(monorepo.get("subdir") or "").strip() if mono_enabled else ""
    agent_prefix = str(monorepo.get("agent_prefix") or prefix) if mono_enabled else prefix
    roster = profile.get("roster") or {}
    enabled = roster.get("enabled_roles") or []
    disabled = [d["role"] if isinstance(d, dict) else str(d) for d in (roster.get("disabled_roles") or [])]
    replicas = int(roster.get("reviewer_replicas") or 1)
    ci_platform = str(profile["git_flow"]["ci_platform"])

    tracker_rule = (
        "Use GitHub Issues synced with `.factory/waves/wave-1.yaml` as the seed backlog."
        if ci_platform == "github-actions"
        else "Repository does not use GitHub Actions. Treat `.factory/waves/wave-1.yaml` as the seed queue, track live worker state in Scion notifications and `/scion-volumes/scratchpad/wave-state.jsonl`, and update `wave-1.yaml` only from the Coordinator via a dedicated PR."
    )
    scope_line = (
        f"- Monorepo scope: `{subdir}` (name child agents `{agent_prefix}-<role>` so sibling monorepo factories do not collide)."
        if subdir
        else f"- Repository scope: full repository root (name child agents `{agent_prefix}-<role>`)."
    )
    lines = [
        f"# Coordinator Day-0 Standby Bootstrap Brief (`{coordinator_name}`)",
        "",
        "## 1. Identity and Strict Standby Gate",
        f"- Active pack: `{pack}@{profile['pack_version']}` (template prefix `{prefix}-*`).",
        f"- Autonomy mode: `{profile['autonomy']}` | Diversity profile: `{profile['diversity_profile']}` | Deploy target: `{profile.get('deploy_target', 'default')}`.",
        scope_line,
        f"- Enabled roles: `{', '.join(enabled) if enabled else 'all pack defaults'}`.",
        f"- Disabled roles (do not spawn): `{', '.join(disabled) if disabled else 'none'}`.",
        f"- Reviewer concurrency: `{replicas}` replica(s).",
        "",
        "## 2. First-Turn Actions (Read-Only Standby)",
        "1. Read `.factory/hub-project.yaml`, `.factory/knowledge-index.yaml`, `.factory/knowledge/requirements.md`, `.factory/knowledge/invariants.md`, and `.factory/waves/wave-1.yaml`.",
        f"2. {tracker_rule}",
        "3. Post a concise Wave-1 readiness summary in Scion Chat listing the detected tasks, enabled specialist roster, and any open modernization gaps from `.factory/modernization-backlog.yaml`.",
        "4. Do NOT spawn developers, modify code, or open pull requests yet. Run `sciontool status blocked` and wait for explicit Product Owner confirmation before launching Wave-1 execution.",
    ]
    return "\n".join(lines) + "\n"


def plan_knowledge_plane(
    repo: pathlib.Path,
    profile: dict[str, Any],
    coordinator_name: str,
    *,
    force_knowledge: bool = False,
) -> dict[str, Any]:
    """Pre-validates symlink safety and computes Knowledge Plane file payloads without touching disk."""
    planned_writes: list[tuple[pathlib.Path, bytes, str]] = []
    preserved: list[str] = []

    editable_targets = (
        (".factory/knowledge/requirements.md", _render_requirements_md(profile)),
        (".factory/knowledge/invariants.md", _render_invariants_md(profile)),
        (".factory/knowledge/decisions/README.md", _render_decisions_readme(profile)),
        (".factory/knowledge/glossary.md", _render_glossary_md(profile)),
        (".factory/waves/wave-1.yaml", _render_wave1_yaml(profile)),
    )
    for rel, content in editable_targets:
        path = assert_no_symlink_escape(repo, repo / rel)
        if path.exists() and not force_knowledge:
            preserved.append(rel)
        else:
            planned_writes.append((path, content.encode("utf-8"), rel))

    brief_rel = ".factory/coordinator-bootstrap-brief.md"
    brief_path = assert_no_symlink_escape(repo, repo / brief_rel)
    planned_writes.append((brief_path, _render_coordinator_brief(profile, coordinator_name).encode("utf-8"), brief_rel))

    return {
        "writes": planned_writes,
        "preserved": preserved,
        "knowledge_files": list(CANONICAL_KNOWLEDGE_FILES),
    }


def check_knowledge_plane(repo_dir: pathlib.Path) -> dict[str, Any]:
    """Fail-closed validation of Knowledge Plane links, canonical files, REQ-NNN traceability, and Wave-1."""
    repo = repo_dir.resolve()
    errors: list[str] = []
    warnings: list[str] = []
    checked_files: list[str] = []

    idx_path = repo / ".factory" / "knowledge-index.yaml"
    if not idx_path.is_file():
        return {"ok": False, "errors": ["Missing .factory/knowledge-index.yaml."], "warnings": [], "checked_files": []}

    idx = yaml.safe_load(idx_path.read_text(encoding="utf-8"))
    if not isinstance(idx, dict):
        return {"ok": False, "errors": [".factory/knowledge-index.yaml must contain a YAML mapping."], "warnings": [], "checked_files": []}

    listed_kp = [str(p) for p in (idx.get("knowledge_files") or [])]
    for canonical in CANONICAL_KNOWLEDGE_FILES:
        if canonical not in listed_kp:
            errors.append(f"knowledge-index.yaml missing canonical knowledge_files entry '{canonical}'.")

    for field in ("sources", "knowledge_files"):
        for rel in idx.get(field) or []:
            rel_s = str(rel)
            try:
                target = assert_no_symlink_escape(repo, repo / rel_s)
            except ValueError as exc:
                errors.append(str(exc))
                continue
            if not target.exists():
                errors.append(f"Broken link in knowledge-index.yaml ({field}): '{rel_s}' does not exist.")
            else:
                checked_files.append(rel_s)

    raw_reqs = idx.get("requirements") or []
    req_ids: set[str] = set()
    for item in raw_reqs:
        if not isinstance(item, dict) or not item.get("id"):
            errors.append(f"Invalid requirement entry in knowledge-index.yaml (expected object with 'id'): {item!r}")
        else:
            req_ids.add(str(item["id"]))

    req_md = repo / ".factory" / "knowledge" / "requirements.md"
    if req_ids and req_md.is_file():
        req_text = req_md.read_text(encoding="utf-8", errors="ignore")
        for rid in sorted(req_ids):
            if not re.search(rf"\b{re.escape(rid)}\b", req_text):
                errors.append(f"Requirement '{rid}' is declared in knowledge-index.yaml but missing from .factory/knowledge/requirements.md.")

    wave_path = repo / ".factory" / "waves" / "wave-1.yaml"
    if wave_path.is_file():
        wave = yaml.safe_load(wave_path.read_text(encoding="utf-8"))
        if not isinstance(wave, dict) or not isinstance(wave.get("tasks"), list):
            errors.append(".factory/waves/wave-1.yaml must contain a mapping with a 'tasks' list.")
        else:
            seen_task_ids: set[str] = set()
            for task in wave["tasks"]:
                if not isinstance(task, dict) or not task.get("id") or not task.get("title"):
                    errors.append("Every task in .factory/waves/wave-1.yaml requires 'id' and 'title'.")
                    continue
                tid = str(task["id"])
                if tid in seen_task_ids:
                    errors.append(f"Duplicate task ID '{tid}' in .factory/waves/wave-1.yaml.")
                seen_task_ids.add(tid)
                size = str(task.get("size") or "small")
                if size not in VALID_SEP_SIZES:
                    errors.append(f"Wave task '{tid}' has invalid SEP size '{size}' (expected small, chunky, or large).")
                for ref_id in task.get("req_ids") or []:
                    ref_s = str(ref_id)
                    if ref_s not in req_ids:
                        errors.append(f"Wave task '{tid}' references unknown requirement ID '{ref_s}'.")

    agents_md = repo / "AGENTS.md"
    if not agents_md.is_file():
        errors.append("Missing AGENTS.md in repository root.")
    else:
        agents_text = agents_md.read_text(encoding="utf-8", errors="ignore")
        if ".factory/knowledge-index.yaml" not in agents_text:
            errors.append("AGENTS.md does not reference .factory/knowledge-index.yaml.")
        if wave_path.is_file() and ".factory/waves/wave-1.yaml" not in agents_text:
            warnings.append("AGENTS.md does not reference .factory/waves/wave-1.yaml.")

    return {"ok": len(errors) == 0, "errors": errors, "warnings": warnings, "checked_files": sorted(set(checked_files))}
