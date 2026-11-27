"""Negative regression tests locking cross-vendor adversarial review findings for costela (v0.7.0).

Covers every High, Medium, and key Low finding identified by Claude Opus 5.5 High:
H1 (--skip-remote-smoke bypass & ReasoningEngine verdict gate enforcement),
H2/M5/L7 (git diff --no-renames eval tamper guard, inverted REQUIRE_LIVE, exact label matching),
H3 (Hub Artifact Registry write isolation via sandbox_builder + sandbox_images),
H4 (strict YAML hub.project_id parsing, UUID validation, no nested key or path traversal),
M1/L1/L2/L3 (strict SSE content/error parser, location validation, HTTPException handling, session cleanup),
M2 (adkSandboxRuntime drops session/memory delete and memory update),
M3/M4 (lowercase WIF deduplication and count=[0] preservation for primary github_repository),
and L4/L5 (platform-injected location read + numeric project number validation).
"""
from __future__ import annotations

import http.client
import importlib.util
import json
import pathlib
import subprocess
from unittest import mock

import pytest

from packs.adk.scripts import adk_sandbox_gate
from packs.adk.scripts import ge_export
from packs.adk.scripts.lib.agent_engine_smoke import (
    _stream_has_non_empty_content,
    default_http_post,
    run_remote_agent_engine_smoke,
)
from packs.adk.scripts.lib.ge_preflight import (
    classify_ge_registration_error,
    preflight_ge_registration,
)
from scripts.lib.io_utils import sha256_tree
from scripts.lib.verdict_checker import _project_matches, verify_verdict

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
VERDICT_SCHEMA = REPO_ROOT / "schemas/verdict.schema.json"


