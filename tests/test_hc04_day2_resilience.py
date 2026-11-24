"""Regression tests for HC-04 Day-2 resilience, Org Policy, and Tier-B Kaizen findings (HC04-F1..F5).

Verifies out-of-tree starter pack checks and kit builds, Domain Restricted Sharing Billing Budget
Pub/Sub toggle, Partner Model Garden Org Policy docs, Cloud Build CLOUD_LOGGING_ONLY compatibility,
and Tier-B Kaizen Viewer IAM plus built-in 0-token Cloud Monitoring and Logging REST collection.
"""
from __future__ import annotations

import pathlib
import shutil
import tempfile
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


class TestHC04Day2ResilienceRegressions(unittest.TestCase):
    """Locks in every fix discovered during live HC-04 qualification."""

    def test_template_pack_out_of_tree_check_and_release_kit(self) -> None:
        """Verifies HC04-F1: cloning packs/_template-pack out-of-tree passes run_check and build_release_kit."""
        from scripts.build import run_check
        from scripts.lib.release_kit import build_release_kit

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            pack_dir = tmp_path / "demo-pack"
            shutil.copytree(REPO_ROOT / "packs/_template-pack", pack_dir)
            for fname in ("pack.yaml", "compat.yaml"):
                fpath = pack_dir / fname
                txt = fpath.read_text(encoding="utf-8")
                txt = (
                    txt.replace("_template-pack", "demo-pack")
                    .replace("example-pack", "demo-pack")
                    .replace('prefix: "example"', 'prefix: "demo"')
                )
                fpath.write_text(txt, encoding="utf-8")

            self.assertEqual(run_check(str(pack_dir)), 0)
            kit_out = tmp_path / "demo-kit"
            manifest = build_release_kit(REPO_ROOT, pack_dir, kit_out)
            self.assertEqual(manifest["pack"], "demo-pack")
            self.assertTrue((kit_out / "packs/demo-pack/Dockerfile").is_file())

        readme = (REPO_ROOT / "packs/_template-pack/README.md").read_text(encoding="utf-8")
        self.assertIn("compat.yaml", readme)
        self.assertIn("runtime_image.dockerfile", readme)

    def test_finops_budget_supports_drs_pubsub_toggle(self) -> None:
        """Verifies HC04-F2: Stage 01 exposes enable_budget_pubsub_topic for DRS-enforced GCP organizations."""
        vars_tf = (REPO_ROOT / "deploy/01-landing-zone/variables.tf").read_text(encoding="utf-8")
        finops_tf = (REPO_ROOT / "deploy/01-landing-zone/finops.tf").read_text(encoding="utf-8")
        self.assertIn('variable "enable_budget_pubsub_topic"', vars_tf)
        self.assertIn("var.enable_budget_pubsub_topic ? google_pubsub_topic.budget_alerts.id : null", finops_tf)

    def test_enterprise_prerequisites_documents_drs_and_partner_model_org_policies(self) -> None:
        """Verifies HC04-F2 and HC04-F3: ENTERPRISE_PREREQUISITES documents DRS and allowedPartnerModelFeatures."""
        doc = (REPO_ROOT / "deploy/ENTERPRISE_PREREQUISITES.md").read_text(encoding="utf-8")
        self.assertIn("constraints/iam.allowedPolicyMemberDomains", doc)
        self.assertIn("enable_budget_pubsub_topic = false", doc)
        self.assertIn("constraints/vertexai.allowedPartnerModelFeatures", doc)
        self.assertIn("ADK_RUNTIME_IMAGE_DIGEST", doc)

    def test_stage_release_kit_avoids_cloud_logging_only_conflict(self) -> None:
        """Verifies HC04-F4: stage-release-kit.sh omits --gcs-log-dir because cloudbuild.yaml uses CLOUD_LOGGING_ONLY."""
        cb_yaml = (REPO_ROOT / "deploy/03-hub-bootstrap/cloudbuild.yaml").read_text(encoding="utf-8")
        script = (REPO_ROOT / "deploy/03-hub-bootstrap/stage-release-kit.sh").read_text(encoding="utf-8")
        self.assertIn("CLOUD_LOGGING_ONLY", cb_yaml)
        self.assertIn("--gcs-source-staging-dir=", script)
        self.assertNotIn("--gcs-log-dir=", script)

    def test_kaizen_viewer_iam_hub_registration_and_live_rest_adapter(self) -> None:
        """Verifies HC04-F5: kaizen_viewer has Service Usage + predict-only IAM, Hub registration, and built-in REST fetcher."""
        iam_tf = (REPO_ROOT / "deploy/01-landing-zone/iam.tf").read_text(encoding="utf-8")
        self.assertIn('resource "google_project_iam_member" "kaizen_inference_predict"', iam_tf)
        self.assertIn('resource "google_project_iam_member" "kaizen_inference_usage"', iam_tf)
        self.assertIn('resource "google_project_iam_member" "kaizen_sandbox_usage"', iam_tf)

        boot_sh = (REPO_ROOT / "deploy/03-hub-bootstrap/bootstrap-hub-project.sh").read_text(encoding="utf-8")
        self.assertIn('register_and_verify_sa "$kaizen_sa" "$inf_p" "kaizen-viewer"', boot_sh)

        from scripts.lib.kaizen_collector import build_kaizen_snapshot

        seen_calls: list[tuple[str, str, str]] = []

        def fake_gcp_http(url: str, method: str, headers: dict, payload: dict | None):
            seen_calls.append((method, url, headers.get("x-goog-user-project", "")))
            if "monitoring.googleapis.com" in url:
                return 200, {
                    "timeSeries": [
                        {
                            "resource": {"labels": {"model_user_id": "gemini-4-neon"}},
                            "points": [{"value": {"int64Value": "12"}}],
                        }
                    ]
                }
            return 200, {
                "entries": [
                    {"severity": "INFO", "resource": {"type": "cloud_run_revision"}},
                    {"severity": "DEFAULT", "resource": {"type": "cloud_run_revision"}},
                ]
            }

        snap = build_kaizen_snapshot(
            enable_gcp_obs=True,
            inference_project="demo-inf",
            sandbox_project="demo-sbx",
            include_drift=False,
            gcp_http_fn=fake_gcp_http,
        )
        # Note: inject token via monkeypatch when testing without ambient gcloud/metadata.
        from unittest.mock import patch

        with patch("scripts.lib.kaizen_gcp_obs.resolve_gcp_access_token", return_value="fake-tok"):
            seen_calls.clear()
            snap = build_kaizen_snapshot(
                enable_gcp_obs=True,
                inference_project="demo-inf",
                sandbox_project="demo-sbx",
                include_drift=False,
                gcp_http_fn=fake_gcp_http,
            )

        self.assertEqual(snap["sources_status"]["gcp_observability"], "ok")
        self.assertEqual(snap["gcp_observability"]["inference_monitoring"]["total_model_invocations"], 12)
        self.assertEqual(snap["gcp_observability"]["sandbox_logging"]["cloud_run_entries"], 2)
        self.assertEqual(seen_calls[0][2], "demo-inf")
        self.assertEqual(seen_calls[1][2], "demo-sbx")


if __name__ == "__main__":
    unittest.main()
