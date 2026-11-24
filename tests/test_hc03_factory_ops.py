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
        """Verifies HC03-F1: stage-release-kit.sh passes --gcs-source-staging-dir and --gcs-log-dir."""
        script = (REPO_ROOT / "deploy/03-hub-bootstrap/stage-release-kit.sh").read_text(encoding="utf-8")
        self.assertIn("sandbox_staging_bucket", script)
        self.assertIn("--gcs-source-staging-dir=", script)
        self.assertIn("--gcs-log-dir=", script)

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

    def test_adk_repo_scaffold_ships_valid_a2a_agent_json(self) -> None:
        """Verifies HC03-F4: packs/adk/repo-scaffold/agent/agent.json exists with A2A v0.3.0 fields."""
        card_path = REPO_ROOT / "packs/adk/repo-scaffold/agent/agent.json"
        self.assertTrue(card_path.is_file(), "Starter agent/agent.json is required for adk api_server --a2a.")
        card = json.loads(card_path.read_text(encoding="utf-8"))
        self.assertEqual(card["protocolVersion"], "0.3.0")
        self.assertTrue(card["url"].endswith("/a2a/agent"))
        self.assertGreaterEqual(len(card["skills"]), 1)
        self.assertIn("tags", card["skills"][0])

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
