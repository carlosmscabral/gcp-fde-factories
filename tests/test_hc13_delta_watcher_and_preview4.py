"""Regression tests locking all HC-13 live Argolis mock-to-reality escapes (HC13-F1..F7).

Verifies cold-start Stage 01 IAM API dependencies (F1), Delta Watcher empty Secret Manager
container provisioning (F2), Cloud Run v2 relative subnetwork path formatting (F3),
Scion v0.4.0-preview.4 Coordinator-before-Schedule ordering (F4), lifecycle.never_suspend
experiment enablement (F5), isolated project-local harness-config --scope global sync (F6),
and least-privilege 2-permission Delta Watcher Hub RBAC provisioning (F7).
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import stat
import subprocess

import yaml

from scripts.lib.release_kit import build_release_kit

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _hcl_without_comments(path: pathlib.Path) -> str:
    """Strips comment-only lines from a Terraform file for structural assertions."""
    return "\n".join(
        line for line in path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )


def test_hc13_f1_all_stage01_service_accounts_depend_on_enabled_apis() -> None:
    """Confirms every Stage 01 google_service_account declares depends_on = [google_project_service.enabled]."""
    for rel in ("deploy/01-landing-zone/iam.tf", "deploy/01-landing-zone/delta_watcher.tf"):
        hcl = _hcl_without_comments(REPO_ROOT / rel)
        blocks = re.findall(r'^resource "google_service_account" "([^"]+)" \{(.*?)^\}', hcl, flags=re.S | re.M)
        assert blocks, f"Expected google_service_account resources in {rel}"
        for name, body in blocks:
            assert "depends_on = [google_project_service.enabled]" in body, (
                f"HC13-F1 regression: google_service_account.{name} in {rel} lacks depends_on = [google_project_service.enabled]"
            )


def test_hc13_f2_delta_watcher_provisions_empty_secret_container_with_no_state_value() -> None:
    """Confirms Stage 01 creates the empty Secret Manager shell cold-start without embedding secret versions."""
    dw_tf = _hcl_without_comments(REPO_ROOT / "deploy/01-landing-zone/delta_watcher.tf")
    assert 'resource "google_secret_manager_secret" "delta_watcher_tracker_token"' in dw_tf
    assert "google_secret_manager_secret_version" not in dw_tf
    assert "secret_id = google_secret_manager_secret.delta_watcher_tracker_token[0].secret_id" in dw_tf
    assert "depends_on = [google_project_service.enabled]" in dw_tf


def test_hc13_f3_cloud_run_v2_strips_compute_v1_prefix_from_subnet_self_link() -> None:
    """Confirms Stage 02 Lite VM Cloud Run v2 Direct VPC Egress passes a relative subnetwork path."""
    dw_run_tf = _hcl_without_comments(REPO_ROOT / "deploy/02-factory-runtime/lite-vm/delta_watcher.tf")
    assert 'replace(var.subnet_self_link, "https://www.googleapis.com/compute/v1/", "")' in dw_run_tf
    assert "subnetwork = var.subnet_self_link" not in dw_run_tf


def test_hc13_f4_f5_f6_f7_stage03_preview4_ordering_never_suspend_isolation_and_rbac(
    tmp_path: pathlib.Path,
) -> None:
    """Confirms Stage 03 starts Coordinator before Kaizen schedule, enables never_suspend, isolates harness sync, and binds 2-perm RBAC."""
    bootstrap = REPO_ROOT / "deploy/03-hub-bootstrap/bootstrap-hub-project.sh"
    src = bootstrap.read_text(encoding="utf-8")

    # HC13-F4: Coordinator starts before recurring schedule targeting it (preview.4 validates agent existence).
    apply_body = src.split("do_apply() {", 1)[1].split("do_overlay_sync() {", 1)[0]
    assert apply_body.index("ensure_coordinator_started") < apply_body.index("ensure_kaizen_schedule")

    # HC13-F5: lifecycle.never_suspend experiment is enabled alongside lifecycle.idle_suspend.
    assert 'scion hub experiments enable lifecycle.never_suspend --hub "$HUB_URL"' in apply_body

    # HC13-F7: Delta Watcher Hub RBAC helper grants strictly agent.message + agent.read only.
    assert "ensure_delta_watcher_hub_rbac" in src
    assert '["agent.message","agent.read"]' in src
    assert '"agent.create"' not in src.split("ensure_delta_watcher_hub_rbac()", 1)[1].split("warn_adk_ge_license_preflight()", 1)[0]

    # HC13-F6 runtime check: linked repo with .scion/ syncs via --scope global from repo/.scion and never reads ~/.scion.
    kit_dir = tmp_path / "adk-kit"
    build_release_kit(REPO_ROOT, REPO_ROOT / "packs/adk", kit_dir)

    lz = tmp_path / "lz.json"
    lz.write_text(
        json.dumps({
            "hub_project_id": {"value": "hc13-hub"},
            "region": {"value": "us-central1"},
            "artifact_registry_url": {"value": "us-central1-docker.pkg.dev/hc13-hub/hc13-images"},
            "inference_project_id": {"value": "hc13-inf"},
            "sandbox_project_id": {"value": "hc13-sbx"},
            "coordinator_sa_email": {"value": "coord@hc13-inf.iam.gserviceaccount.com"},
            "worker_sa_email": {"value": "worker@hc13-inf.iam.gserviceaccount.com"},
            "sandbox_deployer_sa_email": {"value": "dep@hc13-sbx.iam.gserviceaccount.com"},
            "sandbox_evaluator_sa_email": {"value": "eval@hc13-sbx.iam.gserviceaccount.com"},
            "delta_watcher_sa_email": {"value": "dw@hc13-hub.iam.gserviceaccount.com"},
        }),
        encoding="utf-8",
    )

    repo = tmp_path / "linked-repo"
    (repo / ".factory").mkdir(parents=True)
    (repo / ".scion").mkdir(parents=True)
    (repo / ".scion" / "project-id").write_text("d17e9e44-3c26-404a-88c5-6ddba83820c1\n", encoding="utf-8")
    (repo / ".factory" / "coordinator-bootstrap-brief.md").write_text("# Brief\nStandby.\n", encoding="utf-8")
    (repo / ".factory" / "hub-project.yaml").write_text(
        yaml.safe_dump({
            "schema_version": "1",
            "pack": "adk",
            "pack_version": "0.5.0",
            "mode": "sandbox-direct",
            "diversity_profile": "cross-model",
            "limits": {"default_max_duration": "2h", "default_max_turns": 60, "auto_suspend_idle": True},
            "overlay_skills": [],
            "kaizen": {
                "enabled": True,
                "schedule_cron": "0 0 * * *",
                "time_zone": "America/Sao_Paulo",
                "coordinator_agent": "adk-coordinator",
            },
        }),
        encoding="utf-8",
    )

    # Plant a poison stale harness config in fake $HOME/.scion to prove HC13-F6 never overwrites or relies on it.
    fake_home = tmp_path / "home"
    poison_dir = fake_home / ".scion" / "harness-configs" / "adk-antigravity-vertex"
    poison_dir.mkdir(parents=True)
    poison_cfg = poison_dir / "config.yaml"
    poison_cfg.write_text("image: us-central1-docker.pkg.dev/stale-hc12-hub/stale@sha256:0000\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_file = tmp_path / "scion.log"
    stub = bin_dir / "scion"
    stub.write_text(
        f"""#!/usr/bin/env bash
