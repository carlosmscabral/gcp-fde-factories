"""Deterministic Readiness Gate, conditional Dockerfile generator, and Layer 3 overlay emitter (v0.4.0).

Implements Adopt-First, Evolve-Gradually brownfield onboarding without touching Layers 0-2:
- Validates PO-confirmed profiles against schemas/factory-profile.schema.json and track rules.
- Preserves existing AGENTS.md, CLAUDE.md, and .cursorrules via delimited idempotent block merge.
- Emits .factory/Dockerfile.customer only when missing_binaries is non-empty (always USER scion UID 1000).
- Generates skills/<slug>-repo-conventions/SKILL.md with public source citations.
"""
from __future__ import annotations

import pathlib
from typing import Any

import yaml

from scripts.lib.schema_validator import validate_against_schema

START_MARKER = "<!-- gcp-fde-factory:start -->"
END_MARKER = "<!-- gcp-fde-factory:end -->"

INSTALL_RECIPES: dict[str, tuple[str, str]] = {
    "poetry": ("uv pip install --system --no-cache poetry==2.1.1", "poetry --version"),
    "ruff": ("uv pip install --system --no-cache ruff==0.9.9", "ruff --version"),
    "mypy": ("uv pip install --system --no-cache mypy==1.15.0", "mypy --version"),
    "node": ("apt-get update && apt-get install -y --no-install-recommends nodejs npm && rm -rf /var/lib/apt/lists/*", "node --version"),
    "npm": ("true", "npm --version"),
    "pnpm": ("npm install -g pnpm@10.6.0", "pnpm --version"),
    "eslint": ("npm install -g eslint@9.22.0", "eslint --version"),
    "playwright": ("uv pip install --system --no-cache playwright==1.50.0 && playwright install --with-deps chromium", "playwright --version"),
    "go": ("apt-get update && apt-get install -y --no-install-recommends golang-go && rm -rf /var/lib/apt/lists/*", "go version"),
    "terraform": ("echo 'Install pinned Terraform binary via internal mirror' && exit 0", "true"),
    "tflint": ("echo 'Install pinned tflint binary via internal mirror' && exit 0", "true"),
    "jdk": ("apt-get update && apt-get install -y --no-install-recommends default-jdk-headless && rm -rf /var/lib/apt/lists/*", "java -version"),
    "mvn": ("apt-get update && apt-get install -y --no-install-recommends maven && rm -rf /var/lib/apt/lists/*", "mvn --version"),
}


def check_readiness(profile: dict[str, Any], schema_path: pathlib.Path) -> dict[str, Any]:
    """Evaluates whether an onboarding profile passes the deterministic Readiness Gate."""
    issues = validate_against_schema(profile, schema_path)

    if not issues:
        cmds = profile.get("commands", {})
        if "configure lint command" in str(cmds.get("lint", "")):
            issues.append("commands.lint still contains the placeholder value; confirm the real lint command.")

        if profile.get("track") == "complete":
            if not str(profile.get("mission", "")).strip():
                issues.append("Complete track requires a non-empty 'mission' confirmed by the PO.")
            if not profile.get("non_goals"):
                issues.append("Complete track requires at least one entry in 'non_goals'.")
            if not profile.get("requirements"):
                issues.append("Complete track requires at least one REQ-NNN entry in 'requirements'.")
            if not profile.get("invariants"):
                issues.append("Complete track requires at least one verifiable entry in 'invariants'.")
            if not profile.get("evaluation_pyramid"):
                issues.append("Complete track requires 'evaluation_pyramid' targets.")

    return {"ready": len(issues) == 0, "missing_or_weak": issues}


def merge_delimited_agents_md(agents_md_path: pathlib.Path, block_body: str) -> str:
    """Inserts or updates the factory block in AGENTS.md without overwriting customer prose."""
    wrapped = f"{START_MARKER}\n{block_body.strip()}\n{END_MARKER}\n"
    if not agents_md_path.exists():
        agents_md_path.write_text(wrapped, encoding="utf-8")
        return wrapped

    existing = agents_md_path.read_text(encoding="utf-8")
    if START_MARKER in existing and END_MARKER in existing:
        before, rest = existing.split(START_MARKER, 1)
        _, after = rest.split(END_MARKER, 1)
        merged = before.rstrip() + ("\n\n" if before.strip() else "") + wrapped + after.lstrip("\n")
    else:
        sep = "\n\n" if existing.strip() else ""
        merged = existing.rstrip() + sep + wrapped

    agents_md_path.write_text(merged, encoding="utf-8")
    return merged


