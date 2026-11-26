"""Structured manifest and repository metadata parsers for brownfield onboarding (v0.4.0).

Uses Python tomllib, json, and line-anchored Makefile target regexes to detect runtimes,
tools, Git branches, CI workflows, knowledge docs, and brownfield gaps without LLM calls.
"""
from __future__ import annotations

import json
import pathlib
import re
import tomllib
from typing import Any

MAKE_TARGET_RE = re.compile(r"^([A-Za-z0-9_.-]+)\s*:(?!=)", re.MULTILINE)


def read_text_safe(path: pathlib.Path) -> str:
    """Reads UTF-8 text safely, returning an empty string on I/O errors."""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def parse_pyproject_deps(pyproject: pathlib.Path) -> tuple[set[str], dict[str, Any]]:
    """Extracts declared tool sections and lowercased dependency names from pyproject.toml."""
    if not pyproject.is_file():
        return set(), {}
    try:
        data = tomllib.loads(read_text_safe(pyproject))
    except tomllib.TOMLDecodeError:
        return set(), {}

    deps: set[str] = set()
    proj = data.get("project") if isinstance(data.get("project"), dict) else {}
    for item in proj.get("dependencies") or []:
        if isinstance(item, str):
            deps.add(re.split(r"[<>=!~;\[\s]", item, maxsplit=1)[0].strip().lower())
    opt = proj.get("optional-dependencies") if isinstance(proj.get("optional-dependencies"), dict) else {}
    for group in opt.values():
        if isinstance(group, list):
            for item in group:
                if isinstance(item, str):
                    deps.add(re.split(r"[<>=!~;\[\s]", item, maxsplit=1)[0].strip().lower())

    tool = data.get("tool") if isinstance(data.get("tool"), dict) else {}
    poetry_deps = tool.get("poetry", {}).get("dependencies", {}) if isinstance(tool.get("poetry"), dict) else {}
    if isinstance(poetry_deps, dict):
        deps.update(str(k).lower() for k in poetry_deps.keys())
    return deps, tool


def detect_binaries_and_commands(repo: pathlib.Path) -> tuple[list[str], dict[str, str], list[str], dict[str, str]]:
    """Detects runtimes, tools, commands, stacks, and pinned version files from repo manifests."""
    binaries: set[str] = set()
    stacks: set[str] = set()
    versions: dict[str, str] = {}
    lint_cmd = ""
    test_cmd = ""
    build_cmd = ""

    for vfile, key in ((".python-version", "python"), (".nvmrc", "node")):
        if (repo / vfile).is_file():
            raw = read_text_safe(repo / vfile).strip()
            if raw:
                versions[key] = raw.splitlines()[0].strip()

    pyproject = repo / "pyproject.toml"
    req_files = list(repo.glob("requirements*.txt"))
    if pyproject.is_file() or req_files:
        stacks.add("python")
        binaries.add("python")
        deps, tool = parse_pyproject_deps(pyproject)
        for rf in req_files:
            for line in read_text_safe(rf).splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    deps.add(re.split(r"[<>=!~;\[\s]", stripped, maxsplit=1)[0].lower())
        if "poetry" in tool or (repo / "poetry.lock").is_file():
            binaries.add("poetry")
        if "uv" in tool or (repo / "uv.lock").is_file():
            binaries.add("uv")
        if "ruff" in tool or "ruff" in deps or (repo / "ruff.toml").is_file() or (repo / ".ruff.toml").is_file():
            binaries.add("ruff")
            lint_cmd = lint_cmd or "ruff check ."
        if "mypy" in tool or "mypy" in deps:
            binaries.add("mypy")
        if "pytest" in tool or "pytest" in deps or (repo / "pytest.ini").is_file() or (repo / "tests").is_dir():
            binaries.add("pytest")
            test_cmd = test_cmd or "pytest -q"
        if "google-adk" in deps or "google_adk" in deps:
            binaries.add("adk")
            stacks.add("adk")
        if "cxas-scrapi" in deps or "cxas" in deps:
            binaries.add("cxas")
            stacks.add("gecx")
        if "playwright" in deps:
            binaries.add("playwright")

    if (repo / "cxas_app").is_dir() or (repo / "gecx-config.json").is_file():
        stacks.add("gecx")
        binaries.add("cxas")
    if (repo / "ge_manifest.json").is_file() or (repo / "agents-cli-manifest.yaml").is_file():
        stacks.add("adk")
        binaries.add("adk")
    if (repo / "agents-cli-manifest.yaml").is_file():
        binaries.add("agents-cli")

    pkg_json = repo / "package.json"
    if pkg_json.is_file():
        stacks.add("node")
        binaries.update({"node", "npm"})
        try:
            pkg = json.loads(read_text_safe(pkg_json))
        except json.JSONDecodeError:
            pkg = {}
        if isinstance(pkg, dict):
            all_node_deps: set[str] = set()
            for key in ("dependencies", "devDependencies"):
                sec = pkg.get(key)
                if isinstance(sec, dict):
                    all_node_deps.update(str(k).lower() for k in sec.keys())
            if (repo / "pnpm-lock.yaml").is_file():
                binaries.add("pnpm")
            if any("playwright" in d for d in all_node_deps) or any(repo.glob("playwright.config.*")):
                binaries.add("playwright-node")
            if "eslint" in all_node_deps or any(repo.glob(".eslintrc*")):
                binaries.add("eslint")
                lint_cmd = lint_cmd or "npm run lint"
            scripts = pkg.get("scripts") if isinstance(pkg.get("scripts"), dict) else {}
            if "test" in scripts and not test_cmd:
                test_cmd = "npm test"

    if (repo / "go.mod").is_file():
        stacks.add("go")
        binaries.add("go")
        test_cmd = test_cmd or "go test ./..."
    if (repo / "pom.xml").is_file():
        stacks.add("java")
        binaries.update({"jdk", "mvn"})
        test_cmd = test_cmd or "mvn test"
    if any(repo.glob("*.tf")) or any(repo.glob("deploy/*/*.tf")) or any(repo.glob("infra/*.tf")):
        stacks.add("terraform")

    if (repo / "Makefile").is_file():
        targets = set(MAKE_TARGET_RE.findall(read_text_safe(repo / "Makefile")))
        if "build" in targets and not build_cmd:
            build_cmd = "make build"
        if "lint" in targets and not lint_cmd:
            lint_cmd = "make lint"
        if "test" in targets and not test_cmd:
            test_cmd = "make test"

    commands = {
        "build": build_cmd,
        "lint": lint_cmd or "echo 'configure lint command'",
        "test": test_cmd,
        "e2e": "",
    }
    return sorted(binaries), commands, sorted(stacks), versions


