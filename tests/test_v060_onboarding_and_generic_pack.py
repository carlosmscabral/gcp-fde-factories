"""Tests for v0.6.0 (contrafile): packs/generic, 6-pillar /grill-me, Knowledge Plane, kp-check, and Stage 03 Coordinator bootstrap."""
from __future__ import annotations

import json
import os
import pathlib
import stat
import subprocess
import sys

import yaml

from scripts.lib.onboard_emitter import check_readiness, emit_layer3_overlay
from scripts.lib.onboard_kp import check_knowledge_plane
from scripts.lib.onboard_roles import propose_roles
from scripts.lib.onboard_scanner import scan_repository_facts
from scripts.lib.release_kit import build_release_kit

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PROFILE_SCHEMA = REPO_ROOT / "schemas/factory-profile.schema.json"
GENERIC_TOOLCHAIN = REPO_ROOT / "packs/generic/toolchain-manifest.json"
ONBOARD_CLI = REPO_ROOT / "core-gcp-fde/scripts/factory_onboard.py"
GENERIC_GATE = REPO_ROOT / "packs/generic/scripts/generic_sandbox_gate.py"


def _make_nx_monorepo(root: pathlib.Path) -> pathlib.Path:
    """Creates a brownfield Nx monorepo with React frontend and Go Cloud Run API."""
    (root / "apps" / "web").mkdir(parents=True)
    (root / "services" / "billing-api").mkdir(parents=True)
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / "nx.json").write_text('{"affected": {"defaultBase": "main"}}\n', encoding="utf-8")
    (root / "pnpm-workspace.yaml").write_text("packages:\n  - 'apps/*'\n", encoding="utf-8")
    (root / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
    (root / "package.json").write_text(
        json.dumps({"devDependencies": {"eslint": "^9.0.0", "playwright": "^1.50.0"}, "scripts": {"test": "pnpm test"}}),
        encoding="utf-8",
    )
    (root / "apps" / "web" / "package.json").write_text(
        json.dumps({"dependencies": {"react": "^19.0.0", "vite": "^6.0.0"}}),
        encoding="utf-8",
    )
    (root / "services" / "billing-api" / "go.mod").write_text("module example.com/billing\ngo 1.23\n", encoding="utf-8")
    (root / "go.mod").write_text("module example.com/root\ngo 1.23\n", encoding="utf-8")
    (root / "Dockerfile").write_text("FROM alpine:3.20\n", encoding="utf-8")
    (root / ".github" / "workflows" / "deploy.yml").write_text("steps:\n  - run: gcloud run deploy billing\n", encoding="utf-8")
    (root / "README.md").write_text("# Billing Platform\n", encoding="utf-8")
    return root


def _make_python_cli_repo(root: pathlib.Path) -> pathlib.Path:
    """Creates a brownfield Python CLI repository using Azure DevOps CI and deploy_target=none."""
    (root / "tests").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        "[project]\nname = 'ledger-cli'\ndependencies = ['pyyaml']\n[tool.ruff]\nline-length = 100\n",
        encoding="utf-8",
    )
    (root / "azure-pipelines.yml").write_text("trigger:\n  - main\n", encoding="utf-8")
    (root / "README.md").write_text("# Ledger CLI\n", encoding="utf-8")
    (root / "tests" / "test_smoke.py").write_text("def test_ok():\n    assert 1 + 1 == 2\n", encoding="utf-8")
    return root


def test_generic_pack_release_kit_and_template_composition(tmp_path: pathlib.Path) -> None:
    """Confirms packs/generic builds a 15-template sw-* offline Release Kit with grill-questions and gate."""
    out_dir = tmp_path / "generic-kit"
    manifest = build_release_kit(REPO_ROOT, REPO_ROOT / "packs/generic", out_dir)

    assert manifest["pack"] == "generic"
    assert manifest["pack_prefix"] == "sw"
    assert manifest["pack_version"] == "0.6.0"
    assert manifest["external_uris_remaining"] == 0
    assert "generic-runtime" in manifest["images"]
    assert set(manifest["harness_configs"]) == {"sw-claude-vertex", "sw-antigravity-vertex"}
    assert len(manifest["templates"]) == 15
    assert len(manifest["skills"]) == 10
    assert (out_dir / "core-gcp-fde" / "data" / "grill-questions.yaml").is_file()
    assert (out_dir / "packs" / "generic" / "scripts" / "generic_sandbox_gate.py").is_file()

    coord_agents = (out_dir / "templates" / "sw-coordinator" / "agents.md").read_text(encoding="utf-8")
    assert "`sw-*`" in coord_agents
    assert "wave-1.yaml" in coord_agents
    assert "kp-check" in coord_agents


