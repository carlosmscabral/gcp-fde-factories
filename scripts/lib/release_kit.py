"""Offline Release Kit builder composing the 13 scion-frontiers/agent-team (SEP) roles plus domain specialists.

Produces a self-contained customer handoff directory with:
- Zero external gh:// or floating GitHub URLs in generated templates.
- Real upstream agents.md and system-prompt.md merged with core-gcp-fde and pack deltas.
- Role-scoped Hub Skill Bank URIs (skill://scion/global/<name>) and full-tree SHA-256 hashes.
- Prefix-scoped harness-config bundles (<prefix>-<harness>/config.yaml) without hardcoded models.
- Per-pack compat.yaml, skills.lock, NOTICE, manifest.json, Terraform stages, and Stage 03 scripts.
"""
from __future__ import annotations

import json
import pathlib
import shutil
from typing import Any

import yaml

from scripts.lib.io_utils import load_yaml, sha256_file, sha256_tree
from scripts.lib.lock_verifier import scan_for_floating_uris


def _prefixed_name(pack_prefix: str, name: str) -> str:
    """Applies pack_prefix once without duplicating an existing prefix."""
    return name if name.startswith(f"{pack_prefix}-") else f"{pack_prefix}-{name}"


def _read_optional_text(path: pathlib.Path | None) -> str:
    """Reads UTF-8 text from path if it exists, or returns an empty string."""
    return path.read_text(encoding="utf-8").strip() if path and path.exists() else ""


def _resolve_pack_compat(repo_root: pathlib.Path, pack_dir: pathlib.Path) -> pathlib.Path:
    """Resolves the pack-specific compat.yaml or falls back to the repository root compat.yaml."""
    pack_compat = pack_dir / "compat.yaml"
    return pack_compat if pack_compat.exists() else repo_root / "compat.yaml"


def _resolve_pack_runtime_image(compat_cfg: dict[str, Any], pack_name: str) -> str:
    """Selects the runtime image digest for pack_name from compat_cfg.images."""
    images = compat_cfg.get("images", {})
    for key in (f"{pack_name}-runtime", f"scion-{pack_name}-runtime"):
        if key in images:
            return str(images[key])
    raise ValueError(f"compat.yaml images lacks '{pack_name}-runtime' digest for pack '{pack_name}'.")


def _assert_safe_output_dir(repo_root: pathlib.Path, out_dir: pathlib.Path) -> None:
    """Refuses deleting the repository root, home directory, filesystem root, or non-kit folders."""
    resolved_out = out_dir.resolve()
    resolved_repo = repo_root.resolve()
    home_dir = pathlib.Path.home().resolve()

    if resolved_out == resolved_out.parent or resolved_out == home_dir or resolved_out == resolved_repo:
        raise ValueError(f"Refusing to overwrite protected directory: {resolved_out}")
    if resolved_repo.is_relative_to(resolved_out):
        raise ValueError(f"Refusing to overwrite ancestor of repository root: {resolved_out}")
    if not resolved_out.exists():
        return
    if not resolved_out.is_dir():
        raise ValueError(f"Output path exists and is not a directory: {resolved_out}")
    if not any(resolved_out.iterdir()):
        return

    manifest_path = resolved_out / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(
            f"Refusing to delete non-empty directory '{resolved_out}' without a Release Kit manifest.json."
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Refusing to overwrite directory with unreadable manifest.json: {resolved_out}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "1" or not manifest.get("pack"):
        raise ValueError(
            f"Refusing to overwrite non-Release-Kit directory '{resolved_out}' (invalid manifest.json)."
        )


def compose_specialist_template(
    repo_root: pathlib.Path,
    out_tpl_dir: pathlib.Path,
    pack_prefix: str,
    tpl_spec: dict[str, Any],
    core_delta_md_path: pathlib.Path | None,
    delta_md_path: pathlib.Path | None,
    agent_team_commit: str,
) -> dict[str, Any]:
    """Composes a deterministic offline Scion v0.4 template by merging upstream base, core delta, and pack delta."""
    out_tpl_dir.mkdir(parents=True, exist_ok=True)
    full_name = _prefixed_name(pack_prefix, str(tpl_spec["name"]))
    base_role = str(tpl_spec["base_role"])
    hub_role = str(tpl_spec["hub_role"])
    sa_slot = str(tpl_spec["sandbox_sa_slot"])
    role_skills = [str(s) for s in tpl_spec.get("role_skills", [])]

    description = f"{full_name} specialist (base: {base_role}, hub role: {hub_role}, SA slot: {sa_slot})"
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

    upstream_agents = _read_optional_text(upstream_dir / "agents.md")
    core_delta_text = _read_optional_text(core_delta_md_path)
    delta_text = _read_optional_text(delta_md_path)

    agent_sections = [
        f"# Operational Instructions: {full_name}",
        (
            "Scion prepends platform workspace orientation and `sciontool status` signals automatically.\n"
            f"When spawning sibling or child roles, always use the prefix-scoped `{pack_prefix}-*` template names."
        ),
    ]
    if core_delta_text:
        agent_sections.append(
            "## Core FDE Override Rules (`core-gcp-fde`)\n\n" + core_delta_text
        )
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
        "has_core_delta": bool(core_delta_text),
        "has_pack_delta": bool(delta_text),
        "system_prompt_sha256": sha256_file(out_tpl_dir / "system-prompt.md"),
        "agents_md_sha256": sha256_file(out_tpl_dir / "agents.md"),
    }


