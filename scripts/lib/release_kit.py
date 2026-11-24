"""Offline Release Kit builder composing Preston's 13 agent-team roles plus domain specialists.

Produces a self-contained customer handoff directory with:
- Zero external gh:// or GitHub URLs in generated templates.
- Real upstream agents.md and system-prompt.md merged from vendored agent-team@SHA-40 plus pack deltas.
- Role-scoped Hub Skill Bank URIs (skill://scion/global/<name>) for SEP/process skills.
- Hardcoded upstream model/harness_config and environment keys omitted so diversity happens at spawn.
- Prefix-isolated template names (<pack.prefix>-<role>) synced from local dirs.
- Hub Skill Bank skill directories whose basename equals the skill name.
- Closed compat.yaml, skills.lock, NOTICE, manifest.json, and Stage 03 bootstrap scripts.
"""
from __future__ import annotations

import json
import pathlib
import shutil
from typing import Any

import yaml

from scripts.lib.io_utils import load_yaml, sha256_file


def _prefixed_name(pack_prefix: str, name: str) -> str:
    """Applies pack_prefix once without duplicating an existing prefix."""
    return name if name.startswith(f"{pack_prefix}-") else f"{pack_prefix}-{name}"


def _read_optional_text(path: pathlib.Path) -> str:
    """Reads UTF-8 text from path if it exists, or returns an empty string."""
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""


def compose_specialist_template(
    repo_root: pathlib.Path,
    out_tpl_dir: pathlib.Path,
    pack_prefix: str,
    tpl_spec: dict[str, Any],
    delta_md_path: pathlib.Path | None,
    agent_team_commit: str,
) -> dict[str, Any]:
    """Composes a deterministic offline Scion v0.4 template by merging upstream base role and pack delta.

    Follows official Scion v0.4 template rules:
    - Directory basename is the template name (omits redundant name key).
    - Keeps job keys only (omits image, resources, volumes, kubernetes, hub, telemetry).
    - Omits model and harness_config so diversity_profile controls selection at spawn.
    - Separates persona (system-prompt.md) from operational rules (agents.md).
    - References role-specific skills exclusively via local Hub Skill Bank URIs.
    """
    out_tpl_dir.mkdir(parents=True, exist_ok=True)
    full_name = _prefixed_name(pack_prefix, str(tpl_spec["name"]))
    base_role = str(tpl_spec["base_role"])
    hub_role = str(tpl_spec["hub_role"])
    sa_slot = str(tpl_spec["sandbox_sa_slot"])
    role_skills = [str(s) for s in tpl_spec.get("role_skills", [])]

    description = (
        f"{full_name} specialist (base: {base_role}, hub role: {hub_role}, SA slot: {sa_slot})"
    )
    agent_yaml: dict[str, Any] = {
        "schema_version": "1",
        "description": description,
        "agent_instructions": "agents.md",
        "system_prompt": "system-prompt.md",
        "skills": [{"uri": f"skill://scion/global/{skill_name}"} for skill_name in role_skills],
    }
    header = (
        f"# Composed offline Scion v0.4 template for {full_name}.\n"
        f"# Base upstream role: {base_role} @ {agent_team_commit}.\n"
        "# Model, harness_config, and environment keys are omitted for spawn-time diversity.\n"
    )
    (out_tpl_dir / "scion-agent.yaml").write_text(
        header + yaml.safe_dump(agent_yaml, sort_keys=False, width=120),
        encoding="utf-8",
    )

    # Merge upstream persona with explicit factory authority boundaries.
    upstream_dir = repo_root / "vendor" / "agent-team" / "templates" / base_role
    upstream_sys = _read_optional_text(upstream_dir / "system-prompt.md")
    sys_sections = [
        f"# Role Persona: {full_name}",
        (
            f"Composed from upstream role `{base_role}` (pinned commit `{agent_team_commit}`).\n"
            f"- Required Hub role at spawn: `{hub_role}`.\n"
            f"- Required Sandbox SA slot at spawn: `{sa_slot}`.\n"
            "- Follow every pack, role, and overlay skill mounted in your harness skills directory."
        ),
    ]
    if upstream_sys:
        sys_sections.append(f"## Upstream Base Persona (`{base_role}`)\n\n{upstream_sys}")
    (out_tpl_dir / "system-prompt.md").write_text("\n\n".join(sys_sections) + "\n", encoding="utf-8")

    # Merge upstream operational instructions with pack delta (pack rules override upstream defaults).
    upstream_agents = _read_optional_text(upstream_dir / "agents.md")
    delta_text = _read_optional_text(delta_md_path) if delta_md_path else ""

    agent_sections = [
        f"# Operational Instructions: {full_name}",
        (
            "Scion prepends platform workspace orientation and `sciontool status` signals automatically.\n"
            f"When spawning sibling or child roles, always use the prefix-scoped `{pack_prefix}-*` template names."
        ),
    ]
    if delta_text:
        agent_sections.append(
            "## Pack Override Rules (Precedence over Upstream Base)\n\n" + delta_text
        )
    if upstream_agents:
        agent_sections.append(
            f"## Upstream Role Instructions (`scion-frontiers/agent-team/{base_role}` @ `{agent_team_commit[:7]}`)\n\n"
            + upstream_agents
        )
    (out_tpl_dir / "agents.md").write_text("\n\n".join(agent_sections) + "\n", encoding="utf-8")

    return {
        "name": full_name,
        "base_role": base_role,
        "hub_role": hub_role,
        "sandbox_sa_slot": sa_slot,
        "role_skills": role_skills,
        "has_pack_delta": bool(delta_text),
        "system_prompt_sha256": sha256_file(out_tpl_dir / "system-prompt.md"),
        "agents_md_sha256": sha256_file(out_tpl_dir / "agents.md"),
    }