def test_brownfield_generic_monorepo_scan_draft_questions_and_roles(tmp_path: pathlib.Path) -> None:
    """Confirms scan --pack generic --emit-draft detects Nx/React/Go/Cloud Run, curates roles, and emits draft YAML."""
    repo = _make_nx_monorepo(tmp_path / "billing-monorepo")
    draft_path = tmp_path / "draft.yaml"
    res = subprocess.run(
        [
            sys.executable,
            str(ONBOARD_CLI),
            "scan",
            "--repo",
            str(repo),
            "--pack",
            "generic",
            "--roster-preset",
            "full",
            "--emit-draft",
            str(draft_path),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stderr
    scan = json.loads(res.stdout)

    assert scan["recommended_pack"]["pack"] == "generic"
    assert scan["monorepo"]["detected"] is True
    assert scan["monorepo"]["tool"] == "nx"
    assert set(scan["frontend_frameworks"]) >= {"react", "vite"}
    assert scan["suggested_deploy_target"] == "cloud-run"
    assert "nx" in scan["unsupported_binaries"]

    enabled = {r["role"] for r in scan["proposed_roles"]["enabled_roles"]}
    assert {"coordinator", "developer", "code-reviewer", "web-builder", "generic-deployer", "qa-tester"}.issubset(enabled)

    q_ids = {q["id"] for q in scan["grill_questions"]}
    assert {"mission_and_scope", "roster_preset", "commands_and_pyramid", "toolchain_and_dockerfile", "cloud_and_models"}.issubset(q_ids)

    draft = yaml.safe_load(draft_path.read_text(encoding="utf-8"))
    assert draft["pack"] == "generic"
    assert draft["deploy_target"] == "cloud-run"
    assert draft["monorepo"]["enabled"] is True


def test_generic_library_deploy_none_ado_queue_and_wip_warning(tmp_path: pathlib.Path) -> None:
    """Confirms deploy_target=none disables deployer/web-builder, exempts L2 sandbox, and sets local wave-1 queue."""
    repo = _make_python_cli_repo(tmp_path / "ledger-cli")
    scan = scan_repository_facts(repo, GENERIC_TOOLCHAIN, pack="generic", track="complete")

    assert scan["suggested_deploy_target"] == "none"
    proposed = propose_roles(scan, pack="generic", deploy_target="none", track="complete", max_wip=4)
    disabled_map = {r["role"]: r["reason"] for r in proposed["disabled_roles"]}
    assert "generic-deployer" in disabled_map
    assert "web-builder" in disabled_map
    assert "qa-tester" in disabled_map
    assert proposed["reviewer_replicas"] == 2

    profile = {
        "schema_version": "1",
        "slug": "ledger-cli",
        "pack": "generic",
        "pack_version": "0.6.0",
        "track": "complete",
        "existing_hub": True,
        "mode": "sandbox-direct",
        "deploy_target": "none",
        "diversity_profile": "cross-model",
        "autonomy": "supervised",
        "mission": "Provide deterministic offline ledger reconciliation via a Python CLI.",
        "non_goals": ["Never deploy long-running cloud services."],
        "requirements": [
            {
                "id": "REQ-001",
                "summary": "Validate CSV ledgers and return non-zero on imbalance.",
                "acceptance_criteria": ["pytest -q passes with zero failures on sample ledgers."],
            }
        ],
        "invariants": ["Never log customer account numbers to stdout."],
        "decisions": [
            {
                "id": "ADR-001",
                "title": "Use local YAML queue for Azure DevOps",
                "status": "accepted",
                "decision": "Track Wave-1 tasks in .factory/waves/wave-1.yaml because repository uses Azure DevOps.",
            }
        ],
        "glossary": [{"term": "Ledger", "definition": "Double-entry CSV batch file validated by the CLI."}],
        "evaluation_pyramid": {"l1_offline": "pytest -q"},
        "not_verifiable_in_sandbox": ["Production ERP SFTP dropbox credentials"],
        "roster": {
            "enabled_roles": [r["role"] for r in proposed["enabled_roles"]],
            "disabled_roles": proposed["disabled_roles"],
            "max_wip": 4,
            "reviewer_replicas": 1,
        },
        "git_flow": scan["git_flow"],
        "commands": {"build": "", "lint": "python3 -m py_compile tests/test_smoke.py", "test": "pytest -q", "e2e": ""},
        "detected_binaries": scan["detected_binaries"],
        "missing_binaries": scan["missing_binaries"],
        "heavy_test_binaries": [],
        "ai_files_detected": [],
        "knowledge_sources": scan["knowledge_sources"],
        "modernization_gaps": scan["modernization_gaps"],
    }

    gate = check_readiness(profile, PROFILE_SCHEMA)
    assert gate["ready"] is True
    assert any("reviewer_replicas" in w for w in gate["warnings"])

    profile["roster"]["reviewer_replicas"] = 2
    img = "us-central1-docker.pkg.dev/demo/repo/generic-runtime@sha256:" + ("c" * 64)
    out = emit_layer3_overlay(repo, profile, img, PROFILE_SCHEMA)
    assert out["coordinator_agent"] == "sw-coordinator"
    assert ".factory/knowledge/requirements.md" in out["emitted_files"]
    assert ".factory/waves/wave-1.yaml" in out["emitted_files"]
    assert ".factory/coordinator-bootstrap-brief.md" in out["emitted_files"]

    wave = yaml.safe_load((repo / ".factory" / "waves" / "wave-1.yaml").read_text(encoding="utf-8"))
    assert wave["work_tracker"] == "local-waves-yaml"
    assert wave["tasks"][0]["req_ids"] == ["REQ-001"]

    brief = (repo / ".factory" / "coordinator-bootstrap-brief.md").read_text(encoding="utf-8")
    assert "sciontool status blocked" in brief
    assert "does not use GitHub Actions" in brief

    # Validate kp-check passes cleanly via CLI.
    kp_res = subprocess.run([sys.executable, str(ONBOARD_CLI), "kp-check", "--repo", str(repo)], capture_output=True, text=True, check=False)
    assert kp_res.returncode == 0, kp_res.stdout
    assert json.loads(kp_res.stdout)["ok"] is True


def test_knowledge_plane_zero_clobber_and_kp_check_negative_guards(tmp_path: pathlib.Path) -> None:
    """Confirms re-emit preserves agent-edited Knowledge Plane files and kp-check fails closed on broken links/orphan REQs."""
    repo = _make_python_cli_repo(tmp_path / "kp-repo")
    scan = scan_repository_facts(repo, GENERIC_TOOLCHAIN, pack="generic", track="complete")
    img = "us-central1-docker.pkg.dev/demo/repo/generic-runtime@sha256:" + ("d" * 64)
    profile = {
        "schema_version": "1",
        "slug": "kp-repo",
        "pack": "generic",
        "pack_version": "0.6.0",
        "track": "complete",
        "existing_hub": False,
        "mode": "ci-only",
        "deploy_target": "none",
        "diversity_profile": "cross-model",
        "autonomy": "supervised",
        "mission": "Test zero-clobber Knowledge Plane preservation and link checks.",
        "non_goals": ["No cloud deploys."],
        "requirements": [
            {"id": "REQ-001", "summary": "Keep knowledge links valid.", "acceptance_criteria": ["kp-check exits 0."]}
        ],
        "invariants": ["Never overwrite agent-authored Knowledge Plane prose."],
        "evaluation_pyramid": {"l1_offline": "pytest -q"},
        "git_flow": scan["git_flow"],
        "commands": {"build": "", "lint": "echo ok", "test": "pytest -q", "e2e": ""},
        "detected_binaries": scan["detected_binaries"],
        "missing_binaries": [],
        "heavy_test_binaries": [],
        "knowledge_sources": scan["knowledge_sources"],
        "modernization_gaps": [],
    }
    emit_layer3_overlay(repo, profile, img, PROFILE_SCHEMA)

    inv_path = repo / ".factory" / "knowledge" / "invariants.md"
    inv_path.write_text("# Custom Agent-Edited Invariants\n- Preserve this line.\n", encoding="utf-8")

    # Re-emit without --force-knowledge must preserve manual edits.
    out2 = emit_layer3_overlay(repo, profile, img, PROFILE_SCHEMA, force_knowledge=False)
    assert ".factory/knowledge/invariants.md" in out2["preserved_knowledge_files"]
    assert "Preserve this line." in inv_path.read_text(encoding="utf-8")

    # Re-emit WITH --force-knowledge refreshes the file.
    emit_layer3_overlay(repo, profile, img, PROFILE_SCHEMA, force_knowledge=True)
    assert "Preserve this line." not in inv_path.read_text(encoding="utf-8")

    # Negative kp-check: broken source link + orphan REQ-999 in wave-1.yaml must fail closed.
    idx_path = repo / ".factory" / "knowledge-index.yaml"
    idx = yaml.safe_load(idx_path.read_text(encoding="utf-8"))
    idx["sources"].append("docs/deleted-spec.md")
    idx_path.write_text(yaml.safe_dump(idx, sort_keys=False), encoding="utf-8")

    wave_path = repo / ".factory" / "waves" / "wave-1.yaml"
    wave = yaml.safe_load(wave_path.read_text(encoding="utf-8"))
    wave["tasks"].append({"id": "W1-99", "title": "Orphan task", "req_ids": ["REQ-999"], "size": "small"})
    wave_path.write_text(yaml.safe_dump(wave, sort_keys=False), encoding="utf-8")

    report = check_knowledge_plane(repo)
    assert report["ok"] is False
    assert any("deleted-spec.md" in e for e in report["errors"])
    assert any("REQ-999" in e for e in report["errors"])


def test_generic_sandbox_gate_l1_and_l2_honesty(tmp_path: pathlib.Path) -> None:
    """Confirms generic_sandbox_gate.py executes L1 commands, skips L2 on deploy_target=none, and blocks placeholder lint."""
    repo = _make_python_cli_repo(tmp_path / "gate-repo")
    (repo / ".factory").mkdir(parents=True)
    (repo / ".factory" / "factory-profile.yaml").write_text(
        yaml.safe_dump({
            "slug": "gate-repo",
            "pack": "generic",
            "deploy_target": "none",
            "commands": {
                "build": "",
                "lint": f"{sys.executable} -m py_compile tests/test_smoke.py",
                "test": f"{sys.executable} -m pytest -q",
                "e2e": "",
            },
            "not_verifiable_in_sandbox": ["private-erp"],
        }),
        encoding="utf-8",
    )

    l1 = subprocess.run([sys.executable, str(GENERIC_GATE), "--repo", str(repo), "--level", "1"], capture_output=True, text=True, check=False)
    assert l1.returncode == 0, l1.stdout + l1.stderr
    assert json.loads(l1.stdout)["status"] == "passed"

    l2 = subprocess.run([sys.executable, str(GENERIC_GATE), "--repo", str(repo), "--level", "2"], capture_output=True, text=True, check=False)
    assert l2.returncode == 0, l2.stdout + l2.stderr
    assert json.loads(l2.stdout)["status"] == "skipped"

    # Negative: placeholder lint command fails closed.
    (repo / ".factory" / "factory-profile.yaml").write_text(
        yaml.safe_dump({"slug": "gate-repo", "deploy_target": "none", "commands": {"lint": "echo 'configure lint command'", "test": "pytest -q"}}),
        encoding="utf-8",
    )
    bad = subprocess.run([sys.executable, str(GENERIC_GATE), "--repo", str(repo), "--level", "1"], capture_output=True, text=True, check=False)
    assert bad.returncode == 1


def test_stage03_filters_roster_skips_sa_on_deploy_none_and_starts_coordinator_idempotently(tmp_path: pathlib.Path) -> None:
    """Tests Stage 03 apply with packs/generic: roster filtering, 2-project deploy_target=none, idempotent start, and opt-out."""
    kit_dir = tmp_path / "generic-kit"
    build_release_kit(REPO_ROOT, REPO_ROOT / "packs/generic", kit_dir)

    repo = tmp_path / "billing-repo"
    (repo / ".factory").mkdir(parents=True)
    (repo / "services" / "billing-api").mkdir(parents=True)
    (repo / ".factory" / "coordinator-bootstrap-brief.md").write_text("# Standby Brief\n", encoding="utf-8")
    (repo / ".factory" / "hub-project.yaml").write_text(
        yaml.safe_dump({
            "schema_version": "1",
            "pack": "generic",
            "pack_version": "0.6.0",
            "mode": "sandbox-direct",
            "deploy_target": "none",
            "diversity_profile": "cross-model",
            "limits": {"default_max_duration": "2h", "default_max_turns": 60, "auto_suspend_idle": True},
            "overlay_skills": [],
            "kaizen": {"enabled": True, "schedule_cron": "0 17 * * 5", "time_zone": "America/Sao_Paulo", "coordinator_agent": "billing-coordinator"},
            "monorepo": {"enabled": True, "subdir": "services/billing-api", "agent_prefix": "billing"},
            "roster": {
                "enabled_roles": ["coordinator", "developer", "code-reviewer", "security-auditor"],
                "disabled_roles": ["web-builder", "generic-deployer"],
                "max_wip": 3,
                "reviewer_replicas": 1,
            },
        }),
        encoding="utf-8",
    )

    # 2-project Landing Zone (hub + inf only, no sandbox_project_id) must succeed when deploy_target=none.
    lz = tmp_path / "lz-2proj.json"
    lz.write_text(
        json.dumps({
            "inference_project_id": {"value": "cust-inf-proj"},
            "worker_sa_email": {"value": "worker@cust-inf-proj.iam.gserviceaccount.com"},
        }),
        encoding="utf-8",
    )

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_file = tmp_path / "scion.log"
    state_file = tmp_path / "agents_list.json"
    state_file.write_text("[]", encoding="utf-8")
    stub = bin_dir / "scion"
    stub.write_text(
        f"""#!/usr/bin/env bash
echo "$*" >> "{log_file}"
if [[ "$1" == "version" ]]; then echo "scion version v0.4.0-preview.3"; exit 0; fi
if [[ "$*" == *"--format json list"* ]]; then cat "{state_file}"; exit 0; fi
if [[ "$*" == *"service-accounts list"* || "$*" == *"schedule list"* || "$*" == *"project skills list"* ]]; then echo "[]"; exit 0; fi
if [[ "$*" == *"service-accounts add"* ]]; then echo '{{"id":"sa-stub-1"}}'; exit 0; fi
if [[ "$*" == *"service-accounts verify"* ]]; then echo '{{"verified":true}}'; exit 0; fi
if [[ "$*" == *"skills resolve"* || "$*" == *"templates pull"* ]]; then exit 1; fi
exit 0
""",
        encoding="utf-8",
    )
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    env = {**os.environ, "HOME": str(fake_home), "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"}
    bootstrap = kit_dir / "bootstrap" / "bootstrap-hub-project.sh"
    real_img = "us-central1-docker.pkg.dev/cust-hub/factory-images/generic-runtime@sha256:" + ("e" * 64)

    # Run 1: filters disabled templates, skips Deployer/Evaluator SAs, and launches billing-coordinator in standby.
    res1 = subprocess.run(
        [
            str(bootstrap), "apply",
            "--kit", str(kit_dir),
            "--hub", "http://127.0.0.1:8080",
            "--landing-zone", str(lz),
            "--repo", str(repo),
            "--backup-dir", str(tmp_path / "bkp1"),
            "--harness-image-antigravity", real_img,
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res1.returncode == 0, res1.stderr
    calls1 = log_file.read_text(encoding="utf-8")
    assert "templates sync" in calls1 and "--name sw-coordinator" in calls1
    assert "--name sw-web-builder" not in calls1
    assert "--name sw-generic-deployer" not in calls1
    assert "sw-deployer" not in calls1
    assert "start billing-coordinator -t sw-coordinator --role full --harness-config sw-antigravity-vertex" in calls1
    assert " -w " not in calls1  # C1: never mount monorepo subdir as /workspace on coordinator start
    assert "--task-file" in calls1 and "coordinator-bootstrap-brief.md" in calls1

    # Run 2: idempotency check when billing-coordinator already exists on Hub.
    log_file.write_text("", encoding="utf-8")
    state_file.write_text('[{"name":"billing-coordinator","phase":"running"}]', encoding="utf-8")
    res2 = subprocess.run(
        [
            str(bootstrap), "apply",
            "--kit", str(kit_dir),
            "--hub", "http://127.0.0.1:8080",
            "--landing-zone", str(lz),
            "--repo", str(repo),
            "--backup-dir", str(tmp_path / "bkp2"),
            "--harness-image-antigravity", real_img,
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res2.returncode == 0, res2.stderr
    assert "SKIP coordinator start: billing-coordinator already exists" in res2.stdout
    assert "start billing-coordinator" not in log_file.read_text(encoding="utf-8")

    # Run 3: explicit --no-start-coordinator opt-out skips start even when Hub has 0 agents.
    log_file.write_text("", encoding="utf-8")
    state_file.write_text("[]", encoding="utf-8")
    res3 = subprocess.run(
        [
            str(bootstrap), "apply",
            "--kit", str(kit_dir),
            "--hub", "http://127.0.0.1:8080",
            "--landing-zone", str(lz),
            "--repo", str(repo),
            "--backup-dir", str(tmp_path / "bkp3"),
            "--harness-image-antigravity", real_img,
            "--no-start-coordinator",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res3.returncode == 0, res3.stderr
    assert "COORDINATOR START SKIPPED" in res3.stdout
    assert "start billing-coordinator" not in log_file.read_text(encoding="utf-8")