def _emit_harness_configs(
    repo_root: pathlib.Path,
    out_dir: pathlib.Path,
    pack_cfg: dict[str, Any],
    compat_cfg: dict[str, Any],
) -> list[str]:
    """Emits prefix-scoped harness-config bundles (<prefix>-<name>/config.yaml) with pack runtime image."""
    prefix = str(pack_cfg["pack"]["prefix"])
    pack_name = str(pack_cfg["pack"]["name"])
    runtime_image = _resolve_pack_runtime_image(compat_cfg, pack_name)
    hc_root = out_dir / "harness-configs"
    hc_root.mkdir(parents=True, exist_ok=True)
    emitted: list[str] = []

    for hc_rel in pack_cfg["runtime_image"]["harness_configs"]:
        src_hc = repo_root / hc_rel
        data = load_yaml(src_hc)
        scoped_name = _prefixed_name(prefix, src_hc.stem)
        data["name"] = scoped_name
        data["image"] = runtime_image

        bundle_dir = hc_root / scoped_name
        bundle_dir.mkdir(parents=True, exist_ok=True)
        header = (
            f"# Pack-scoped harness-config bundle for {scoped_name} ({pack_name}@{pack_cfg['pack']['version']}).\n"
            "# Keeps default model alias and model_aliases table while allowing per-agent `scion start --model` overrides.\n"
        )
        (bundle_dir / "config.yaml").write_text(
            header + yaml.safe_dump(data, sort_keys=False, width=120),
            encoding="utf-8",
        )
        emitted.append(scoped_name)
    return emitted


def _copy_build_and_deploy_assets(
    repo_root: pathlib.Path,
    pack_dir: pathlib.Path,
    out_dir: pathlib.Path,
    pack_cfg: dict[str, Any],
    compat_path: pathlib.Path,
) -> str | None:
    """Copies bootstrap, Terraform stages, build contexts, verifier, scaffold, and FDE onboarding skill."""
    ignore_cache = shutil.ignore_patterns("__pycache__", "*.pyc", ".terraform", "*.tfstate*")
    pack_name = str(pack_cfg["pack"]["name"])

    shutil.copytree(repo_root / "deploy" / "03-hub-bootstrap", out_dir / "bootstrap", ignore=ignore_cache)
    for stage in ("01-landing-zone", "02-factory-runtime"):
        stage_src = repo_root / "deploy" / stage
        if stage_src.is_dir():
            shutil.copytree(stage_src, out_dir / "deploy" / stage, ignore=ignore_cache)

    shutil.copy2(compat_path, out_dir / "compat.yaml")
    shutil.copy2(repo_root / "skills.lock", out_dir / "skills.lock")
    shutil.copy2(repo_root / "WORKAROUNDS.yaml", out_dir / "WORKAROUNDS.yaml")
    shutil.copy2(repo_root / "NOTICE", out_dir / "NOTICE")

    (out_dir / "core-gcp-fde" / "images").mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        repo_root / "core-gcp-fde" / "images" / "base.Dockerfile",
        out_dir / "core-gcp-fde" / "images" / "base.Dockerfile",
    )
    if (repo_root / "core-gcp-fde" / "scripts").is_dir():
        shutil.copytree(repo_root / "core-gcp-fde" / "scripts", out_dir / "core-gcp-fde" / "scripts", ignore=ignore_cache)
    if (repo_root / "core-gcp-fde" / "data").is_dir():
        shutil.copytree(repo_root / "core-gcp-fde" / "data", out_dir / "core-gcp-fde" / "data", ignore=ignore_cache)
    if (repo_root / "core-gcp-fde" / "skills" / "factory-onboard").is_dir():
        shutil.copytree(
            repo_root / "core-gcp-fde" / "skills" / "factory-onboard",
            out_dir / "fde-skills" / "factory-onboard",
            ignore=ignore_cache,
        )

    ignore_kit_lib = shutil.ignore_patterns(
        "__pycache__",
        "*.pyc",
        "sanitizer.py",
        "release_kit.py",
        "budget_engine.py",
        "lock_verifier.py",
    )
    shutil.copytree(repo_root / "scripts" / "lib", out_dir / "scripts" / "lib", ignore=ignore_kit_lib)
    shutil.copy2(repo_root / "scripts" / "verify-verdict.py", out_dir / "scripts" / "verify-verdict.py")
    shutil.copytree(repo_root / "schemas", out_dir / "schemas", ignore=ignore_cache)

    dockerfile_rel = str(pack_cfg["runtime_image"]["dockerfile"])
    # Support out-of-tree pack directories by falling back to pack_dir/<basename> when REPO_ROOT/dockerfile_rel is absent (HC-04 F1).
    dockerfile_src = repo_root / dockerfile_rel
    if not dockerfile_src.is_file():
        dockerfile_src = pack_dir / pathlib.Path(dockerfile_rel).name
    (out_dir / dockerfile_rel).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(dockerfile_src, out_dir / dockerfile_rel)
    toolchain_manifest_rel: str | None = None
    if (pack_dir / "toolchain-manifest.json").exists():
        toolchain_manifest_rel = f"packs/{pack_name}/toolchain-manifest.json"
        (out_dir / toolchain_manifest_rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pack_dir / "toolchain-manifest.json", out_dir / toolchain_manifest_rel)
    if (pack_dir / "scripts").is_dir():
        shutil.copytree(pack_dir / "scripts", out_dir / "packs" / pack_name / "scripts", ignore=ignore_cache)
    if (pack_dir / "repo-scaffold").is_dir():
        shutil.copytree(pack_dir / "repo-scaffold", out_dir / "repo-scaffold", ignore=ignore_cache)
    return toolchain_manifest_rel


