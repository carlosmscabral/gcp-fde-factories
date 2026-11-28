"""Regression tests locking live mock-to-reality escapes caught during HC-15 (Wave 2 Argolis qualification).

Locks:
- HC15-F1: base.Dockerfile persists /opt/gcp-fde/.venv/bin in /etc/zsh/zshenv and /etc/zsh/zprofile
  (in addition to /etc/profile.d and /etc/bash.bashrc) because upstream scion-antigravity:v0.4.0-preview.4
  uses zsh as scion's default login shell, and runs both `su -l scion` and `su -s /bin/bash -l scion` checks.
- HC15-F2: Stage 03 custom Dockerfile Cloud Build verifies verify_binaries strictly as USER scion under
  --network=none and appends a metadata-only `.scion-runtime.Dockerfile` (`FROM ...` + `USER root`, zero RUN)
  so sciontool init PID 1 can remap SCION_HOST_UID/GID on /workspace and /home/scion before dropping privileges.
- HC15-F3: bootstrap-hub-project.sh extracts limits.auto_suspend_idle via `| tostring` (never raw `jq -re` on
  a boolean) so `auto_suspend_idle: false` does not silently exit 1 under `set -euo pipefail`.
- HC15-F4: ensure_kaizen_schedule requires active status before skipping so recreated coordinators self-heal
  `paused (target_deleted)` recurring schedules.
"""
from __future__ import annotations

import pathlib
import subprocess

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_hc15_f1_base_dockerfile_persists_venv_for_zsh_and_bash_login_shells() -> None:
    """Locks HC15-F1: base.Dockerfile configures /etc/zsh/zshenv + /etc/zsh/zprofile and tests zsh + bash."""
    text = (REPO_ROOT / "core-gcp-fde" / "images" / "base.Dockerfile").read_text(encoding="utf-8")
    assert "/etc/zsh/zshenv" in text
    assert "/etc/zsh/zprofile" in text
    assert "su -l scion -c" in text
    assert "su -s /bin/bash -l scion -c" in text


def test_hc15_f2_customer_dockerfile_cloudbuild_wraps_scion_pid1_after_nonroot_verify() -> None:
    """Locks HC15-F2: customer image verifies as USER scion (--network=none), then wraps metadata-only USER root."""
    text = (REPO_ROOT / "deploy" / "03-hub-bootstrap" / "bootstrap-hub-project.sh").read_text(encoding="utf-8")
    assert ".scion-verify.Dockerfile" in text
    assert ".scion-runtime.Dockerfile" in text
    assert "wrap-scion-pid1-user-root" in text
    assert 'f"FROM {local_build_tag}\\nUSER root\\n"' in text
    # Verify step runs BEFORE wrap step, both under --network=none using gcr.io/cloud-builders/docker only.
    assert text.index("verify-binaries-network-none") < text.index("wrap-scion-pid1-user-root")


def test_hc15_f3_auto_suspend_idle_false_does_not_fail_jq_exit_status() -> None:
    """Locks HC15-F3: jq extraction handles auto_suspend_idle=false cleanly with exit code 0."""
    text = (REPO_ROOT / "deploy" / "03-hub-bootstrap" / "bootstrap-hub-project.sh").read_text(encoding="utf-8")
    assert 'jq -re \'.limits.auto_suspend_idle\'' not in text
    expr = "(if .limits.auto_suspend_idle == null then true else .limits.auto_suspend_idle end) | tostring"
    assert expr in text

    for payload, expected in (
        ('{"limits":{"auto_suspend_idle":false}}', "false"),
        ('{"limits":{"auto_suspend_idle":true}}', "true"),
        ('{"limits":{}}', "true"),
    ):
        proc = subprocess.run(["jq", "-re", expr], input=payload, capture_output=True, text=True, check=False)
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == expected


def test_hc15_f4_kaizen_schedule_reconciler_replaces_paused_target_deleted_schedules() -> None:
    """Locks HC15-F4: ensure_kaizen_schedule skips only active schedules and self-heals paused ones."""
    text = (REPO_ROOT / "deploy" / "03-hub-bootstrap" / "bootstrap-hub-project.sh").read_text(encoding="utf-8")
    assert '((.status // "active") == "active")' in text
