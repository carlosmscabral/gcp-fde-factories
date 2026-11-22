"""Total context budget, skill collision detector, lockfile digest verifier, and TTL gate.

Enforces four invariants:
1. Total lines per role across vendored upstream template + role skills + project-attached skills + delta
   stay below pack.yaml context_budget.max_total_lines_per_role.
2. Authored pack/core skills stay <= max_lines_per_pack_skill, vendored upstream skills match skills.lock
   SHA-256 digests, and directory basenames match skill names for scion skills publish.
3. No two skills share a colliding name across pack, vendored, or customer overlay skills.
4. No WORKAROUNDS.yaml entry exceeds max_age_days (90 days) without explicit review.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import re
from typing import Any

from scripts.lib.io_utils import load_yaml, sha256_file

NUMBERED_RULE_RE = re.compile(r"^\s*\d+\.\s+")


def count_lines(path: pathlib.Path) -> int:
    """Returns the line count of a UTF-8 text file."""
    return len(path.read_text(encoding="utf-8").splitlines())


def count_delta_rules(delta_md: pathlib.Path) -> int:
    """Counts numbered normative rules in a specialist delta.md file."""
    return sum(1 for line in delta_md.read_text(encoding="utf-8").splitlines() if NUMBERED_RULE_RE.match(line))


def _upstream_template_lines(repo_root: pathlib.Path, base_role: str) -> int:
    """Counts lines in vendored upstream agents.md and system-prompt.md when present."""
    tpl_dir = repo_root / "vendor" / "agent-team" / "templates" / base_role
    if not tpl_dir.is_dir():
        return 0
    total = 0
    for fname in ("agents.md", "system-prompt.md"):
        fpath = tpl_dir / fname
        if fpath.exists():
            total += count_lines(fpath)
    return total


def check_context_budget(
    repo_root: pathlib.Path,
    pack_dir: pathlib.Path,
    overlay_hub_project: pathlib.Path | None = None,
) -> tuple[list[str], dict[str, Any]]:
    """Checks total context budgets across Layers 0+1+2, verifies vendored digests, and detects collisions."""
    errors: list[str] = []
    pack_cfg = load_yaml(pack_dir / "pack.yaml")
    lock_cfg = load_yaml(repo_root / pack_cfg["upstream"]["skills_lock"])

    budget = pack_cfg["context_budget"]
    max_role_lines = int(budget["max_total_lines_per_role"])
    max_skill_lines = int(budget["max_lines_per_pack_skill"])
    max_delta_rules = int(budget["max_delta_rules"])

    layer0_fallback: dict[str, int] = {k: int(v) for k, v in lock_cfg.get("layer0_baseline_lines", {}).items()}
    lock_sha_by_name: dict[str, str] = {
        str(entry["name"]): str(entry["sha256"]) for entry in lock_cfg.get("skills", [])
    }

    # Validate skill basenames, authored line budgets, and vendored SHA-256 integrity.
    seen_skills: set[str] = set()
    attached_skill_lines = 0
    skill_lines_by_name: dict[str, int] = {}

    for item in pack_cfg.get("project_skills", []):
        name = str(item["name"])
        local_rel = str(item["local_dir"])
        local_dir = repo_root / local_rel
        skill_md = local_dir / "SKILL.md"
        attach_to_project = bool(item.get("attach_to_project", True))

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
        skill_lines_by_name[name] = lines
        if attach_to_project:
            attached_skill_lines += lines

        if local_rel.startswith("vendor/"):
            expected_sha = lock_sha_by_name.get(name)
            if not expected_sha:
                errors.append(f"Vendored skill '{name}' is missing an entry in skills.lock.")
            else:
                actual_sha = sha256_file(skill_md)
                if actual_sha != expected_sha:
                    errors.append(
                        f"Vendored skill '{name}' SHA-256 mismatch: got {actual_sha}, expected {expected_sha}."
                    )
        elif lines > max_skill_lines:
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

    # Measure total context per specialist role across vendored base + role skills + project skills + delta.
    role_report: dict[str, dict[str, int]] = {}
    for tpl in pack_cfg.get("specialist_templates", []):
        role_name = str(tpl["name"])
        base_role = str(tpl["base_role"])
        delta_dir_rel = tpl.get("delta_dir")

        delta_lines = 0
        delta_rules = 0
        if delta_dir_rel:
            delta_md = pack_dir / str(delta_dir_rel) / "delta.md"
            if not delta_md.exists():
                errors.append(f"Missing specialist delta file: {delta_md}.")
                continue
            delta_lines = count_lines(delta_md)
            delta_rules = count_delta_rules(delta_md)
            if delta_rules > max_delta_rules:
                errors.append(
                    f"Specialist '{role_name}' defines {delta_rules} rules, exceeding max_delta_rules ({max_delta_rules})."
                )

        role_skills_lines = 0
        for rskill in tpl.get("role_skills", []):
            if rskill not in skill_lines_by_name:
                errors.append(f"Specialist '{role_name}' references unknown role_skill '{rskill}'.")
                continue
            role_skills_lines += skill_lines_by_name[rskill]

        base_lines = _upstream_template_lines(repo_root, base_role)
        if base_lines == 0:
            base_lines = layer0_fallback.get(base_role, 200)

        total = base_lines + role_skills_lines + attached_skill_lines + delta_lines
        role_report[role_name] = {
            "upstream_template_lines": base_lines,
            "role_skills_lines": role_skills_lines,
            "project_skills_lines": attached_skill_lines,
            "delta_lines": delta_lines,
            "delta_rules": delta_rules,
            "total_lines": total,
        }
        if total > max_role_lines:
            errors.append(
                f"Specialist '{role_name}' totals {total} lines (Layers 0+1+2), exceeding max_total_lines_per_role ({max_role_lines})."
            )

    return errors, {"skills": skill_lines_by_name, "roles": role_report}


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
