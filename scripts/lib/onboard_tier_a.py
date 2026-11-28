"""Universal <2s Tier-A structural repository scanner (Wave 2, pure stdlib + PyYAML).

Collects shallow, deterministic, language-agnostic structural facts at zero LLM cost and
without importing jsonschema. Refuses symlinks pointing outside the repository root (M8),
resolves .git worktree pointers and exact GitHub hostnames (L4), and dynamically loads
reserved pack skill names from pack manifests when available (L5).
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import tomllib
from typing import Any
from urllib.parse import urlparse

import yaml

SKIP_DIRS = frozenset({
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "vendor",
    "dist",
    "build",
    "target",
    ".terraform",
    "__pycache__",
})

DEFAULT_RESERVED_SKILLS = frozenset({
    "gcp-fde-guardrails",
    "gcp-sandbox-contract",
    "gcp-kaizen-light",
    "gcp-kaizen-analyst",
    "factory-onboard",
    "generic-software-guardrails",
    "adk-domain-guardrails",
    "adk-ge-export-contract",
    "gecx-foundry-adapter",
    "gecx-domain-guardrails",
    "software-engineering-process",
    "agent-state-continuity",
    "artifact-durability",
    "code-review",
    "release-notes-daily",
})

PRIVATE_REGISTRY_FILES = (".npmrc", "pip.conf", ".yarnrc.yml", "settings.xml", ".mvn/settings.xml", "nuget.config", "NuGet.Config")
VERSION_PIN_FILES = (
    (".nvmrc", "node"),
    (".node-version", "node"),
    (".python-version", "python"),
    (".java-version", "java"),
    (".tool-versions", "asdf"),
    ("mise.toml", "mise"),
    ("rust-toolchain.toml", "rust"),
    ("rust-toolchain", "rust"),
)
ENV_KEY_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]{0,63})\s*=")
GIT_REMOTE_RE = re.compile(r'\[remote\s+"origin"\](.*?)(?:\n\[|\Z)', re.DOTALL)
GIT_URL_RE = re.compile(r"^\s*url\s*=\s*(.+)$", re.MULTILINE)
GO_VER_RE = re.compile(r"^(go|toolchain)\s+(\S+)", re.MULTILINE)
SUBPROJECT_MANIFESTS = ("package.json", "pyproject.toml", "go.mod", "Cargo.toml", "pom.xml", "build.gradle", "build.gradle.kts")
SUBPROJECT_PARENTS = ("apps", "services", "packages", "libs", "modules", "crates")


def _load_reserved_skills() -> frozenset[str]:
    """Loads reserved pack/core skill names from Release Kit manifest or repo pack.yaml files (L5)."""
    names = set(DEFAULT_RESERVED_SKILLS)
    base = pathlib.Path(__file__).resolve().parent.parent.parent
    kit_manifest = base / "manifest.json"
    if kit_manifest.is_file():
        try:
            data = json.loads(kit_manifest.read_text(encoding="utf-8"))
            for item in data.get("skills") or []:
                if isinstance(item, dict) and item.get("name"):
                    names.add(str(item["name"]))
        except (OSError, json.JSONDecodeError):
            pass
    packs_dir = base / "packs"
    if packs_dir.is_dir():
        for pyaml in packs_dir.glob("*/pack.yaml"):
            try:
                pdata = yaml.safe_load(pyaml.read_text(encoding="utf-8")) or {}
                for item in pdata.get("project_skills") or []:
                    if isinstance(item, dict) and item.get("name"):
                        names.add(str(item["name"]))
            except (OSError, yaml.YAMLError):
                pass
    return frozenset(names)


def _safe_in_repo_file(repo_root: pathlib.Path, path: pathlib.Path) -> pathlib.Path | None:
    """Returns resolved path strictly inside repo_root while refusing symlinks escaping the repo (M8)."""
    try:
        if path.is_symlink():
            return None
        resolved = path.resolve()
        resolved.relative_to(repo_root)
        return resolved if resolved.is_file() else None
    except (OSError, ValueError):
        return None


def _read_safe(repo_root: pathlib.Path, path: pathlib.Path, max_bytes: int = 131072) -> str:
    """Reads bounded UTF-8 text only from regular files strictly inside repo_root (M8)."""
    safe = _safe_in_repo_file(repo_root, path)
    if safe is None:
        return ""
    try:
        with safe.open("rb") as fh:
            return fh.read(max_bytes).decode("utf-8", errors="ignore")
    except OSError:
        return ""


def _resolve_git_dir(repo_root: pathlib.Path) -> pathlib.Path | None:
    """Resolves .git directory safely inside repo_root (handling both standard .git dirs and worktree files, L4)."""
    dot_git = repo_root / ".git"
    if dot_git.is_symlink():
        return None
    if dot_git.is_dir():
        return dot_git
    if dot_git.is_file():
        line = _read_safe(repo_root, dot_git, 2048).strip()
        if line.startswith("gitdir:"):
            target = (repo_root / line.split(":", 1)[1].strip()).resolve()
            try:
                target.relative_to(repo_root)
                return target if target.is_dir() else None
            except ValueError:
                return None
    return None


def read_git_origin_url(repo_root: pathlib.Path) -> str:
    """Reads the origin remote URL safely from .git/config (supporting worktree files, zero subprocess)."""
    resolved = repo_root.resolve()
    git_dir = _resolve_git_dir(resolved)
    if git_dir is None:
        return ""
    cfg = _read_safe(resolved, git_dir / "config")
    if not cfg:
        return ""
    m_sec = GIT_REMOTE_RE.search(cfg)
    if not m_sec:
        return ""
    m_url = GIT_URL_RE.search(m_sec.group(1))
    return m_url.group(1).strip() if m_url else ""


def _parse_origin_host(repo_root: pathlib.Path, git_dir: pathlib.Path | None) -> tuple[str, str]:
    """Classifies origin host with exact/suffix matching; unknown or non-GitHub remotes default to best_effort (L4)."""
    if git_dir is None:
        return "unknown", "best_effort"
    raw_url = read_git_origin_url(repo_root)
    if not raw_url:
        return "unknown", "best_effort"
    host = ""
    if "://" in raw_url:
        host = (urlparse(raw_url).hostname or "").lower()
    elif "@" in raw_url and ":" in raw_url:
        host = raw_url.split("@", 1)[1].split(":", 1)[0].lower()
    if not host:
        return "unknown", "best_effort"
    if host == "github.com":
        return "github", "native_github"
    if host.endswith(".ghe.com") or host.startswith("github.") or host.endswith(".github.com"):
        return "ghes", "native_github"
    if host == "gitlab.com" or host.startswith("gitlab.") or host.endswith(".gitlab.com"):
        return "gitlab", "best_effort"
    if host == "dev.azure.com" or host.endswith(".visualstudio.com"):
        return "azure_devops", "best_effort"
    if host == "bitbucket.org" or host.endswith(".bitbucket.org"):
        return "bitbucket", "best_effort"
    return host, "best_effort"


def _detect_five_monorepo_layouts(repo: pathlib.Path) -> dict[str, Any]:
    """Detects the 5 canonical monorepo workspace layouts (JS/TS, JVM, Go, Rust, Python)."""
    layouts: list[str] = []
    tool: str | None = None

    for fname, label in (("nx.json", "nx"), ("turbo.json", "turbo"), ("pnpm-workspace.yaml", "pnpm-workspace"), ("lerna.json", "lerna")):
        if _safe_in_repo_file(repo, repo / fname):
            layouts.append("js-ts")
            tool = tool or label
            break
    pkg_txt = _read_safe(repo, repo / "package.json")
    if pkg_txt:
        try:
            pkg = json.loads(pkg_txt)
            if isinstance(pkg, dict) and pkg.get("workspaces"):
                if "js-ts" not in layouts:
                    layouts.append("js-ts")
                tool = tool or "npm-workspaces"
        except json.JSONDecodeError:
            pass

    gradle_txt = _read_safe(repo, repo / "settings.gradle") + _read_safe(repo, repo / "settings.gradle.kts")
    if gradle_txt and ("include(" in gradle_txt or "include " in gradle_txt):
        layouts.append("jvm")
        tool = tool or "gradle-multimodule"
    if "<modules>" in _read_safe(repo, repo / "pom.xml"):
        if "jvm" not in layouts:
            layouts.append("jvm")
        tool = tool or "maven-multimodule"

    if _safe_in_repo_file(repo, repo / "go.work"):
        layouts.append("go")
        tool = tool or "go-work"

    cargo_txt = _read_safe(repo, repo / "Cargo.toml")
    if cargo_txt:
        try:
            if isinstance(tomllib.loads(cargo_txt).get("workspace"), dict):
                layouts.append("rust")
                tool = tool or "cargo-workspace"
        except tomllib.TOMLDecodeError:
            pass

    py_txt = _read_safe(repo, repo / "pyproject.toml")
    if py_txt:
        try:
            py_data = tomllib.loads(py_txt)
            uv_sec = (py_data.get("tool") or {}).get("uv") if isinstance(py_data.get("tool"), dict) else None
            if isinstance(uv_sec, dict) and uv_sec.get("workspace"):
                layouts.append("python")
                tool = tool or "uv-workspace"
        except tomllib.TOMLDecodeError:
            pass

    candidates: list[str] = []
    for parent in SUBPROJECT_PARENTS:
        pdir = repo / parent
        if pdir.is_symlink() or not pdir.is_dir():
            continue
        for child in sorted(pdir.iterdir()):
            if child.is_symlink() or not child.is_dir() or child.name.startswith("."):
                continue
            if any(_safe_in_repo_file(repo, child / m) for m in SUBPROJECT_MANIFESTS):
                candidates.append(child.relative_to(repo).as_posix())

    if sum(1 for c in candidates if _safe_in_repo_file(repo, repo / c / "go.mod")) >= 2 and "go" not in layouts:
        layouts.append("go")
        tool = tool or "go-multimodule"
    if sum(1 for c in candidates if _safe_in_repo_file(repo, repo / c / "pyproject.toml")) >= 2 and "python" not in layouts:
        layouts.append("python")
        tool = tool or "python-multipackage"

    return {"detected": bool(layouts or len(candidates) >= 2), "tool": tool, "layouts": sorted(set(layouts)), "candidates": candidates[:25]}


def _detect_ai_files_and_collisions(repo: pathlib.Path) -> tuple[list[str], list[str]]:
    """Finds AI instruction/rule/skill files and flags Day-0 collisions against reserved pack skills."""
    ai_files: set[str] = set()
    for rel in ("AGENTS.md", "CLAUDE.md", "GEMINI.md", ".cursorrules", ".windsurfrules", ".mcp.json", ".github/copilot-instructions.md"):
        if (repo / rel).is_file():
            ai_files.add(rel)
    for dir_rel in (".claude/rules", ".claude/skills", ".cursor/rules", ".github/instructions", ".windsurf/rules"):
        d = repo / dir_rel
        if d.is_dir() and not d.is_symlink():
            ai_files.add(f"{dir_rel}/")

    for dirpath, dirnames, filenames in os.walk(repo, followlinks=False):
        cur = pathlib.Path(dirpath)
        rel_dir = cur.relative_to(repo)
        depth = 0 if rel_dir == pathlib.Path(".") else len(rel_dir.parts)
        dirnames[:] = (
            sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".") and not (cur / d).is_symlink())
            if depth < 3
            else []
        )
        if depth > 0 and "AGENTS.md" in filenames and not (cur / "AGENTS.md").is_symlink():
            ai_files.add((rel_dir / "AGENTS.md").as_posix())

    reserved = _load_reserved_skills()
    collisions: list[str] = []
    for skills_root in (repo / "skills", repo / ".claude" / "skills"):
        if not skills_root.is_dir() or skills_root.is_symlink():
            continue
        for child in sorted(skills_root.iterdir()):
            if child.is_dir() and not child.is_symlink() and child.name in reserved:
                collisions.append(f"{child.relative_to(repo).as_posix()} collides with pack skill '{child.name}'")
    return sorted(ai_files), collisions


def _detect_tier_c_warnings(repo: pathlib.Path) -> list[dict[str, str]]:
    """Surfaces early fail-closed warnings for ~5% rare Tier-C build/hardware edge cases."""
    warnings: list[dict[str, str]] = []
    if any(_safe_in_repo_file(repo, repo / f) for f in ("WORKSPACE", "WORKSPACE.bazel", "MODULE.bazel", "BUILD.bazel")):
        warnings.append({"code": "TIER_C_BAZEL", "message": "Detected Bazel workspace. Provide a custom .factory/Dockerfile.customer or use ci-only."})
    if _safe_in_repo_file(repo, repo / "flake.nix"):
        warnings.append({"code": "TIER_C_NIX", "message": "Detected Nix flake.nix. Provide a custom .factory/Dockerfile.customer or use ci-only."})
    if any(repo.glob("*.xcodeproj")) or any(repo.glob("*.xcworkspace")):
        warnings.append({"code": "TIER_C_XCODE", "message": "Detected macOS/iOS Xcode project. Linux containers cannot compile Xcode; use ci-only."})
    if _safe_in_repo_file(repo, repo / "CMakeLists.txt") or _safe_in_repo_file(repo, repo / "meson.build"):
        warnings.append({"code": "TIER_C_NATIVE_CPP", "message": "Detected CMake/Meson native C/C++ build. Author an explicit .factory/Dockerfile.customer."})
    df_text = _read_safe(repo, repo / "Dockerfile").lower()
    if "nvidia/cuda" in df_text or "rocm/" in df_text:
        warnings.append({"code": "TIER_C_GPU_CUDA", "message": "Detected CUDA/ROCm base image. Declare GPU tests under not_verifiable_in_sandbox."})
    if "@Library" in _read_safe(repo, repo / "Jenkinsfile"):
        warnings.append({"code": "TIER_C_JENKINS_SHARED_LIB", "message": "Detected Jenkins @Library. Engineering Lead must confirm build/test commands."})
    return warnings


def scan_tier_a_signals(repo_dir: pathlib.Path) -> dict[str, Any]:
    """Runs the universal <2s Tier-A structural probe on repo_dir and returns a JSON-safe report."""
    repo = repo_dir.resolve()
    git_dir = _resolve_git_dir(repo)
    remote_host, git_support_tier = _parse_origin_host(repo, git_dir)
    monorepo = _detect_five_monorepo_layouts(repo)
    ai_files, skill_collisions = _detect_ai_files_and_collisions(repo)
    tier_c = _detect_tier_c_warnings(repo)

    heads_dir = (git_dir / "refs" / "heads") if git_dir else None
    branches_present = sorted(p.name for p in heads_dir.iterdir() if p.is_file()) if heads_dir and heads_dir.is_dir() else []
    release_tools = [
        lbl
        for cond, lbl in (
            ((repo / ".changeset").is_dir(), "changesets"),
            (bool(_safe_in_repo_file(repo, repo / "release-please-config.json")), "release-please"),
            (any(repo.glob(".releaserc*")), "semantic-release"),
        )
        if cond
    ]

    wf_dir = repo / ".github" / "workflows"
    ci_pointers = sorted(p.relative_to(repo).as_posix() for p in wf_dir.glob("*.y*ml") if _safe_in_repo_file(repo, p)) if wf_dir.is_dir() else []
    ci_pointers.extend(f for f in (".gitlab-ci.yml", "Jenkinsfile", "azure-pipelines.yml", "azure-pipelines.yaml") if _safe_in_repo_file(repo, repo / f))
    task_wrappers = [f for f in ("Makefile", "justfile", "Taskfile.yml", "Taskfile.yaml", "tox.ini", "noxfile.py") if _safe_in_repo_file(repo, repo / f)]

    version_pins: dict[str, str] = {}
    for fname, label in VERSION_PIN_FILES:
        first_line = next((ln.strip() for ln in _read_safe(repo, repo / fname).splitlines() if ln.strip() and not ln.strip().startswith("#")), "")
        if first_line:
            version_pins[label] = first_line[:80]
    for kind, val in GO_VER_RE.findall(_read_safe(repo, repo / "go.mod")):
        version_pins[f"go_{kind}"] = val

    pkg_script_keys: list[str] = []
    pkg_txt = _read_safe(repo, repo / "package.json")
    if pkg_txt:
        try:
            pkg = json.loads(pkg_txt)
            if isinstance(pkg, dict):
                if isinstance(pkg.get("scripts"), dict):
                    pkg_script_keys = sorted(str(k) for k in pkg["scripts"].keys())[:30]
                if isinstance(pkg.get("packageManager"), str):
                    version_pins["packageManager"] = pkg["packageManager"][:80]
                if isinstance(pkg.get("engines"), dict):
                    for ek, ev in pkg["engines"].items():
                        version_pins[f"engine_{ek}"] = str(ev)[:40]
        except json.JSONDecodeError:
            pass

    private_registries = [rel for rel in PRIVATE_REGISTRY_FILES if _safe_in_repo_file(repo, repo / rel)]
    env_example_keys = sorted({
        m.group(1)
        for ef in (".env.example", ".env.sample", ".env.template")
        for line in _read_safe(repo, repo / ef).splitlines()
        if (m := ENV_KEY_RE.match(line))
    })
    local_services = [c for c in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml") if _safe_in_repo_file(repo, repo / c)]
    for mf in ("package.json", "pyproject.toml", "pom.xml", "build.gradle", "build.gradle.kts", "go.mod"):
        if "testcontainers" in _read_safe(repo, repo / mf).lower():
            local_services.append(f"testcontainers:{mf}")

    return {
        "remote_host": remote_host,
        "git_support_tier": git_support_tier,
        "branches_present": branches_present,
        "has_submodules": bool(_safe_in_repo_file(repo, repo / ".gitmodules")),
        "has_git_lfs": "filter=lfs" in _read_safe(repo, repo / ".gitattributes"),
        "has_commitlint": any(repo.glob("commitlint.config.*")) or bool(_safe_in_repo_file(repo, repo / ".commitlintrc.json")),
        "release_automation": release_tools,
        "monorepo": monorepo,
        "ci_workflow_pointers": sorted(set(ci_pointers)),
        "task_wrappers": task_wrappers,
        "package_json_script_keys": pkg_script_keys,
        "version_pins": version_pins,
        "private_registries": private_registries,
        "env_example_keys": env_example_keys,
        "local_services": sorted(set(local_services)),
        "ai_files": ai_files,
        "skill_collisions": skill_collisions,
        "tier_c_warnings": tier_c,
    }
