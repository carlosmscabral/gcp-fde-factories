"""Total context budget, skill collision detector, and WORKAROUNDS.yaml 90-day TTL gate.

Enforces three invariants:
1. Total lines per role across Layer 0 (agent-team) + Layer 1 (core skills) + Layer 2 (pack skills + delta)
   stay below pack.yaml context_budget.max_total_lines_per_role.
2. Pack skill files stay <= max_lines_per_pack_skill, directory basename matches skill name,
   and no two skills share a colliding name across project, pack, or customer overlay.
3. No WORKAROUNDS.yaml entry exceeds max_age_days (90 days) without explicit review.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import re
from typing import Any

from scripts.lib.io_utils import load_yaml

NUMBERED_RULE_RE = re.compile(r"^\s*\d+\.\s+")


def count_lines(path: pathlib.Path) -> int:
    """Returns the line count of a UTF-8 text file."""
    return len(path.read_text(encoding="utf-8").splitlines())


def count_delta_rules(delta_md: pathlib.Path) -> int:
    """Counts numbered normative rules in a specialist delta.md file."""
    return sum(1 for line in delta_md.read_text(encoding="utf-8").splitlines() if NUMBERED_RULE_RE.match(line))


def check_context_budget(
    repo_root: pathlib.Path,
    pack_dir: pathlib.Path,
    overlay_hub_project: pathlib.Path | None = None,
) -> tuple[list[str], dict[str, Any]]:
    """Checks total context budgets across Layers 0+1+2 and detects skill name collisions."""
    errors: list[str] = []
    pack_cfg = load_yaml(pack_dir / "pack.yaml")
    lock_cfg = load_yaml(repo_root / pack_cfg["upstream"]["skills_lock"])

    budget = pack_cfg["context_budget"]
    max_role_lines = int(budget["max_total_lines_per_role"])
    max_skill_lines = int(budget["max_lines_per_pack_skill"])
    max_delta_rules = int(budget["max_delta_rules"])

    layer0_map: dict[str, int] = {k: int(v) for k, v in lock_cfg.get("layer0_baseline_lines", {}).items()}

    # Validate project_skills names, directory basenames (Scion v0.4 Skill Bank rule), and line limits.
    seen_skills: set[str] = set()
    shared_skill_lines = 0
    skill_report: dict[str, int] = {}

    for item in pack_cfg.get("project_skills", []):
        name = str(item["name"])
        local_dir = repo_root / item["local_dir"]
        skill_md = local_dir / "SKILL.md"

        if name in seen_skills:
            errors.append(f"Duplicate skill name in pack project_skills: '{name}'.")
        seen_skills.add(name)

        if local_dir.name != name:
            errors.append(
                f"Skill directory basename '{local_dir.name}' must match skill name '{name}' for scion skills publish."
            )
        if not skill_md.exists():
            errors.append(f"Missing SKILL.md for skill '{name}' at {skill_md}.")
            continue

        lines = count_lines(skill_md)
        skill_report[name] = lines
        shared_skill_lines += lines
        if lines > max_skill_lines:
            errors.append(f"Skill '{name}' has {lines} lines, exceeding max_lines_per_pack_skill ({max_skill_lines}).")

    # Detect collisions between pack skills and optional customer overlay skills.
    if overlay_hub_project and overlay_hub_project.exists():
        ov_cfg = load_yaml(overlay_hub_project)
        excluded = set(ov_cfg.get("exclude_skills", []))
        active_pack_skills = seen_skills - excluded
        for ov in ov_cfg.get("overlay_skills", []):
            ov_name = pathlib.Path(ov["dir"]).name
            if ov_name in active_pack_skills:
                errors.append(
                    f"Overlay skill '{ov_name}' collides with active pack skill. Add '{ov_name}' to exclude_skills or rename it."
                )

    # Measure total context per specialist role across Layers 0 + 1 + 2.
    role_report: dict[str, dict[str, int]] = {}
    for tpl in pack_cfg.get("specialist_templates", []):
        role_name = str(tpl["name"])
        base_role = str(tpl["base_role"])
        delta_md = pack_dir / tpl["delta_dir"] / "delta.md"
        if not delta_md.exists():
            errors.append(f"Missing specialist delta file: {delta_md}.")
            continue

        delta_lines = count_lines(delta_md)
        delta_rules = count_delta_rules(delta_md)
        l0 = layer0_map.get(base_role, 200)
        total = l0 + shared_skill_lines + delta_lines
        role_report[role_name] = {
            "layer0_lines": l0,
            "shared_skills_lines": shared_skill_lines,
            "delta_lines": delta_lines,
            "delta_rules": delta_rules,
            "total_lines": total,
        }
        if delta_rules > max_delta_rules:
            errors.append(f"Specialist '{role_name}' defines {delta_rules} rules, exceeding max_delta_rules ({max_delta_rules}).")
        if total > max_role_lines:
            errors.append(
                f"Specialist '{role_name}' totals {total} lines (Layers 0+1+2), exceeding max_total_lines_per_role ({max_role_lines})."
            )

    return errors, {"skills": skill_report, "roles": role_report}


def check_workarounds_ttl(
    workarounds_path: pathlib.Path, today: dt.date | None = None
) -> list[str]:
    """Fails if any entry in WORKAROUNDS.yaml is older than max_age_days or past expires_date."""
    errors: list[str] = []
    ref_day = today or dt.date.today()
    cfg = load_yaml(workarounds_path)
    max_age = int(cfg.get("max_age_days", 90))

    for item in cfg.get("workarounds", []):
        wid = str(item.get("id", "unknown"))
        added = dt.date.fromisoformat(str(item["added_date"]))
        expires = dt.date.fromisoformat(str(item["expires_date"]))
        age_days = (ref_day - added).days
        if age_days > max_age or ref_day > expires:
            errors.append(
                f"Workaround {wid} ({item.get('component')}) expired (age={age_days}d, expires={expires}). Run removal_test and compact."
            )
    return errors