def build_release_kit(repo_root: pathlib.Path, pack_dir: pathlib.Path, out_dir: pathlib.Path) -> dict[str, Any]:
    """Builds a self-contained offline Release Kit for pack_dir into out_dir."""
    pack_cfg = load_yaml(pack_dir / "pack.yaml")
    compat_cfg = load_yaml(repo_root / "compat.yaml")

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    prefix = str(pack_cfg["pack"]["prefix"])
    agent_team_commit = str(pack_cfg["upstream"]["agent_team_commit"])

    # 1. Compose all prefix-scoped templates locally (zero external URIs).
    templates_meta: list[dict[str, Any]] = []
    for tpl in pack_cfg["specialist_templates"]:
        full_name = _prefixed_name(prefix, str(tpl["name"]))
        delta_dir_rel = tpl.get("delta_dir")
        delta_md = (pack_dir / str(delta_dir_rel) / "delta.md") if delta_dir_rel else None
        meta = compose_specialist_template(
            repo_root,
            out_dir / "templates" / full_name,
            prefix,
            tpl,
            delta_md,
            agent_team_commit,
        )
        templates_meta.append(meta)

    # 2. Copy publishable skills under skills/<basename>/ so scion skills publish uses exact names.
    skills_meta: list[dict[str, Any]] = []
    for item in pack_cfg.get("project_skills", []):
        src = repo_root / item["local_dir"]
        dst = out_dir / "skills" / item["name"]
        shutil.copytree(src, dst)
        skills_meta.append({
            "name": item["name"],
            "version": item["version"],
            "scope": item["scope"],
            "attach_to_project": bool(item.get("attach_to_project", True)),
            "sha256": sha256_file(dst / "SKILL.md"),
        })

    # 3. Copy harness configs, bootstrap scripts, Dockerfiles, and normative governance files.
    hc_dir = out_dir / "harness-configs"
    hc_dir.mkdir(parents=True, exist_ok=True)
    for hc_rel in pack_cfg["runtime_image"]["harness_configs"]:
        src_hc = repo_root / hc_rel
        shutil.copy2(src_hc, hc_dir / src_hc.name)

    shutil.copytree(repo_root / "deploy" / "03-hub-bootstrap", out_dir / "bootstrap")
    shutil.copy2(repo_root / "compat.yaml", out_dir / "compat.yaml")
    shutil.copy2(repo_root / "skills.lock", out_dir / "skills.lock")
    shutil.copy2(repo_root / "WORKAROUNDS.yaml", out_dir / "WORKAROUNDS.yaml")
    shutil.copy2(repo_root / "NOTICE", out_dir / "NOTICE")

    # Include build contexts needed when customers choose --mode rebuild (cloudbuild.yaml).
    ignore_cache = shutil.ignore_patterns("__pycache__", "*.pyc")
    (out_dir / "core-gcp-fde" / "images").mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        repo_root / "core-gcp-fde" / "images" / "base.Dockerfile",
        out_dir / "core-gcp-fde" / "images" / "base.Dockerfile",
    )
    if (repo_root / "core-gcp-fde" / "scripts").is_dir():
        shutil.copytree(
            repo_root / "core-gcp-fde" / "scripts",
            out_dir / "core-gcp-fde" / "scripts",
            ignore=ignore_cache,
        )
    shutil.copytree(repo_root / "scripts" / "lib", out_dir / "scripts" / "lib", ignore=ignore_cache)
    shutil.copytree(repo_root / "schemas", out_dir / "schemas", ignore=ignore_cache)

    pack_name = str(pack_cfg["pack"]["name"])
    (out_dir / "packs" / pack_name).mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        repo_root / pack_cfg["runtime_image"]["dockerfile"],
        out_dir / pack_cfg["runtime_image"]["dockerfile"],
    )
    toolchain_manifest_rel: str | None = None
    if (pack_dir / "toolchain-manifest.json").exists():
        toolchain_manifest_rel = f"packs/{pack_name}/toolchain-manifest.json"
        shutil.copy2(pack_dir / "toolchain-manifest.json", out_dir / toolchain_manifest_rel)
    if (pack_dir / "scripts").is_dir():
        shutil.copytree(pack_dir / "scripts", out_dir / "packs" / pack_name / "scripts", ignore=ignore_cache)

    manifest: dict[str, Any] = {
        "schema_version": "1",
        "pack": pack_name,
        "pack_prefix": prefix,
        "pack_version": pack_cfg["pack"]["version"],
        "scion_tested": compat_cfg["scion"]["tested"],
        "scion_binary_sha256": compat_cfg["scion"]["binary_sha256"],
        "agent_team_commit": agent_team_commit,
        "images": compat_cfg["images"],
        "toolchain_manifest": toolchain_manifest_rel,
        "templates": templates_meta,
        "skills": skills_meta,
        "external_uris_remaining": 0,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
