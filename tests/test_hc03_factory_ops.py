"""Regression tests for HC-03 real factory operations findings (HC03-F1 through HC03-F8).

Verifies Cloud Build explicit staging bucket flags, project-scoped overlay skill UUID URIs,
adkSandboxEvaluator Cloud Run invoke rights, ADK scaffold A2A agent.json descriptor,
Cloud Run Contract 5 Verdict schema/verifier/Janitor support, non-verdict commit SHA binding,
clean CI container --entrypoint override, and evals-only tamper gating.
"""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


class TestHC03FactoryOpsRegressions(unittest.TestCase):
    """Locks in every fix discovered during live HC-03 qualification."""

    def test_stage_release_kit_routes_staging_and_logs_to_landing_zone_bucket(self) -> None:
        """Verifies HC03-F1 and HC04-F4: stage-release-kit.sh routes --gcs-source-staging-dir without conflicting --gcs-log-dir."""
        script = (REPO_ROOT / "deploy/03-hub-bootstrap/stage-release-kit.sh").read_text(encoding="utf-8")
        self.assertIn("sandbox_staging_bucket", script)
        self.assertIn("--gcs-source-staging-dir=", script)
        self.assertNotIn("--gcs-log-dir=", script)

    def test_bootstrap_overlay_sync_uses_project_uuid_and_idempotency_guard(self) -> None:
        """Verifies HC03-F2: do_overlay_sync resolves project UUID into skill://scion/project/<id>/<name>@<ver>."""
        script = (REPO_ROOT / "deploy/03-hub-bootstrap/bootstrap-hub-project.sh").read_text(encoding="utf-8")
        self.assertIn('uri="skill://scion/project/${proj_id}/${sname}@${sver}"', script)
        self.assertIn('SKIP overlay attach:', script)
        self.assertIn('scion templates sync "$tpl_dir" --name "$tname" "${PROJ_FLAGS[@]}"', script)

    def test_adk_sandbox_evaluator_role_grants_cloud_run_invoke(self) -> None:
        """Verifies HC03-F3: adkSandboxEvaluator includes run.routes.invoke for authenticated Cloud Run A2A."""
        iam_tf = (REPO_ROOT / "deploy/01-landing-zone/iam.tf").read_text(encoding="utf-8")
        start = iam_tf.index('resource "google_project_iam_custom_role" "adk_sandbox_evaluator"')
        end = iam_tf.index('resource "google_project_iam_custom_role" "adk_sandbox_janitor"', start)
        block = iam_tf[start:end]
        self.assertIn('"run.routes.invoke"', block)
        self.assertNotIn('"run.services.create"', block)
        self.assertNotIn('"run.services.delete"', block)

    def test_adk_repo_scaffold_ships_dynamic_agents_cli_a2a_surface(self) -> None:
        """Verifies HC03-F4 evolved via ADR-014: dynamic A2A v0.3 compat via app/fast_api_app.py without static agent.json."""
        scaffold = REPO_ROOT / "packs/adk/repo-scaffold"
        a2a_py = (scaffold / "app/app_utils/a2a.py").read_text(encoding="utf-8")
        fast_api_py = (scaffold / "app/fast_api_app.py").read_text(encoding="utf-8")
        adapter_py = (scaffold / "app/app_utils/reasoning_engine_adapter.py").read_text(encoding="utf-8")
        manifest_text = (scaffold / "agents-cli-manifest.yaml").read_text(encoding="utf-8")

        self.assertIn("AgentCardBuilder", a2a_py)
        self.assertIn("enable_v0_3_compat=True", a2a_py)
        self.assertIn('protocol_version="0.3"', a2a_py)
        self.assertIn("APP_URL", a2a_py)
        self.assertIn("attach_a2a_routes", fast_api_py)
        self.assertIn("attach_reasoning_engine_routes", fast_api_py)
        self.assertIn("/api/reasoning_engine", adapter_py)
        self.assertIn("/api/stream_reasoning_engine", adapter_py)
        self.assertIn("is_a2a: true", manifest_text)
        self.assertIn('app_name: "app"', manifest_text)
        self.assertFalse((scaffold / "agent/agent.json").exists())

        # Verify brownfield fallback in adk_sandbox_gate.py and agents-cli detection in onboard_parsers.py.
        from packs.adk.scripts.adk_sandbox_gate import _resolve_agent_dir
        from scripts.lib.onboard_parsers import detect_binaries_and_commands

        self.assertEqual(_resolve_agent_dir(scaffold, ""), "app")
        bins, _, stacks, _ = detect_binaries_and_commands(scaffold)
        self.assertIn("adk", stacks)
        self.assertIn("agents-cli", bins)
        with tempfile.TemporaryDirectory() as tmp:
            legacy = pathlib.Path(tmp)
            (legacy / "agent").mkdir()
            self.assertEqual(_resolve_agent_dir(legacy, ""), "agent")
            self.assertEqual(_resolve_agent_dir(scaffold, "custom_pkg"), "custom_pkg")

    def test_verdict_checker_supports_live_cloud_run_a2a_service_provenance(self) -> None:
        """Verifies HC03-F5: verdict.schema.json and verdict_checker verify Cloud Run /services/ with PR/commit labels."""
        from scripts.lib.io_utils import sha256_tree
        from scripts.lib.verdict_checker import verify_verdict

        commit_sha = "2b451191b44e88d4466b1ba7190fafe27509308d"
        svc_res = "projects/test-sbx/locations/us-central1/services/hc03-adk-pr-1"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            evals_dir = tmp_path / "evals"
            evals_dir.mkdir()
            (evals_dir / "smoke.json").write_text("{}\n", encoding="utf-8")
            verdict_path = tmp_path / "pr-1.json"
            verdict = {
                "schema_version": "1",
                "pack": "adk",
                "pr_number": 1,
                "commit_sha": commit_sha,
                "diversity_profile": "cross-model",
                "ephemeral_app_name": svc_res,
                "expected_evaluator_sa": "eval@test-sbx.iam.gserviceaccount.com",
                "evals_tree_sha256": sha256_tree(evals_dir),
                "gates_executed": ["l1:pytest", "l2:adk-eval"],
                "gates_skipped": [],
                "verdict": "live-gcp-verified",
                "created_at_utc": "2026-11-24T21:00:00Z",
            }
            verdict_path.write_text(json.dumps(verdict), encoding="utf-8")

            def fake_ok_fetch(url: str, token: str, qp: str) -> tuple[int, dict]:
                self.assertEqual(url, f"https://run.googleapis.com/v2/{svc_res}")
                self.assertEqual(qp, "test-sbx")
                return 200, {"name": svc_res, "labels": {"pr": "pr-1", "commit": commit_sha[:7]}}

            errors = verify_verdict(
                verdict_path=verdict_path,
                schema_path=REPO_ROOT / "schemas/verdict.schema.json",
                expected_commit=commit_sha,
                evals_dir=evals_dir,
                sandbox_project="test-sbx",
                expected_evaluator_sa="eval@test-sbx.iam.gserviceaccount.com",
                access_token="tok",
                fetch_fn=fake_ok_fetch,
                expected_pack="adk",
                expected_pr_number=1,
                require_live=True,
            )
            self.assertEqual(errors, [])

            def fake_mismatch_fetch(url: str, token: str, qp: str) -> tuple[int, dict]:
                return 200, {"name": svc_res, "labels": {"pr": "pr-99", "commit": "0000000"}}

            bad_errors = verify_verdict(
                verdict_path=verdict_path,
                schema_path=REPO_ROOT / "schemas/verdict.schema.json",
                expected_commit=commit_sha,
                evals_dir=evals_dir,
                sandbox_project="test-sbx",
                expected_evaluator_sa="eval@test-sbx.iam.gserviceaccount.com",
                access_token="tok",
                fetch_fn=fake_mismatch_fetch,
                expected_pack="adk",
                expected_pr_number=1,
                require_live=True,
            )
            self.assertTrue(any("Cloud Run service labels" in e for e in bad_errors))

    def test_verdict_gate_workflows_fix_commit_sha_entrypoint_janitor_and_evals_guard(self) -> None:
        """Verifies HC03-F5/F6/F7/F8 across ADK and GECX GitHub Actions Verdict Gate workflows."""
        adk_wf = (REPO_ROOT / "packs/adk/repo-scaffold/.github/workflows/adk-verdict-gate.yml").read_text(encoding="utf-8")
        gecx_wf = (REPO_ROOT / "packs/gecx/repo-scaffold/.github/workflows/gecx-verdict-gate.yml").read_text(encoding="utf-8")

        for wf in (adk_wf, gecx_wf):
            self.assertIn("export EXPECTED_CODE_SHA=", wf)
            self.assertIn(":(exclude).factory/verdicts/", wf)
            self.assertIn('--expected-commit "$EXPECTED_CODE_SHA"', wf)
            self.assertIn('--entrypoint ""', wf)

        self.assertIn("https://run.googleapis.com/v2/${RE_RES}", adk_wf)
        self.assertIn("grep -Eq '^evals/'", adk_wf)
        self.assertNotIn("grep -Eq '^(evals|tests)/'", adk_wf)


if __name__ == "__main__":
    unittest.main()