def detect_base_branch(repo: pathlib.Path) -> str:
    """Resolves the repository base branch from origin/HEAD before falling back to local HEAD."""
    origin_head = repo / ".git" / "refs" / "remotes" / "origin" / "HEAD"
    if origin_head.is_file():
        m = re.match(r"ref:\s*refs/remotes/origin/(.+)", read_text_safe(origin_head).strip())
        if m:
            return m.group(1)
    head_file = repo / ".git" / "HEAD"
    if head_file.is_file():
        m = re.match(r"ref:\s*refs/heads/(.+)", read_text_safe(head_file).strip())
        if m and m.group(1) in ("main", "master", "develop", "trunk"):
            return m.group(1)
    return "main"


def detect_git_and_ci(repo: pathlib.Path) -> dict[str, Any]:
    """Inspects Git base branch, CI workflow files, CODEOWNERS, and PR templates."""
    ci_platform = "none"
    workflows: list[str] = []
    gh_wf_dir = repo / ".github" / "workflows"
    if gh_wf_dir.is_dir():
        workflows = sorted(p.relative_to(repo).as_posix() for p in gh_wf_dir.glob("*.y*ml"))
        if workflows:
            ci_platform = "github-actions"
    for ado in ("azure-pipelines.yml", "azure-pipelines.yaml"):
        if (repo / ado).is_file():
            workflows.append(ado)
            ci_platform = "azure-devops" if ci_platform == "none" else ci_platform
    if (repo / ".gitlab-ci.yml").is_file():
        workflows.append(".gitlab-ci.yml")
        ci_platform = "gitlab-ci" if ci_platform == "none" else ci_platform

    pr_tpl = next(
        (c for c in (".github/PULL_REQUEST_TEMPLATE.md", ".github/pull_request_template.md") if (repo / c).is_file()),
        None,
    )
    has_codeowners = any((repo / p).is_file() for p in ("CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS"))
    return {
        "base_branch": detect_base_branch(repo),
        "branch_pattern": "feat/<issue>-<slug>",
        "commit_convention": "conventional-commits",
        "ci_platform": ci_platform,
        "workflows": sorted(set(workflows)),
        "pr_template": pr_tpl,
        "has_codeowners": has_codeowners,
    }