def render_conditional_dockerfile(
    pack_image_ref: str,
    missing_binaries: list[str],
    tester_only: bool = False,
) -> str | None:
    """Renders a derived Layer 3 Dockerfile when missing_binaries is non-empty."""
    ordered = [b for b in missing_binaries if b]
    if not ordered:
        return None

    role_note = "test-engineer and qa-tester roles only" if tester_only else "project default harnesses"
    install_lines: list[str] = []
    smoke_checks: list[str] = []
    for binary in ordered:
        install_cmd, check_cmd = INSTALL_RECIPES.get(
            binary,
            (f"echo 'Install pinned {binary} package before production use'", "true"),
        )
        install_lines.append(f"RUN {install_cmd}")
        if check_cmd != "true":
            smoke_checks.append(check_cmd)

    smoke_line = " && ".join(smoke_checks) if smoke_checks else "true"
    lines = [
        f"# Conditional Layer 3 derived customer image ({role_note}).",
        "# Inherits upstream Scion sciontool, Chainguard git, and pack toolchain without forking Layers 0-2.",
        f"ARG PACK_IMAGE={pack_image_ref}",
        "FROM ${PACK_IMAGE}",
        "",
        "USER root",
        *install_lines,
        "",
        "# Return to unprivileged Scion runtime user (UID 1000) and verify added binaries.",
        "USER scion",
        f"RUN {smoke_line}",
        "",
    ]
    return "\n".join(lines)


def _render_conventions_skill(profile: dict[str, Any]) -> str:
    """Renders skills/<slug>-repo-conventions/SKILL.md within the 300-line skill budget."""
    slug = profile["slug"]
    gf = profile["git_flow"]
    cmds = profile["commands"]
    ai_list = ", ".join(profile.get("ai_files_detected", [])) or "none"
    return (
        f"---\n"
        f"name: {slug}-repo-conventions\n"
        f"description: Repository-specific commands, Git Flow rules, and absorbed brownfield conventions for {slug}.\n"
        f"---\n\n"
        f"# Repository Conventions (`{slug}`)\n\n"
        f"## 1. Canonical Repository Commands\n"
        f"- Lint command: `{cmds['lint']}`\n"
        f"- Test command: `{cmds['test']}`\n"
        f"- Build command: `{cmds.get('build') or 'not configured'}`\n"
        f"- E2E command: `{cmds.get('e2e') or 'see pack verification gate'}`\n"
        f"- source: https://github.com/GoogleCloudPlatform/scion\n\n"
        f"## 2. Git Flow and Pull Request Contract\n"
        f"- Base branch: `{gf['base_branch']}`\n"
        f"- Branch naming pattern: `{gf['branch_pattern']}`\n"
        f"- Commit convention: `{gf['commit_convention']}`\n"
        f"- CI platform: `{gf['ci_platform']}` (PR template: `{gf.get('pr_template') or 'none'}`)\n"
        f"- Pre-existing AI coding files preserved in place: `{ai_list}`\n"
        f"- source: https://github.com/scion-frontiers/agent-team\n"
    )


