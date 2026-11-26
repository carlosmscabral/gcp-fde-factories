"""HC-09 regression tests locking Group-A structural findings only (zero repo-specific heuristics).

Covers shared-Hub concurrent apply 409 resilience and existing_hub default_harness_config
protection (HC09-F1), packless toolchain-manifest auto-resolution + core JDK/Maven binaries,
consistent non-mixed Maven/Gradle commands, standard Claude @AGENTS.md include parity, and
read-only in-repo symlink handling in kp-check while keeping writes symlink-strict.
"""
from __future__ import annotations

import json
import os
import pathlib
import stat
import subprocess

import yaml

from scripts.lib.onboard_kp import check_knowledge_plane, plan_knowledge_plane
from scripts.lib.onboard_scanner import scan_repository_facts
from scripts.lib.release_kit import build_release_kit

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_hc09_f1_shared_hub_concurrent_409_and_existing_hub_default_guard(tmp_path: pathlib.Path) -> None:
    """bootstrap-hub-project.sh tolerates 409 global skill/harness races and preserves shared Hub defaults."""
    kit_dir = tmp_path / "kit"
    build_release_kit(REPO_ROOT, REPO_ROOT / "packs" / "generic", kit_dir)

    lz = tmp_path / "lz.json"
    lz.write_text(
        json.dumps({
            "hub_project_id": {"value": "cust-hub"},
            "region": {"value": "us-central1"},
            "artifact_registry_url": {"value": "us-central1-docker.pkg.dev/cust-hub/factory-images"},
            "inference_project_id": {"value": "cust-inf"},
            "worker_sa_email": {"value": "worker@cust-inf.iam.gserviceaccount.com"},
        }),
        encoding="utf-8",
    )

    repo = tmp_path / "shared-proj"
    (repo / ".factory").mkdir(parents=True)
    (repo / ".factory" / "hub-project.yaml").write_text(
        yaml.safe_dump({
            "schema_version": "1",
            "pack": "generic",
            "pack_version": "0.6.0",
            "mode": "ci-only",
            "deploy_target": "none",
            "diversity_profile": "cross-model",
            "limits": {"default_max_duration": "2h", "default_max_turns": 60, "auto_suspend_idle": True},
            "overlay_skills": [],
            "brownfield": {"track": "complete", "existing_hub": True},
        }),
        encoding="utf-8",
    )

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_file = tmp_path / "scion.log"
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    # Simulate another parallel apply winning skill publish and harness sync between resolve and publish.
    stub = bin_dir / "scion"
    stub.write_text(
        f"""#!/usr/bin/env bash
echo "$*" >> "{log_file}"
if [[ "$1" == "version" ]]; then echo "scion version v0.4.0-preview.3"; exit 0; fi
if [[ "$1" == "skills" && "$2" == "resolve" ]]; then
  key="$(echo "$3" | tr '/:@' '___')"
  if [[ -f "{state_dir}/$key" ]]; then exit 0; fi
  exit 1
fi
if [[ "$1" == "skills" && "$2" == "publish" ]]; then
  sname="$(basename "$3")"
  sver=""
  for ((i=1; i<=$#; i++)); do
    if [[ "${{!i}}" == "--version" ]]; then j=$((i+1)); sver="${{!j}}"; fi
  done
  key="$(echo "skill://scion/global/${{sname}}@${{sver}}" | tr '/:@' '___')"
  touch "{state_dir}/$key"
  echo "Error: failed to create skill: conflict: Resource already exists (status: 409)" >&2
  exit 1
fi
if [[ "$1" == "harness-config" && "$2" == "sync" ]]; then
  if [[ ! -f "{state_dir}/hc_raced" ]]; then
    touch "{state_dir}/hc_raced"
    echo "Error: conflict (status: 409)" >&2
    exit 1
  fi
  exit 0
fi
if [[ "$*" == *"service-accounts list"* || "$*" == *"schedule list"* || "$*" == *"project skills list"* ]]; then echo "[]"; exit 0; fi
if [[ "$*" == *"service-accounts add"* ]]; then echo '{{"id":"sa-1"}}'; exit 0; fi
if [[ "$*" == *"service-accounts verify"* ]]; then echo '{{"verified":true}}'; exit 0; fi
if [[ "$*" == *"templates pull"* ]]; then exit 1; fi
exit 0
""",
        encoding="utf-8",
    )
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    env = {**os.environ, "HOME": str(fake_home), "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"}
    real_img = "us-central1-docker.pkg.dev/cust-hub/factory-images/generic-runtime@sha256:" + ("b" * 64)
    res = subprocess.run(
        [
            str(kit_dir / "bootstrap" / "bootstrap-hub-project.sh"),
            "apply",
            "--kit", str(kit_dir),
            "--hub", "http://127.0.0.1:8080",
            "--project", "shared-proj",
            "--landing-zone", str(lz),
            "--repo", str(repo),
            "--backup-dir", str(tmp_path / "bkp"),
            "--harness-image-antigravity", real_img,
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stderr
    assert "concurrent peer published" in res.stdout
    assert "SKIP hub-global default_harness_config update" in res.stdout
    assert "hub settings set default_harness_config" not in log_file.read_text(encoding="utf-8")


def test_hc09_structural_scan_and_kp_fixes(tmp_path: pathlib.Path) -> None:
    """Locks in packless manifest auto-resolve, @AGENTS.md parity, non-mixed Java cmds, core jdk/mvn, and kp symlinks."""
    # 1. Packless scan auto-resolves baked python/uv/pytest and recognizes @AGENTS.md include directive as parity.
    py_repo = tmp_path / "py-repo"
    py_repo.mkdir()
    (py_repo / "pyproject.toml").write_text('[project]\nname = "demo"\ndependencies = ["pytest"]\n', encoding="utf-8")
    (py_repo / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    (py_repo / "AGENTS.md").write_text("# Canonical Rules\n", encoding="utf-8")
    (py_repo / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
    s_py = scan_repository_facts(py_repo)
    assert "python" not in s_py["unsupported_binaries"]
    assert "uv" not in s_py["unsupported_binaries"]
    assert s_py["ai_file_divergence"] == []

    # 2. Co-located pom.xml + build.gradle keeps build/test internally consistent and places jdk/mvn in core container.
    java_repo = tmp_path / "java-dual"
    java_repo.mkdir()
    (java_repo / "pom.xml").write_text("<project></project>\n", encoding="utf-8")
    (java_repo / "build.gradle").write_text("plugins { id 'java' }\n", encoding="utf-8")
    (java_repo / "mvnw").write_text("#!/bin/sh\n", encoding="utf-8")
    s_java = scan_repository_facts(java_repo)
    assert s_java["commands"]["build"] == "./mvnw -DskipTests compile"
    assert s_java["commands"]["test"] == "./mvnw test"
    assert "jdk" in s_java["missing_binaries"] and "mvn" in s_java["missing_binaries"]
    assert "jdk" not in s_java["heavy_test_binaries"]

    # 3. pnpm workspace defaults JS test to pnpm test rather than npm test.
    pnpm_repo = tmp_path / "pnpm-repo"
    pnpm_repo.mkdir()
    (pnpm_repo / "pnpm-workspace.yaml").write_text("packages:\n  - 'packages/*'\n", encoding="utf-8")
    (pnpm_repo / "package.json").write_text('{"name":"root","scripts":{"test":"vitest"}}\n', encoding="utf-8")
    assert scan_repository_facts(pnpm_repo)["commands"]["test"] == "pnpm test"

    # 4. kp-check allows valid in-repo relative symlinks in read-only sources while still blocking escapes.
    kp_repo = tmp_path / "kp-symlink"
    (kp_repo / "docs").mkdir(parents=True)
    (kp_repo / "docs/real.md").write_text("# Real doc\n", encoding="utf-8")
    os.symlink("real.md", kp_repo / "docs/latest.md")
    (kp_repo / "AGENTS.md").write_text("See .factory/knowledge-index.yaml and .factory/waves/wave-1.yaml.\n", encoding="utf-8")
    prof = {
        "pack": "generic",
        "pack_version": "0.6.0",
        "slug": "kp-symlink",
        "mode": "ci-only",
        "deploy_target": "none",
        "diversity_profile": "cross-model",
        "autonomy": "supervised",
        "git_flow": {"ci_platform": "github-actions"},
        "mission": "Verify symlink safety.",
        "requirements": [{"id": "REQ-001", "summary": "Keep symlinks bounded."}],
        "invariants": ["Never escape repo root."],
        "waves": [{"id": "W1-01", "title": "Check symlink", "req_ids": ["REQ-001"], "size": "small"}],
        "knowledge_sources": ["docs/latest.md"],
    }
    planned = plan_knowledge_plane(kp_repo, prof, "sw-coordinator", force_knowledge=True)
    for dest, raw, _rel in planned["writes"]:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
    (kp_repo / ".factory/knowledge-index.yaml").write_text(
        yaml.safe_dump({
            "schema_version": "1",
            "sources": ["docs/latest.md"],
            "knowledge_files": planned["knowledge_files"],
            "requirements": [{"id": "REQ-001", "summary": "Keep symlinks bounded."}],
        }, sort_keys=False),
        encoding="utf-8",
    )
    assert check_knowledge_plane(kp_repo)["ok"] is True

    outside = tmp_path / "outside.md"
    outside.write_text("# Outside\n", encoding="utf-8")
    os.symlink(str(outside), kp_repo / "docs/escape.md")
    idx_path = kp_repo / ".factory/knowledge-index.yaml"
    idx = yaml.safe_load(idx_path.read_text(encoding="utf-8"))
    idx["sources"].append("docs/escape.md")
    idx_path.write_text(yaml.safe_dump(idx, sort_keys=False), encoding="utf-8")
    res_esc = check_knowledge_plane(kp_repo)
    assert res_esc["ok"] is False
    assert any("escaping repository root" in e for e in res_esc["errors"])
