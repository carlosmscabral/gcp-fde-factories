"""Zero-token static repository scanner and Day-2 drift detector (v0.4.0).

Inspects greenfield and brownfield repositories across six dimensions without calling an LLM:
1. Stack, runtimes, and package managers.
2. Test, lint, and build commands.
3. Toolchain delta against a pack toolchain-manifest.json.
4. Pre-existing AI coding instruction files.
5. Git Flow and CI/CD pipelines.
6. Knowledge sources (docs, ADRs, specs, requirements) for in-place indexing.
"""
from __future__ import annotations

import pathlib
import re
from typing import Any

from scripts.lib.io_utils import load_json, load_yaml

AI_FILE_CANDIDATES = (
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    ".cursorrules",
    ".github/copilot-instructions.md",
)

HEAVY_TEST_BINARIES = {"playwright", "chromium", "jdk", "mvn", "gradle"}


def _read_lower(path: pathlib.Path) -> str:
    """Reads a text file safely in lowercase, returning an empty string on error."""
    try:
        return path.read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        return ""


def _detect_binaries_and_commands(repo: pathlib.Path) -> tuple[list[str], dict[str, str], list[str]]:
    """Detects language runtimes, tools, suggested commands, and stacks from manifest files."""
    binaries: set[str] = set()
    stacks: set[str] = set()
    lint_cmd = ""
    test_cmd = ""
    build_cmd = ""

    pyproject = repo / "pyproject.toml"
    if pyproject.exists() or any(repo.glob("requirements*.txt")):
        stacks.add("python")
        binaries.add("python")
        txt = _read_lower(pyproject) if pyproject.exists() else ""
        if "[tool.poetry]" in txt or (repo / "poetry.lock").exists():
            binaries.add("poetry")
        if "[tool.uv]" in txt or (repo / "uv.lock").exists():
            binaries.add("uv")
        if "ruff" in txt or (repo / "ruff.toml").exists() or (repo / ".ruff.toml").exists():
            binaries.add("ruff")
            lint_cmd = lint_cmd or "ruff check ."
        if "mypy" in txt:
            binaries.add("mypy")
        if "pytest" in txt or (repo / "pytest.ini").exists() or (repo / "tests").is_dir():
            binaries.add("pytest")
            test_cmd = test_cmd or "pytest -q"
        if "google-adk" in txt or "google_adk" in txt:
            binaries.add("adk")
            stacks.add("adk")
        if "cxas" in txt or (repo / "gecx-config.json").exists():
            binaries.add("cxas")
            stacks.add("gecx")

    pkg_json = repo / "package.json"
    if pkg_json.exists():
        stacks.add("node")
        binaries.update({"node", "npm"})
        txt = _read_lower(pkg_json)
        if (repo / "pnpm-lock.yaml").exists():
            binaries.add("pnpm")
        if "playwright" in txt or any(repo.glob("playwright.config.*")):
            binaries.add("playwright")
        if "eslint" in txt:
            binaries.add("eslint")
            lint_cmd = lint_cmd or "npm run lint"
        if '"test"' in txt and not test_cmd:
            test_cmd = "npm test"

    if (repo / "go.mod").exists():
        stacks.add("go")
        binaries.add("go")
        test_cmd = test_cmd or "go test ./..."

    if (repo / "pom.xml").exists():
        stacks.add("java")
        binaries.update({"jdk", "mvn"})
        test_cmd = test_cmd or "mvn test"
    elif any(repo.glob("build.gradle*")):
        stacks.add("java")
        binaries.update({"jdk", "gradle"})
        test_cmd = test_cmd or "./gradlew test"

    if any(repo.glob("*.tf")) or any(repo.glob("deploy/*/*.tf")):
        stacks.add("terraform")
        binaries.add("terraform")
        if (repo / ".tflint.hcl").exists():
            binaries.add("tflint")

    if (repo / "Makefile").exists():
        mk = _read_lower(repo / "Makefile")
        if "build:" in mk and not build_cmd:
            build_cmd = "make build"
        if "lint:" in mk and not lint_cmd:
            lint_cmd = "make lint"
        if "test:" in mk and not test_cmd:
            test_cmd = "make test"

    commands = {
        "build": build_cmd,
        "lint": lint_cmd or "echo 'configure lint command'",
        "test": test_cmd or "pytest -q",
        "e2e": "",
    }
    return sorted(binaries), commands, sorted(stacks)


def _detect_git_and_ci(repo: pathlib.Path) -> dict[str, Any]:
    """Inspects local Git HEAD, CI workflow files, CODEOWNERS, and PR templates."""
    base_branch = "main"
    head_file = repo / ".git" / "HEAD"
    if head_file.exists():
        raw = head_file.read_text(encoding="utf-8", errors="ignore").strip()
        m = re.match(r"ref:\s*refs/heads/(.+)", raw)
        if m:
            base_branch = m.group(1)

    ci_platform = "none"
    workflows: list[str] = []
    gh_wf_dir = repo / ".github" / "workflows"
    if gh_wf_dir.is_dir():
        workflows = sorted(p.relative_to(repo).as_posix() for p in gh_wf_dir.glob("*.y*ml"))
        if workflows:
            ci_platform = "github-actions"
    if (repo / "azure-pipelines.yml").exists():
        workflows.append("azure-pipelines.yml")
        ci_platform = "azure-devops" if ci_platform == "none" else ci_platform
    if (repo / ".gitlab-ci.yml").exists():
        workflows.append(".gitlab-ci.yml")
        ci_platform = "gitlab-ci" if ci_platform == "none" else ci_platform

    pr_tpl: str | None = None
    for cand in (".github/PULL_REQUEST_TEMPLATE.md", ".github/pull_request_template.md"):
        if (repo / cand).exists():
            pr_tpl = cand
            break

    return {
        "base_branch": base_branch,
        "branch_pattern": "feat/<issue>-<slug>",
        "commit_convention": "conventional-commits",
        "ci_platform": ci_platform,
        "workflows": workflows,
        "pr_template": pr_tpl,
        "has_codeowners": (repo / "CODEOWNERS").exists() or (repo / ".github" / "CODEOWNERS").exists(),
    }