def emit_layer3_overlay(
    repo_dir: pathlib.Path,
    profile: dict[str, Any],
    pack_image_ref: str,
    profile_schema_path: pathlib.Path,
) -> dict[str, Any]:
    """Emits the Layer 3 .factory/ overlay after passing the Readiness Gate."""
    gate = check_readiness(profile, profile_schema_path)
    if not gate["ready"]:
        raise ValueError("Readiness Gate failed: " + " | ".join(gate["missing_or_weak"]))

    repo = repo_dir.resolve()
    factory_dir = repo / ".factory"
    factory_dir.mkdir(parents=True, exist_ok=True)
    slug = profile["slug"]
    created: list[str] = []

    # 1. Conditional Dockerfiles (created only when toolchain delta is non-empty).
    core_df_text = render_conditional_dockerfile(pack_image_ref, profile.get("missing_binaries", []), tester_only=False)
    core_df_rel: str | None = None
    if core_df_text:
        core_df_path = factory_dir / "Dockerfile.customer"
        core_df_path.write_text(core_df_text, encoding="utf-8")
        core_df_rel = ".factory/Dockerfile.customer"
        created.append(core_df_rel)

    tester_df_text = render_conditional_dockerfile(
        pack_image_ref, profile.get("heavy_test_binaries", []), tester_only=True
    )
    tester_df_rel: str | None = None
    if tester_df_text:
        tester_df_path = factory_dir / "Dockerfile.customer-tester"
        tester_df_path.write_text(tester_df_text, encoding="utf-8")
        tester_df_rel = ".factory/Dockerfile.customer-tester"
        created.append(tester_df_rel)

    # 2. Project Overlay Skill (skills/<slug>-repo-conventions/SKILL.md).
    skill_dir = repo / "skills" / f"{slug}-repo-conventions"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(_render_conventions_skill(profile), encoding="utf-8")
    created.append(f"skills/{slug}-repo-conventions/SKILL.md")

    # 3. Declarative .factory/ manifests (retrocompatible hub-project.yaml v2).
    hub_project = {
        "schema_version": "1",
        "pack": profile["pack"],
        "pack_version": profile["pack_version"],
        "mode": profile["mode"],
        "diversity_profile": profile["diversity_profile"],
        "limits": {
            "default_max_duration": "2h",
            "default_max_turns": 60,
            "default_max_model_calls": 150,
            "auto_suspend_idle": True,
        },
        "exclude_skills": [],
        "overlay_skills": [{"dir": f"skills/{slug}-repo-conventions", "version": "1.0.0"}],
        "kaizen": {
            "enabled": True,
            "schedule_cron": profile.get("kaizen_schedule_cron", "0 17 * * 5"),
            "time_zone": profile.get("kaizen_time_zone", "America/Sao_Paulo"),
            "enable_gcp_obs": False,
        },
        "brownfield": {
            "track": profile["track"],
            "existing_hub": bool(profile["existing_hub"]),
            "custom_image_dockerfile": core_df_rel,
            "tester_image_dockerfile": tester_df_rel,
            "profile_path": ".factory/factory-profile.yaml",
        },
    }
    (factory_dir / "hub-project.yaml").write_text(yaml.safe_dump(hub_project, sort_keys=False), encoding="utf-8")
    (factory_dir / "factory-profile.yaml").write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
    created.extend([".factory/hub-project.yaml", ".factory/factory-profile.yaml"])

    # 4. In-place Knowledge Index and Modernization Backlog.
    knowledge_index = {
        "schema_version": "1",
        "sources": profile.get("knowledge_sources", []),
        "requirements": profile.get("requirements", []),
        "invariants": profile.get("invariants", []),
    }
    (factory_dir / "knowledge-index.yaml").write_text(
        yaml.safe_dump(knowledge_index, sort_keys=False), encoding="utf-8"
    )
    backlog = {
        "schema_version": "1",
        "gaps": profile.get("modernization_gaps", []),
    }
    (factory_dir / "modernization-backlog.yaml").write_text(
        yaml.safe_dump(backlog, sort_keys=False), encoding="utf-8"
    )
    created.extend([".factory/knowledge-index.yaml", ".factory/modernization-backlog.yaml"])

    # 5. Non-destructive delimited AGENTS.md merge.
    block = (
        f"## Google Cloud FDE Factory Overlay (`{profile['pack']}@{profile['pack_version']}`)\n"
        f"- Factory overlay config: `.factory/hub-project.yaml` and `.factory/factory-profile.yaml`\n"
        f"- In-place knowledge index: `.factory/knowledge-index.yaml`\n"
        f"- Repository conventions skill: `skills/{slug}-repo-conventions/SKILL.md`\n"
        f"- Modernization backlog: `.factory/modernization-backlog.yaml`"
    )
    merge_delimited_agents_md(repo / "AGENTS.md", block)
    created.append("AGENTS.md")

    return {"emitted_files": created, "custom_dockerfile": core_df_rel, "tester_dockerfile": tester_df_rel}