def detect_knowledge_sources(repo: pathlib.Path) -> list[str]:
    """Finds existing specs, ADRs, design docs, and READMEs for in-place indexing."""
    found = [n for n in ("README.md", "ARCHITECTURE.md", "DESIGN.md", "SPEC.md") if (repo / n).is_file()]
    for folder in ("docs", "adr", "adrs", "rfcs", "knowledge-plane"):
        d = repo / folder
        if d.is_dir():
            found.extend(md.relative_to(repo).as_posix() for md in sorted(d.rglob("*.md"))[:25])
    return sorted(set(found))


def detect_hooks_and_ai_divergence(repo: pathlib.Path) -> tuple[list[str], list[str], list[dict[str, str]]]:
    """Detects untrusted workspace hooks and diverging AI instruction files for Day-0 advisory reporting."""
    hooks: list[str] = []
    advisory: list[dict[str, str]] = []

    # Check harness settings files for workspace-level command hooks.
    for rel in (
        ".claude/settings.json",
        ".claude/settings.local.json",
        ".gemini/settings.json",
        ".gemini/settings.local.json",
    ):
        p = repo / rel
        if p.is_file():
            raw = read_text_safe(p)
            if '"hooks"' in raw or "'hooks'" in raw:
                hooks.append(rel)

    # Check repository-managed Git hook directories.
    for hook_dir in (".githooks", ".husky"):
        d = repo / hook_dir
        if d.is_dir():
            for child in sorted(d.iterdir()):
                if child.is_file() and not child.name.startswith("."):
                    hooks.append(child.relative_to(repo).as_posix())

    # Check whether co-existing AGENTS.md, CLAUDE.md, and GEMINI.md files diverge.
    ai_present: dict[str, bytes] = {}
    for fname in ("AGENTS.md", "CLAUDE.md", "GEMINI.md"):
        p = repo / fname
        if p.is_file() and not p.is_symlink():
            ai_present[fname] = p.read_bytes().replace(b"\r\n", b"\n").strip()
    diverged: list[str] = []
    if len(ai_present) >= 2 and len(set(ai_present.values())) > 1:
        diverged = sorted(ai_present.keys())

    if hooks:
        advisory.append({
            "code": "UNTRUSTED_WORKSPACE_HOOKS",
            "severity": "medium",
            "blocking": False,
            "paths": hooks,
            "message": f"Detected workspace hook definitions ({', '.join(hooks)}). Review before trusting in automated runs.",
        })
    if diverged:
        advisory.append({
            "code": "AI_INSTRUCTION_DIVERGENCE",
            "severity": "low",
            "blocking": False,
            "paths": diverged,
            "message": f"Pre-existing AI instruction files diverge ({', '.join(diverged)}). Consolidate key rules into absorbed_conventions.",
        })
    return sorted(set(hooks)), diverged, advisory


def detect_modernization_gaps(
    repo: pathlib.Path,
    git_ci: dict[str, Any],
    untrusted_hooks: list[str] | None = None,
    ai_divergence: list[str] | None = None,
) -> list[dict[str, str]]:
    """Identifies non-blocking brownfield maturity gaps with severity and effort."""
    gaps: list[dict[str, str]] = []
    if not (repo / "evals").is_dir():
        gaps.append({
            "id": "GAP-EVALS",
            "title": "Add synthetic evaluation suite under evals/",
            "severity": "high",
            "effort": "M",
            "status": "open",
            "benefit": "Enables deterministic offline and Sandbox regression checks.",
        })
    if not any("verdict" in w for w in git_ci.get("workflows", [])):
        gaps.append({
            "id": "GAP-VERDICT-CI",
            "title": "Add fail-closed verdict verification CI workflow",
            "severity": "medium",
            "effort": "S",
            "status": "open",
            "benefit": "Prevents forged verdicts and unapproved eval modifications.",
        })
    if not git_ci.get("has_codeowners"):
        gaps.append({
            "id": "GAP-CODEOWNERS",
            "title": "Add CODEOWNERS for protected paths and evals/",
            "severity": "low",
            "effort": "S",
            "status": "open",
            "benefit": "Enforces explicit human reviewers on sensitive directories.",
        })
    if untrusted_hooks:
        gaps.append({
            "id": "GAP-UNTRUSTED-HOOKS",
            "title": f"Review workspace hooks ({', '.join(untrusted_hooks[:3])})",
            "severity": "medium",
            "effort": "S",
            "status": "open",
            "benefit": "Prevents unexpected shell execution from legacy workspace hooks inside agent containers.",
        })
    if ai_divergence:
        gaps.append({
            "id": "GAP-AI-DIVERGENCE",
            "title": f"Consolidate diverging AI files ({', '.join(ai_divergence)})",
            "severity": "low",
            "effort": "S",
            "status": "open",
            "benefit": "Keeps agent instructions consistent across Antigravity and Claude harnesses.",
        })
    return gaps
