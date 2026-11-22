"""Offline Release Kit builder composing specialist forks and localizing all skills.

Produces a self-contained customer handoff directory with:
- Zero external gh:// or GitHub URLs in generated templates.
- Hardcoded upstream model/harness_config keys stripped so diversity happens at spawn.
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


def compose_specialist_template(
    out_tpl_dir: pathlib.Path,
    pack_prefix: str,
    tpl_spec: dict[str, Any],
    delta_md_path: pathlib.Path,
    agent_team_commit: str,
) -> dict[str, Any]:
    """Composes a single deterministic Scion v0.4 specialist template without external URIs.

    Follows official Scion v0.4 template rules:
    - Directory basename is the template name (omits redundant name key).
    - Keeps job keys only (omits image, resources, volumes, kubernetes, hub, telemetry).
    - Omits model and harness_config so diversity_profile controls selection at spawn.
    - Separates persona (system-prompt.md) from operational rules (agents.md).
    """
    out_tpl_dir.mkdir(parents=True, exist_ok=True)
    full_name = _prefixed_name(pack_prefix, str(tpl_spec["name"]))
    base_role = str(tpl_spec["base_role"])
    hub_role = str(tpl_spec["hub_role"])
    sa_slot = str(tpl_spec["sandbox_sa_slot"])

    description = (
        f"{full_name} specialist (base: {base_role}, hub role: {hub_role}, SA slot: {sa_slot})"
    )
    agent_yaml: dict[str, Any] = {
        "schema_version": "1",
        "description": description,
        "agent_instructions": "agents.md",
        "system_prompt": "system-prompt.md",
        "skills": [],
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

    # Keep system-prompt.md focused on persona and authority boundaries.
    system_prompt = (
        f"# Role Persona: {full_name}\n\n"
        f"You act as the `{full_name}` specialist composed from upstream role `{base_role}` "
        f"(pinned commit `{agent_team_commit}`).\n\n"
        f"- Required Hub role at spawn: `{hub_role}`.\n"
        f"- Required Sandbox SA slot at spawn: `{sa_slot}`.\n"
        "- Follow every pack and overlay skill mounted in your harness skills directory.\n"
    )
    (out_tpl_dir / "system-prompt.md").write_text(system_prompt, encoding="utf-8")

    # Place operational rules in agents.md so Scion prepends its Mandatory Instruction Preamble.
    delta_text = delta_md_path.read_text(encoding="utf-8").strip()
    agents_md = (
        f"# Operational Instructions: {full_name}\n\n"
        "Scion prepends platform workspace orientation and `sciontool status` signals automatically.\n"
        "Apply the pack rules below on every task.\n\n"
        f"{delta_text}\n"
    )
    (out_tpl_dir / "agents.md").write_text(agents_md, encoding="utf-8")

    return {
        "name": full_name,
        "base_role": base_role,
        "hub_role": hub_role,
        "sandbox_sa_slot": sa_slot,
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

    # 1. Compose prefix-scoped specialist templates locally (zero external URIs).
    templates_meta: list[dict[str, Any]] = []
    for tpl in pack_cfg["specialist_templates"]:
        full_name = _prefixed_name(prefix, str(tpl["name"]))
        delta_md = pack_dir / tpl["delta_dir"] / "delta.md"
        meta = compose_specialist_template(
            out_dir / "templates" / full_name, prefix, tpl, delta_md, agent_team_commit
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
    (out_dir / "core-gcp-fde" / "images").mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        repo_root / "core-gcp-fde" / "images" / "base.Dockerfile",
        out_dir / "core-gcp-fde" / "images" / "base.Dockerfile",
    )
    (out_dir / "packs" / pack_cfg["pack"]["name"]).mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        repo_root / pack_cfg["runtime_image"]["dockerfile"],
        out_dir / pack_cfg["runtime_image"]["dockerfile"],
    )

    manifest: dict[str, Any] = {
        "schema_version": "1",
        "pack": pack_cfg["pack"]["name"],
        "pack_prefix": prefix,
        "pack_version": pack_cfg["pack"]["version"],
        "scion_tested": compat_cfg["scion"]["tested"],
        "scion_binary_sha256": compat_cfg["scion"]["binary_sha256"],
        "agent_team_commit": agent_team_commit,
        "images": compat_cfg["images"],
        "templates": templates_meta,
        "skills": skills_meta,
        "external_uris_remaining": 0,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