def _load_parse_hub_project():
    """Loads deploy/03-hub-bootstrap/parse_hub_project.py dynamically for unit testing."""
    path = REPO_ROOT / "deploy/03-hub-bootstrap/parse_hub_project.py"
    spec = importlib.util.spec_from_file_location("parse_hub_project", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_h1_skip_remote_smoke_requires_unit_test_env_and_never_emits_live_verified(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    """Confirms --skip-remote-smoke fails closed in prod and downgrades verdict even in unit tests (H1)."""
    repo = tmp_path / "repo"
    (repo / "evals" / "synthetic").mkdir(parents=True)
    (repo / "evals" / "synthetic" / "smoke.evalset.json").write_text('{"eval_cases": []}\n', encoding="utf-8")
    (repo / "app").mkdir()
    out = tmp_path / "v.json"
    commit = "b" * 40
    re_name = "projects/964773340301/locations/us-central1/reasoningEngines/171967191996956672"

    monkeypatch.setenv("ADK_EVALUATOR_OAUTH_TOKEN", "tok")
    monkeypatch.delenv("ADK_GATE_UNIT_TEST", raising=False)

    rc_prod = adk_sandbox_gate.main([
        "--repo-dir", str(repo),
        "--pr-number", "1",
        "--commit-sha", commit,
        "--mode", "sandbox-live",
        "--phase", "evaluate",
        "--sandbox-project", "sbx",
        "--sandbox-project-number", "964773340301",
        "--reasoning-engine", re_name,
        "--expected-evaluator-sa", "eval@sbx.iam.gserviceaccount.com",
        "--skip-remote-smoke",
        "--verdict-out", str(out),
    ])
    assert rc_prod == 1
    assert json.loads(out.read_text(encoding="utf-8"))["verdict"] == "verifier-blocked"

    # Even with ADK_GATE_UNIT_TEST=1, skipping remote smoke downgrades verdict to unit-test-verified.
    monkeypatch.setenv("ADK_GATE_UNIT_TEST", "1")
    fake_eval = subprocess.CompletedProcess(["adk"], 0, stdout="Tests passed: 1\nTests failed: 0\n", stderr="")
    with mock.patch.object(adk_sandbox_gate, "run_cli", return_value=fake_eval):
        rc_test = adk_sandbox_gate.main([
            "--repo-dir", str(repo),
            "--pr-number", "1",
            "--commit-sha", commit,
            "--mode", "sandbox-live",
            "--phase", "evaluate",
            "--sandbox-project", "sbx",
            "--sandbox-project-number", "964773340301",
            "--reasoning-engine", re_name,
            "--expected-evaluator-sa", "eval@sbx.iam.gserviceaccount.com",
            "--skip-remote-smoke",
            "--verdict-out", str(out),
        ])
    assert rc_test == 0
    assert json.loads(out.read_text(encoding="utf-8"))["verdict"] == "unit-test-verified"

    # CI verify_verdict rejects any live-gcp-verified ReasoningEngine verdict lacking l2:agent-engine-remote-smoke.
    forged = tmp_path / "forged.json"
    forged.write_text(
        json.dumps({
            "schema_version": "1",
            "pack": "adk",
            "pr_number": 1,
            "commit_sha": commit,
            "diversity_profile": "cross-model",
            "ephemeral_app_name": re_name,
            "ge_agent_resource": None,
            "evaluation_run_ids": [],
            "expected_evaluator_sa": "eval@sbx.iam.gserviceaccount.com",
            "evals_tree_sha256": sha256_tree(repo / "evals"),
            "gates_executed": ["l1:pytest", "l2:adk-eval"],
            "gates_skipped": ["l2:agent-engine-remote-smoke"],
            "not_verifiable_surfaces": [],
            "verdict": "live-gcp-verified",
            "created_at_utc": "2026-11-26T23:00:00Z",
        }),
        encoding="utf-8",
    )
    errs = verify_verdict(
        forged,
        VERDICT_SCHEMA,
        commit,
        repo / "evals",
        sandbox_project="sbx",
        sandbox_project_number="964773340301",
        expected_evaluator_sa="eval@sbx.iam.gserviceaccount.com",
        access_token="tok",
        fetch_fn=lambda url, t, p: (200, {"name": re_name, "displayName": f"[CI] PR-1-{commit[:7]}"}),
        require_live=True,
    )
    assert any("l2:agent-engine-remote-smoke" in e for e in errs)


def test_h2_m5_l7_workflow_blocks_eval_rename_inverted_live_and_exact_labels() -> None:
    """Confirms adk-verdict-gate.yml uses --no-renames, inverted docs-only live check, and exact labels (H2/M5/L7)."""
    wf = (REPO_ROOT / "packs/adk/repo-scaffold/.github/workflows/adk-verdict-gate.yml").read_text(encoding="utf-8")
    assert "git diff --no-renames --name-only" in wf
    assert "grep -qx 'eval-change-approved'" in wf
    assert "grep -qx 'no-verdict-approved'" in wf
    assert "grep -qw 'eval-change-approved'" not in wf
    assert "grep -Ev '^(README\\.md|docs/.*|.*\\.md|\\.factory/.*)$'" in wf
    assert "=~ ^[0-9]+$" in wf


def test_h3_m2_m3_m4_landing_zone_isolates_sandbox_builder_trims_runtime_and_preserves_wif_count() -> None:
    """Confirms Hub AR isolation (H3), trimmed adkSandboxRuntime (M2), and upgrade-safe multi-repo WIF (M3/M4)."""
    iam_tf = (REPO_ROOT / "deploy/01-landing-zone/iam.tf").read_text(encoding="utf-8")
    net_tf = (REPO_ROOT / "deploy/01-landing-zone/network.tf").read_text(encoding="utf-8")
    out_tf = (REPO_ROOT / "deploy/01-landing-zone/outputs.tf").read_text(encoding="utf-8")

    # H3: Deployer acts as sandbox_builder (not release_builder), builds in sandbox_project_id, never writes Hub AR.
    assert 'resource "google_artifact_registry_repository" "sandbox_images"' in net_tf
    assert 'resource "google_service_account" "sandbox_builder"' in iam_tf
    assert 'resource "google_artifact_registry_repository_iam_member" "builder_ar_writer"' in iam_tf
    assert 'resource "google_project_iam_member" "builder_ar_writer"' not in iam_tf
    assert "deployer_hub_cloudbuild_editor" not in iam_tf
    assert "service_account_id = google_service_account.sandbox_builder[0].name" in iam_tf
    assert 'output "sandbox_artifact_registry_url"' in out_tf
    assert 'output "sandbox_builder_sa_email"' in out_tf

    # M2: adkSandboxRuntime drops delete and memory update permissions while retaining OTLP telemetry.traces.write
    # and binding official predefined observability roles (roles/cloudtrace.agent, roles/logging.logWriter, roles/monitoring.metricWriter).
    rt_start = iam_tf.index('resource "google_project_iam_custom_role" "adk_sandbox_runtime"')
    rt_end = iam_tf.index('resource "google_project_iam_member" "adk_runtime_sandbox_sessions"', rt_start)
    rt_block = iam_tf[rt_start:rt_end]
    for dropped in ('"aiplatform.sessions.delete"', '"aiplatform.memories.delete"', '"aiplatform.memories.update"'):
        assert dropped not in rt_block
    assert '"telemetry.traces.write"' in rt_block
    for predefined_role in ('"roles/cloudtrace.agent"', '"roles/logging.logWriter"', '"roles/monitoring.metricWriter"', '"roles/logging.viewer"'):
        assert predefined_role in iam_tf
    apis_tf = (REPO_ROOT / "deploy/01-landing-zone/apis.tf").read_text(encoding="utf-8")
    for otlp_api in ('"telemetry.googleapis.com"', '"cloudtrace.googleapis.com"', '"monitoring.googleapis.com"'):
        assert otlp_api in apis_tf

    # M3/M4: WIF normalizes lowercase and keeps count=[0] addresses for primary github_repository.
    assert "assertion.repository.lowerAscii()" in iam_tf
    assert 'resource "google_service_account_iam_member" "wif_evaluator_impersonation" {\n  count =' in iam_tf
    assert 'resource "google_service_account_iam_member" "wif_evaluator_impersonation_extra" {\n  for_each =' in iam_tf


def test_h4_read_scion_project_id_ignores_nested_keys_and_blocks_path_traversal(tmp_path: pathlib.Path) -> None:
    """Confirms YAML parser reads only hub.project_id, ignores nested keys, and rejects non-UUID traversal (H4)."""
    mod = _load_parse_hub_project()

    # Nested runtime.gcp.project_id appearing BEFORE hub.project_id must NOT win.
    valid_uuid = "47b3a38e-cb10-4f06-b6ab-fed45d25f602"
    settings = tmp_path / "settings.yaml"
    settings.write_text(
        f'schema_version: "1"\nruntime:\n  gcp:\n    project_id: tim-agnt-ai-pov-dev\nhub:\n  project_id: "{valid_uuid}"\n',
        encoding="utf-8",
    )
    assert mod.read_scion_project_id(settings) == valid_uuid

    # Path traversal payload must raise ValueError.
    traversal = tmp_path / "bad.yaml"
    traversal.write_text('hub:\n  project_id: "../../projects/other-uuid"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid hub.project_id UUID"):
        mod.read_scion_project_id(traversal)


def test_m1_l1_l2_l3_remote_smoke_rejects_error_streams_bad_loc_http_errors_and_cleans_session() -> None:
    """Confirms SSE parser rejects error payloads, validates loc, catches HTTPException, and deletes smoke session."""
    # M1: Error streams and empty/user-echo streams MUST return False.
    assert _stream_has_non_empty_content('{"output":"Error: 403 PERMISSION_DENIED"}') is False
    assert _stream_has_non_empty_content('{"text":"Internal Server Error"}') is False
    assert _stream_has_non_empty_content('{"content":{"role":"model","parts":[{"text":"   "}]}}') is False
    assert _stream_has_non_empty_content('{"content":{"role":"user","parts":[{"text":"Hello"}]}}') is False
    assert _stream_has_non_empty_content(
        'data: {"content":{"role":"model","parts":[{"text":"ok"}]}}\n'
        'data: {"code":13,"message":"internal"}\n'
    ) is False
    assert _stream_has_non_empty_content(
        'data: {"content":{"role":"model","parts":[{"text":"ok"}]}}\n'
        'data: [{"error":{"code":500,"message":"boom"}}]\n'
    ) is False
    assert _stream_has_non_empty_content(
        'data: {"content":{"role":"model","parts":[{"text":"ok"}]}}\n'
        'Traceback (most recent call last):\n'
    ) is False

    # Valid pretty-printed JSON array and SSE with model text or functionCall MUST pass.
    assert _stream_has_non_empty_content(json.dumps([{"content": {"role": "model", "parts": [{"text": "Healthy"}]}}], indent=2)) is True
    assert _stream_has_non_empty_content('event: message\ndata: {"content":{"role":"model","parts":[{"functionCall":{"name":"health_ping"}}]}}\n') is True

    # L1: Host confusion location MUST fail before calling post_fn.
    called = False

    def fail_if_called(url, headers, body):
        nonlocal called
        called = True
        return 200, ""

    ok_loc, err_loc = run_remote_agent_engine_smoke(
        "projects/sbx/locations/evil.com#/reasoningEngines/1",
        "tok",
        "sbx",
        post_fn=fail_if_called,
    )
    assert ok_loc is False
    assert called is False
    assert "Invalid ReasoningEngine location" in err_loc

    # L2: default_http_post catches http.client.IncompleteRead and returns (0, msg).
    with mock.patch("urllib.request.urlopen", side_effect=http.client.IncompleteRead(b"partial")):
        code, msg = default_http_post("https://us-central1-aiplatform.googleapis.com/v1beta1/test", {}, {})
    assert code == 0
    assert "IncompleteRead" in msg

    # L3: Successful smoke issues best-effort async_delete_session.
    methods: list[str] = []

    def track_post(url: str, headers: dict[str, str], body: dict[str, object]) -> tuple[int, str]:
        methods.append(str(body.get("class_method") or ""))
        if body.get("class_method") == "async_create_session":
            return 200, json.dumps({"output": {"id": "sess-999"}})
        if body.get("class_method") == "async_stream_query":
            return 200, json.dumps({"content": {"role": "model", "parts": [{"text": "All systems green."}]}})
        return 200, "{}"

    ok_clean, sess_id = run_remote_agent_engine_smoke(
        "projects/964773340301/locations/us-central1/reasoningEngines/171967191996956672",
        "tok",
        "sbx",
        post_fn=track_post,
    )
    assert ok_clean is True
    assert sess_id == "sess-999"
    assert methods == ["async_create_session", "async_stream_query", "async_delete_session"]

    # L5: _project_matches rejects non-numeric sandbox_project_number.
    assert _project_matches("foreign-proj", "sbx", "foreign-proj") is False
    assert _project_matches("964773340301", "sbx", "964773340301") is True


def test_ge_license_preflight_classifies_states_and_keeps_zero_pii_iam(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Confirms GE preflight separates IAM vs license gaps and adkSandboxDeployer stays Zero-PII."""
    active_lc = "projects/280799742875/locations/global/licenseConfigs/internal_gemini_ent_plus"

    # 1. READY when ACTIVE licenseConfig matches defaultLicenseConfig with auto-register enabled.
    def ready_http(method: str, url: str, headers: dict[str, str], body: object) -> tuple[int, dict[str, object]]:
        if url.endswith("/licenseConfigs"):
            return 200, {"licenseConfigs": [{"name": active_lc, "state": "ACTIVE"}]}
        return 200, {"defaultLicenseConfig": active_lc, "enableLicenseAutoRegister": True}

    res_ready = preflight_ge_registration("280799742875", "global", "tok", http_fn=ready_http)
    assert res_ready["status"] == "READY"
    assert res_ready["ready"] is True

    # 2. NO_PROJECT_LICENSE when licenseConfigs is empty or only EXPIRED.
    def no_lic_http(method: str, url: str, headers: dict[str, str], body: object) -> tuple[int, dict[str, object]]:
        return 200, {"licenseConfigs": [{"name": active_lc, "state": "EXPIRED"}]}

    res_none = preflight_ge_registration("427709713022", "global", "tok", http_fn=no_lic_http)
    assert res_none["status"] == "NO_PROJECT_LICENSE"
    assert res_none["ready"] is False

    # 3. AUTO_REGISTER_DISABLED when ACTIVE license exists but userStore auto-register is off.
    def auto_off_http(method: str, url: str, headers: dict[str, str], body: object) -> tuple[int, dict[str, object]]:
        if url.endswith("/licenseConfigs"):
            return 200, {"licenseConfigs": [{"name": active_lc, "state": "ACTIVE"}]}
        return 200, {"defaultLicenseConfig": active_lc, "enableLicenseAutoRegister": False}

    res_off = preflight_ge_registration("280799742875", "global", "tok", http_fn=auto_off_http)
    assert res_off["status"] == "AUTO_REGISTER_DISABLED"
    assert res_off["ready"] is False

    # 4. IAM_DENIED and API_DISABLED classification.
    def denied_http(method: str, url: str, headers: dict[str, str], body: object) -> tuple[int, dict[str, object]]:
        return 403, {"error": "PERMISSION_DENIED"}

    assert preflight_ge_registration("427709713022", "global", "tok", http_fn=denied_http)["status"] == "IAM_DENIED"
    assert classify_ge_registration_error(400, {"error": "an active Gemini Enterprise license is not available"}) == "LICENSE_REQUIRED"
    assert classify_ge_registration_error(403, {"error": "PERMISSION_DENIED"}) == "IAM_DENIED"

    # 5. CLI exit codes: 0 for READY, 2 for NO_PROJECT_LICENSE, 1 for IAM_DENIED.
    monkeypatch.setenv("ADK_DEPLOYER_OAUTH_TOKEN", "tok")
    with mock.patch.object(ge_export, "preflight_ge_registration", return_value=res_none):
        assert ge_export.main(["preflight", "--project", "427709713022", "--location", "global"]) == 2
        assert '"NO_PROJECT_LICENSE"' in capsys.readouterr().out
    with mock.patch.object(ge_export, "preflight_ge_registration", return_value=res_ready):
        assert ge_export.main(["preflight", "--project", "280799742875", "--location", "global"]) == 0
        assert '"READY"' in capsys.readouterr().out

    # 6. Zero-PII IAM invariant: adk_sandbox_deployer gets metadata reads, NEVER listUserLicenses.
    iam_tf = (REPO_ROOT / "deploy/01-landing-zone/iam.tf").read_text(encoding="utf-8")
    dep_start = iam_tf.index('resource "google_project_iam_custom_role" "adk_sandbox_deployer"')
    dep_end = iam_tf.index('resource "google_project_iam_custom_role" "adk_sandbox_evaluator"', dep_start)
    dep_block = iam_tf[dep_start:dep_end]
    assert '"discoveryengine.licenseConfigs.list"' in dep_block
    assert '"discoveryengine.userStores.get"' in dep_block
    assert '"discoveryengine.userStores.listUserLicenses"' not in iam_tf

    # 7. Standalone container layout guard (HC12-F1): ge_export.py must run from /opt/adk-factory without 'packs' on sys.path.
    import shutil
    import subprocess
    import sys

    iso = tmp_path / "opt_adk_factory"
    shutil.copytree(REPO_ROOT / "packs/adk/scripts", iso)
    gcp_fde = tmp_path / "opt_gcp_fde"
    shutil.copytree(REPO_ROOT / "scripts", gcp_fde / "scripts")
    proc = subprocess.run(
        [sys.executable, str(iso / "ge_export.py"), "preflight", "--help"],
        cwd=str(tmp_path),
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(gcp_fde)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"Standalone container import failed: {proc.stderr}"
    assert "--project" in proc.stdout


def test_audit_silent_403_scanner_catches_otlp_denial_and_ignores_intentional_probes() -> None:
    """Confirms Zero-Silent-403 scanner catches background OTLP 403 while allowing marked negative probes."""
    spec = importlib.util.spec_from_file_location("audit_silent_403", REPO_ROOT / "scripts/audit-silent-403.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    entries = [
        {
            "timestamp": "2026-11-27T00:01:00Z",
            "severity": "ERROR",
            "textPayload": "Failed to export spans: 403 Forbidden PERMISSION_DENIED telemetry.traces.write",
        },
        {
            "timestamp": "2026-11-27T00:02:00Z",
            "severity": "WARNING",
            "textPayload": "Intentional negative-probe HTTP 403 on userStores/default_user_store/userLicenses",
        },
        {
            "timestamp": "2026-11-27T00:03:00Z",
            "severity": "INFO",
            "textPayload": "Healthy request processed HTTP 200",
        },
    ]
    findings = mod.classify_log_entries(entries)
    assert len(findings) == 1
    assert "telemetry.traces.write" in findings[0]["message"]