def _detect_knowledge_sources(repo: pathlib.Path) -> list[str]:
    """Finds existing specs, ADRs, design docs, and READMEs for in-place indexing."""
    found: list[str] = []
    for name in ("README.md", "ARCHITECTURE.md", "DESIGN.md", "SPEC.md"):
        if (repo / name).is_file():
            found.append(name)
    for folder in ("docs", "adr", "adrs", "rfcs", "knowledge-plane"):
        d = repo / folder
        if d.is_dir():
            for md in sorted(d.rglob("*.md"))[:25]:
                found.append(md.relative_to(repo).as_posix())
    return sorted(set(found))


def _detect_modernization_gaps(repo: pathlib.Path, git_ci: dict[str, Any]) -> list[dict[str, str]]:
    """Identifies non-blocking brownfield maturity gaps for gradual adoption."""
    gaps: list[dict[str, str]] = []
    if not (repo / "evals").is_dir():
        gaps.append({
            "id": "GAP-EVALS",
            "title": "Add synthetic evaluation suite under evals/",
            "severity": "high",
            "benefit": "Enables deterministic offline and Sandbox regression checks.",
        })
    if not any("verdict" in w for w in git_ci.get("workflows", [])):
        gaps.append({
            "id": "GAP-VERDICT-CI",
            "title": "Add fail-closed verdict verification CI workflow",
            "severity": "medium",
            "benefit": "Prevents forged verdicts and unapproved eval modifications.",
        })
    if not git_ci.get("has_codeowners"):
        gaps.append({
            "id": "GAP-CODEOWNERS",
            "title": "Add CODEOWNERS for protected paths and evals/",
            "severity": "low",
            "benefit": "Enforces explicit human reviewers on sensitive directories.",
        })
    return gaps


def scan_repository_facts(
    repo_dir: pathlib.Path,
    toolchain_manifest_path: pathlib.Path | None = None,
) -> dict[str, Any]:
    """Scans repo_dir statically and computes the toolchain delta against the target pack."""
    repo = repo_dir.resolve()
    binaries, commands, stacks = _detect_binaries_and_commands(repo)
    git_ci = _detect_git_and_ci(repo)
    knowledge = _detect_knowledge_sources(repo)
    gaps = _detect_modernization_gaps(repo, git_ci)

    ai_files = [rel for rel in AI_FILE_CANDIDATES if (repo / rel).is_file()]
    if (repo / ".claude" / "skills").is_dir():
        ai_files.append(".claude/skills/")

    baked: set[str] = set()
    heavy_candidates = set(HEAVY_TEST_BINARIES)
    if toolchain_manifest_path and toolchain_manifest_path.exists():
        manifest = load_json(toolchain_manifest_path)
        baked = set(manifest.get("baked_binaries", {}).keys())
        heavy_candidates.update(manifest.get("heavy_test_candidates", []))

    missing_all = sorted(b for b in binaries if b not in baked)
    heavy_missing = sorted(b for b in missing_all if b in heavy_candidates)
    core_missing = sorted(b for b in missing_all if b not in heavy_candidates)

    return {
        "repo_path": str(repo),
        "stacks": stacks,
        "detected_binaries": binaries,
        "missing_binaries": core_missing,
        "heavy_test_binaries": heavy_missing,
        "commands": commands,
        "ai_files_detected": ai_files,
        "git_flow": git_ci,
        "knowledge_sources": knowledge,
        "modernization_gaps": gaps,
    }


def detect_repo_drift(
    repo_dir: pathlib.Path,
    toolchain_manifest_path: pathlib.Path | None = None,
) -> dict[str, Any]:
    """Compares current repo scan against .factory/factory-profile.yaml for Day-2 Kaizen drift."""
    scan = scan_repository_facts(repo_dir, toolchain_manifest_path)
    profile_path = repo_dir / ".factory" / "factory-profile.yaml"
    notes: list[str] = []
    new_missing = list(scan["missing_binaries"]) + list(scan["heavy_test_binaries"])

    if not profile_path.exists():
        return {
            "drift_detected": bool(new_missing),
            "missing_binaries": new_missing,
            "notes": ["No .factory/factory-profile.yaml found; run factory-onboard for baseline."]
            if not profile_path.exists()
            else [],
        }

    prof = load_yaml(profile_path)
    prev_bins = set(prof.get("detected_binaries", []))
    curr_bins = set(scan["detected_binaries"])
    added_bins = sorted(curr_bins - prev_bins)
    if added_bins:
        notes.append(f"New repository binaries detected since onboarding: {', '.join(added_bins)}.")

    prev_ai = set(prof.get("ai_files_detected", []))
    curr_ai = set(scan["ai_files_detected"])
    added_ai = sorted(curr_ai - prev_ai)
    if added_ai:
        notes.append(f"New AI instruction files detected: {', '.join(added_ai)}.")

    return {
        "drift_detected": bool(added_bins or added_ai or new_missing),
        "missing_binaries": new_missing,
        "notes": notes,
    }
