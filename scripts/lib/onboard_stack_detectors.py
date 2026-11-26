"""Extended brownfield stack, frontend, deploy-target, and monorepo detectors (ADR-016).

Complements scripts/lib/onboard_parsers.py without exceeding module size limits.
Uses pure zero-token filesystem inspection to inform pack recommendation, SEP role curation,
and generic-pack interview depth.
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from scripts.lib.onboard_parsers import read_text_safe

FRONTEND_PACKAGES = {
    "react": "react",
    "next": "nextjs",
    "vite": "vite",
    "@angular/core": "angular",
    "vue": "vue",
    "svelte": "svelte",
}

MONOREPO_MARKERS = (
    ("nx.json", "nx"),
    ("turbo.json", "turbo"),
    ("pnpm-workspace.yaml", "pnpm-workspace"),
    ("lerna.json", "lerna"),
)

SUBPROJECT_MANIFESTS = ("package.json", "pyproject.toml", "go.mod", "Cargo.toml", "pom.xml", "build.gradle", "build.gradle.kts")
SUBPROJECT_PARENT_DIRS = ("apps", "services", "packages", "libs", "modules")


def _detect_frontend_frameworks(repo: pathlib.Path) -> list[str]:
    """Inspects root and first-level app package.json files for frontend UI frameworks."""
    found: set[str] = set()
    candidates = [repo / "package.json"]
    for parent in ("apps", "packages", "frontend", "web"):
        pdir = repo / parent
        if pdir.is_symlink() or not pdir.is_dir():
            continue
        if (pdir / "package.json").is_file() and not (pdir / "package.json").is_symlink():
            candidates.append(pdir / "package.json")
        for child in sorted(pdir.iterdir()):
            if not child.is_symlink() and child.is_dir() and (child / "package.json").is_file():
                candidates.append(child / "package.json")

    for pkg_path in candidates:
        if not pkg_path.is_file():
            continue
        try:
            pkg = json.loads(read_text_safe(pkg_path))
        except json.JSONDecodeError:
            continue
        if not isinstance(pkg, dict):
            continue
        deps: set[str] = set()
        for section in ("dependencies", "devDependencies"):
            block = pkg.get(section)
            if isinstance(block, dict):
                deps.update(str(k).lower() for k in block.keys())
        for dep_name, label in FRONTEND_PACKAGES.items():
            if dep_name in deps:
                found.add(label)
    return sorted(found)


def _detect_monorepo(repo: pathlib.Path) -> dict[str, Any]:
    """Detects workspace managers and candidate service subdirectories in brownfield monorepos."""
    tool: str | None = None
    for filename, label in MONOREPO_MARKERS:
        if (repo / filename).is_file():
            tool = label
            break

    candidates: list[str] = []
    for parent in SUBPROJECT_PARENT_DIRS:
        pdir = repo / parent
        if pdir.is_symlink() or not pdir.is_dir():
            continue
        for child in sorted(pdir.iterdir()):
            if child.is_symlink() or not child.is_dir() or child.name.startswith("."):
                continue
            if any((child / m).is_file() for m in SUBPROJECT_MANIFESTS):
                candidates.append(child.relative_to(repo).as_posix())

    pkg_json = repo / "package.json"
    if tool is None and pkg_json.is_file():
        try:
            pkg = json.loads(read_text_safe(pkg_json))
            if isinstance(pkg, dict) and pkg.get("workspaces"):
                tool = "npm-workspaces"
        except json.JSONDecodeError:
            pass

    detected = bool(tool or len(candidates) >= 2)
    return {
        "detected": detected,
        "tool": tool,
        "candidates": candidates[:20],
    }


def _detect_deploy_signals(repo: pathlib.Path, frontend_frameworks: list[str]) -> tuple[list[str], str]:
    """Detects container, Kubernetes, and Cloud Run deployment signals and suggests a deploy_target."""
    signals: set[str] = set()
    if (repo / "Dockerfile").is_file() or any(repo.glob("*/Dockerfile")):
        signals.add("dockerfile")
    if (repo / "docker-compose.yml").is_file() or (repo / "docker-compose.yaml").is_file():
        signals.add("docker-compose")
    if (repo / "cloudbuild.yaml").is_file() or (repo / "cloudbuild.yml").is_file():
        signals.add("cloudbuild")

    for name in ("service.yaml", "cloudrun.yaml", "cloud-run.yaml"):
        if (repo / name).is_file():
            signals.add("cloud-run")
    for wf in (repo / ".github" / "workflows").glob("*.y*ml") if (repo / ".github" / "workflows").is_dir() else []:
        text = read_text_safe(wf)
        if "run deploy" in text or "deploy-cloudrun" in text:
            signals.add("cloud-run")
        if "container clusters get-credentials" in text or "kubectl apply" in text or "helm upgrade" in text:
            signals.add("gke")

    if (repo / "Chart.yaml").is_file() or (repo / "k8s").is_dir() or (repo / "helm").is_dir() or (repo / "manifests").is_dir():
        signals.add("gke")

    if "gke" in signals:
        suggested = "gke"
    elif "cloud-run" in signals or "dockerfile" in signals or frontend_frameworks:
        suggested = "cloud-run"
    else:
        suggested = "none"
    return sorted(signals), suggested


def detect_extended_signals(repo_dir: pathlib.Path) -> dict[str, Any]:
    """Returns extended language, monorepo, frontend, and deploy signals for generic onboarding."""
    repo = repo_dir.resolve()
    extra_stacks: set[str] = set()
    extra_binaries: set[str] = set()
    extra_commands: dict[str, str] = {}

    if (repo / "Cargo.toml").is_file():
        extra_stacks.add("rust")
        extra_binaries.add("cargo")
        extra_commands.setdefault("test", "cargo test")
        extra_commands.setdefault("lint", "cargo clippy -- -D warnings")
        extra_commands.setdefault("build", "cargo build")

    if (repo / "build.gradle").is_file() or (repo / "build.gradle.kts").is_file():
        extra_stacks.add("java")
        extra_binaries.update({"jdk", "gradle"})
        # Avoid mixing Gradle build with Maven test when pom.xml coexists (HC-09).
        if not (repo / "pom.xml").is_file():
            extra_commands.setdefault("test", "./gradlew test")
            extra_commands.setdefault("build", "./gradlew build")

    if (repo / "nx.json").is_file():
        extra_binaries.add("nx")
    if (repo / "turbo.json").is_file():
        extra_binaries.add("turbo")

    monorepo = _detect_monorepo(repo)
    frontend = _detect_frontend_frameworks(repo)
    deploy_signals, suggested_deploy = _detect_deploy_signals(repo, frontend)

    if "dockerfile" in deploy_signals:
        extra_stacks.add("docker")
    if "gke" in deploy_signals:
        extra_stacks.add("kubernetes")
    if "cloud-run" in deploy_signals:
        extra_stacks.add("cloud-run")

    return {
        "extra_stacks": sorted(extra_stacks),
        "extra_binaries": sorted(extra_binaries),
        "extra_commands": extra_commands,
        "frontend_frameworks": frontend,
        "monorepo": monorepo,
        "deploy_signals": deploy_signals,
        "suggested_deploy_target": suggested_deploy,
    }
