"""HC-08 regression tests locking empirical findings HC08-F1 and HC08-F2.

Verifies bounded retry on transient Service Usage propagation errors in stage-release-kit.sh
and roster-filtered / 2-project no-sandbox reporting in bootstrap-hub-project.sh plan.
"""
from __future__ import annotations

import json
import os
import pathlib
import stat
import subprocess

import yaml

from scripts.lib.release_kit import build_release_kit

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_hc08_f1_stage_release_kit_retries_transient_serviceusage_only(tmp_path: pathlib.Path) -> None:
    """stage-release-kit.sh retries transient serviceusage propagation errors and fails fast on real errors."""
    kit_dir = tmp_path / "kit"
    build_release_kit(REPO_ROOT, REPO_ROOT / "packs" / "generic", kit_dir)
    lz = tmp_path / "lz.json"
    lz.write_text(
        json.dumps({
            "hub_project_id": {"value": "cust-hub"},
            "region": {"value": "us-central1"},
            "artifact_registry_url": {"value": "us-central1-docker.pkg.dev/cust-hub/factory-images"},
            "release_builder_sa_email": {"value": "builder@cust-hub.iam.gserviceaccount.com"},
            "sandbox_staging_bucket": {"value": "cust-hub-staging"},
        }),
        encoding="utf-8",
    )

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    count_file = tmp_path / "gcloud_calls.txt"
    mode_file = tmp_path / "gcloud_mode.txt"

    # Stub gcloud and sleep so the test exercises real retry loops deterministically in <1s.
    gcloud_stub = bin_dir / "gcloud"
    gcloud_stub.write_text(
        f"""#!/usr/bin/env bash
if [[ "$*" == *"builds submit"* ]]; then
  n=0
  [[ -f "{count_file}" ]] && n="$(cat "{count_file}")"
  n=$((n + 1))
  echo "$n" > "{count_file}"
  mode="$(cat "{mode_file}")"
  if [[ "$mode" == "transient" && "$n" -eq 1 ]]; then
    echo "ERROR: (gcloud.builds.submit) PERMISSION_DENIED: serviceusage.services.use Propagation of the new permission" >&2
    exit 1
  fi
  if [[ "$mode" == "hard_fail" ]]; then
    echo "ERROR: Dockerfile syntax error" >&2
    exit 1
  fi
  exit 0
fi
if [[ "$*" == *"artifacts docker images describe"* ]]; then
  echo "sha256:{'a' * 64}"
  exit 0
fi
exit 0
""",
        encoding="utf-8",
    )
    gcloud_stub.chmod(gcloud_stub.stat().st_mode | stat.S_IXUSR)

    sleep_stub = bin_dir / "sleep"
    sleep_stub.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    sleep_stub.chmod(sleep_stub.stat().st_mode | stat.S_IXUSR)

    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"}
    stage_sh = str(kit_dir / "bootstrap" / "stage-release-kit.sh")

    # 1. Transient Service Usage propagation error succeeds on attempt 2.
    mode_file.write_text("transient", encoding="utf-8")
    res_ok = subprocess.run(
        [stage_sh, "--mode", "rebuild", "--kit", str(kit_dir), "--landing-zone", str(lz)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_ok.returncode == 0, res_ok.stderr
    assert count_file.read_text(encoding="utf-8").strip() == "2"
    assert "Transient Service Usage" in res_ok.stderr

    # 2. Non-transient build failure exits immediately on attempt 1 without retrying.
    count_file.write_text("0", encoding="utf-8")
    mode_file.write_text("hard_fail", encoding="utf-8")
    res_fail = subprocess.run(
        [stage_sh, "--mode", "rebuild", "--kit", str(kit_dir), "--landing-zone", str(lz)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_fail.returncode != 0
    assert count_file.read_text(encoding="utf-8").strip() == "1"


def test_hc08_f2_bootstrap_plan_reflects_roster_and_no_sandbox(tmp_path: pathlib.Path) -> None:
    """bootstrap-hub-project.sh plan marks disabled roles, sandbox SA skip, and coordinator auto-start."""
    kit_dir = tmp_path / "kit"
    build_release_kit(REPO_ROOT, REPO_ROOT / "packs" / "generic", kit_dir)

    repo_dir = tmp_path / "cli-repo"
    (repo_dir / ".factory").mkdir(parents=True)
    (repo_dir / ".factory" / "coordinator-bootstrap-brief.md").write_text("# Standby Brief\n", encoding="utf-8")
    (repo_dir / ".factory" / "hub-project.yaml").write_text(
        yaml.safe_dump({
            "schema_version": "1",
            "pack": "generic",
            "pack_version": "0.6.0",
            "mode": "ci-only",
            "deploy_target": "none",
            "diversity_profile": "cross-model",
            "limits": {"default_max_duration": "2h", "default_max_turns": 60, "auto_suspend_idle": True},
            "overlay_skills": [],
            "roster": {
                "enabled_roles": ["coordinator", "developer"],
                "disabled_roles": ["web-builder", "qa-tester", "generic-deployer"],
            },
        }),
        encoding="utf-8",
    )

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    scion_stub = bin_dir / "scion"
    scion_stub.write_text(
        """#!/usr/bin/env bash
if [[ "$1" == "version" ]]; then echo "scion version v0.4.0-preview.3"; exit 0; fi
exit 0
""",
        encoding="utf-8",
    )
    scion_stub.chmod(scion_stub.stat().st_mode | stat.S_IXUSR)

    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"}
    res = subprocess.run(
        [
            str(kit_dir / "bootstrap" / "bootstrap-hub-project.sh"),
            "plan",
            "--kit",
            str(kit_dir),
            "--hub",
            "http://127.0.0.1:8080",
            "--repo",
            str(repo_dir),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stderr
    assert "sw-web-builder [SKIP - disabled in roster]" in res.stdout
    assert "sw-qa-tester [SKIP - disabled in roster]" in res.stdout
    assert "sw-generic-deployer [SKIP - disabled in roster]" in res.stdout
    assert "sandbox_service_accounts=skip" in res.stdout
    assert "coordinator_auto_start=enabled (sw-coordinator, standby via --task-file)" in res.stdout