echo "$*" >> "{log_file}"
if [[ "$1" == "version" ]]; then echo "scion version v0.4.0-preview.4"; exit 0; fi
if [[ "$1" == "help" && "$2" == "start" ]]; then echo "  --never-suspend  Keep alive"; exit 0; fi
if [[ "$*" == *"service-accounts list"* || "$*" == *"schedule list"* || "$*" == *"project skills list"* || "$*" == *"--format json list"* ]]; then echo "[]"; exit 0; fi
if [[ "$*" == *"service-accounts add"* ]]; then echo '{{"id":"sa-1"}}'; exit 0; fi
if [[ "$*" == *"service-accounts verify"* ]]; then echo '{{"verified":true}}'; exit 0; fi
if [[ "$*" == *"templates pull"* || "$*" == *"skills resolve"* || "$*" == *"harness-config pull"* ]]; then exit 1; fi
exit 0
""",
        encoding="utf-8",
    )
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)

    env = {
        **os.environ,
        "HOME": str(fake_home),
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
        "SCION_HUB_TOKEN": "",
    }
    real_img = "us-central1-docker.pkg.dev/hc13-hub/hc13-images/adk-antigravity-runtime@sha256:" + ("c" * 64)
    res = subprocess.run(
        [
            str(kit_dir / "bootstrap" / "bootstrap-hub-project.sh"),
            "apply",
            "--kit", str(kit_dir),
            "--hub", "http://127.0.0.1:8080",
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
    calls = log_file.read_text(encoding="utf-8")

    # HC13-F6 assertions: project-local staged config used --scope global and fake ~/.scion was untouched.
    assert "harness-config sync adk-antigravity-vertex --scope global --hub" in calls
    assert "harness-config sync adk-antigravity-vertex --global --hub" not in calls
    assert "stale-hc12-hub" in poison_cfg.read_text(encoding="utf-8")
    staged = yaml.safe_load((repo / ".scion" / "harness-configs" / "adk-antigravity-vertex" / "config.yaml").read_text(encoding="utf-8"))
    assert staged["image"] == real_img

    # HC13-F4 + HC13-F5 assertions: start with --never-suspend ran before schedule create-recurring.
    assert "hub experiments enable lifecycle.never_suspend --hub" in calls
    start_idx = calls.index("start adk-coordinator ")
    sched_idx = calls.index("schedule create-recurring ")
    assert start_idx < sched_idx
    assert "--never-suspend" in calls.splitlines()[calls[:start_idx].count("\n")]