def build_release_kit(repo_root: pathlib.Path, pack_dir: pathlib.Path, out_dir: pathlib.Path) -> dict[str, Any]:
    """Builds a self-contained offline Release Kit for pack_dir into out_dir."""
    pack_cfg = load_yaml(pack_dir / "pack.yaml")
    compat_path = _resolve_pack_compat(repo_root, pack_dir)
    compat_cfg = load_yaml(compat_path)

    _assert_safe_output_dir(repo_root, out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    prefix = str(pack_cfg["pack"]["prefix"])
    pack_name = str(pack_cfg["pack"]["name"])
    agent_team_commit = str(pack_cfg["upstream"]["agent_team_commit"])

    templates_meta: list[dict[str, Any]] = []
    for tpl in pack_cfg["specialist_templates"]:
        tpl_name = str(tpl["name"])
        full_name = _prefixed_name(prefix, tpl_name)
        core_delta_candidate = repo_root / "core-gcp-fde" / "templates" / tpl_name / "delta.md"
        core_delta_md = core_delta_candidate if core_delta_candidate.exists() else None
        delta_dir_rel = tpl.get("delta_dir")
        delta_md = (pack_dir / str(delta_dir_rel) / "delta.md") if delta_dir_rel else None
        meta = compose_specialist_template(
            repo_root,
            out_dir / "templates" / full_name,
            prefix,
            tpl,
            core_delta_md,
            delta_md,
            agent_team_commit,
        )
        templates_meta.append(meta)

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
            "tree_sha256": sha256_tree(dst),
        })

    harness_configs_meta = _emit_harness_configs(repo_root, out_dir, pack_cfg, compat_cfg)
    toolchain_manifest_rel = _copy_build_and_deploy_assets(repo_root, pack_dir, out_dir, pack_cfg, compat_path)
    remaining_uris = scan_for_floating_uris(out_dir / "templates")

    manifest: dict[str, Any] = {
        "schema_version": "1",
        "core_version": "0.6.0",
        "pack": pack_name,
        "pack_prefix": prefix,
        "pack_version": pack_cfg["pack"]["version"],
        "scion_tested": compat_cfg["scion"]["tested"],
        "scion_binary_sha256": compat_cfg["scion"]["binary_sha256"],
        "agent_team_commit": agent_team_commit,
        "images": compat_cfg["images"],
        "harness_configs": harness_configs_meta,
        "toolchain_manifest": toolchain_manifest_rel,
        "templates": templates_meta,
        "skills": skills_meta,
        "external_uris_remaining": len(remaining_uris),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
