"""Pinned, dependency-ordered Dockerfile recipe renderer for Layer 3 brownfield overlays.

Enforces three security and correctness invariants:
1. Strict allowlist of known binaries with real smoke checks (zero arbitrary shell interpolation).
2. Strict digest-pinned base image regex (literal FROM without overridable ARG).
3. Topological dependency ordering so base runtimes (e.g. node) install before global tools (e.g. eslint).
"""
from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass
from typing import Any

DIGEST_IMAGE_RE = re.compile(r"^[a-z0-9][a-z0-9./:_-]*@sha256:[0-9a-f]{64}$")
SHELL_PIPE_RE = re.compile(r"\b(curl|wget)\b[^|\n]*\|\s*(sudo\s+)?(ba|da|z)?sh\b", re.IGNORECASE)


@dataclass(frozen=True)
class BinaryRecipe:
    """Pinned container installation recipe with prerequisite binaries and smoke verification."""

    install_cmd: str
    smoke_cmd: str
    requires: tuple[str, ...] = ()
    env_lines: tuple[str, ...] = ()


# Pinned toolchain recipes targeting Debian-based Scion harness or factory base images (UID 1000 scion).
INSTALL_RECIPES: dict[str, BinaryRecipe] = {
    "poetry": BinaryRecipe(
        install_cmd="pip install --no-cache-dir poetry==2.1.1",
        smoke_cmd="poetry --version",
    ),
    "ruff": BinaryRecipe(
        install_cmd="pip install --no-cache-dir ruff==0.9.9",
        smoke_cmd="ruff --version",
    ),
    "mypy": BinaryRecipe(
        install_cmd="pip install --no-cache-dir mypy==1.15.0",
        smoke_cmd="mypy --version",
    ),
    "node": BinaryRecipe(
        install_cmd="apt-get update && apt-get install -y --no-install-recommends nodejs npm && rm -rf /var/lib/apt/lists/*",
        smoke_cmd="node --version && npm --version",
    ),
    "npm": BinaryRecipe(
        install_cmd="npm --version >/dev/null",
        smoke_cmd="npm --version",
        requires=("node",),
    ),
    "pnpm": BinaryRecipe(
        install_cmd="npm install -g pnpm@10.6.0",
        smoke_cmd="pnpm --version",
        requires=("node",),
    ),
    "eslint": BinaryRecipe(
        install_cmd="npm install -g eslint@9.22.0",
        smoke_cmd="eslint --version",
        requires=("node",),
    ),
    "playwright": BinaryRecipe(
        install_cmd="pip install --no-cache-dir playwright==1.50.0 && playwright install --with-deps chromium && chmod -R a+rX /opt/playwright-browsers",
        smoke_cmd="playwright --version",
        env_lines=("ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers",),
    ),
    "playwright-node": BinaryRecipe(
        install_cmd="npm install -g @playwright/test@1.50.0 && npx playwright install --with-deps chromium && chmod -R a+rX /opt/playwright-browsers",
        smoke_cmd="npx playwright --version",
        requires=("node",),
        env_lines=("ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers",),
    ),
    "go": BinaryRecipe(
        install_cmd="apt-get update && apt-get install -y --no-install-recommends golang-go && rm -rf /var/lib/apt/lists/*",
        smoke_cmd="go version",
    ),
    "jdk": BinaryRecipe(
        install_cmd="apt-get update && apt-get install -y --no-install-recommends default-jdk-headless && rm -rf /var/lib/apt/lists/*",
        smoke_cmd="java -version",
    ),
    "mvn": BinaryRecipe(
        install_cmd="apt-get update && apt-get install -y --no-install-recommends maven && rm -rf /var/lib/apt/lists/*",
        smoke_cmd="mvn --version",
        requires=("jdk",),
    ),
}


def resolve_recipe_order(binaries: list[str]) -> list[str]:
    """Validates binary names against INSTALL_RECIPES and returns topologically sorted names."""
    ordered: list[str] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visited:
            return
        if name in visiting:
            raise ValueError(f"Circular recipe dependency detected involving '{name}'.")
        if name not in INSTALL_RECIPES:
            raise ValueError(
                f"Unsupported binary '{name}' in Dockerfile recipe allowlist. Allowed: {sorted(INSTALL_RECIPES)}."
            )
        visiting.add(name)
        for dep in INSTALL_RECIPES[name].requires:
            visit(dep)
        visiting.remove(name)
        visited.add(name)
        ordered.append(name)

    for raw in binaries:
        if raw:
            visit(raw)
    return ordered


def render_conditional_dockerfile(
    pack_image_ref: str,
    missing_binaries: list[str],
    tester_only: bool = False,
    allow_local_stage_ref: bool = False,
) -> str | None:
    """Renders a digest-pinned Layer 3 derived Dockerfile when missing_binaries is non-empty."""
    ordered = resolve_recipe_order(missing_binaries)
    if not ordered:
        return None
    if not allow_local_stage_ref and not DIGEST_IMAGE_RE.match(pack_image_ref):
        raise ValueError(
            f"Base image reference '{pack_image_ref}' must be digest-pinned (<registry>/<image>@sha256:<64-hex>)."
        )

    role_note = "test-engineer and qa-tester roles only" if tester_only else "project default harnesses"
    env_lines: list[str] = []
    install_lines: list[str] = []
    smoke_checks: list[str] = []
    for name in ordered:
        recipe = INSTALL_RECIPES[name]
        for env_line in recipe.env_lines:
            if env_line not in env_lines:
                env_lines.append(env_line)
        install_lines.append(f"RUN {recipe.install_cmd}")
        smoke_checks.append(recipe.smoke_cmd)

    lines = [
        f"# Conditional Layer 3 derived customer image ({role_note}).",
        "# Inherits digest-pinned pack/harness base without modifying Layers 0-2.",
        f"FROM {pack_image_ref}",
        "",
        "USER root",
        *env_lines,
        *install_lines,
        "",
        "# Return to unprivileged Scion runtime user (UID 1000) and verify every added binary.",
        "USER scion",
        f"RUN {' && '.join(smoke_checks)}",
        "",
    ]
    return "\n".join(lines)


def validate_customer_dockerfile(
    dockerfile_path: pathlib.Path,
    *,
    strict: bool = False,
) -> dict[str, Any]:
    """Validates any agent-authored .factory/Dockerfile.customer with advisory-default Day-0 findings (ADR-015).

    Structural errors (missing file or missing FROM) always fail. Security findings
    (unpinned base image, non-root USER, shell-pipe installs, or missing post-USER smoke
    check) emit named warnings with exit 0 by default, and fail only when strict=True.
    """
    structural_errors: list[str] = []
    advisory_findings: list[dict[str, str]] = []

    if not dockerfile_path.is_file():
        structural_errors.append(f"Dockerfile does not exist: {dockerfile_path}")
        return {
            "ok": False,
            "mode": "strict" if strict else "advisory",
            "structural_errors": structural_errors,
            "advisory_findings": advisory_findings,
        }

    raw_lines = [
        ln.strip()
        for ln in dockerfile_path.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    stages: list[list[str]] = []
    for ln in raw_lines:
        if ln.upper().startswith("FROM "):
            stages.append([ln])
        elif stages:
            stages[-1].append(ln)

    if not stages:
        structural_errors.append("Dockerfile missing FROM instruction.")
        return {
            "ok": False,
            "mode": "strict" if strict else "advisory",
            "structural_errors": structural_errors,
            "advisory_findings": advisory_findings,
        }

    final_stage = stages[-1]
    base_tokens = final_stage[0].split()
    base_ref = next((tok for tok in base_tokens[1:] if not tok.startswith("--")), "")
    if not DIGEST_IMAGE_RE.match(base_ref):
        advisory_findings.append({
            "code": "BASE_IMAGE_NOT_DIGEST_PINNED",
            "severity": "medium",
            "message": f"Final stage FROM '{base_ref}' is not digest-pinned (@sha256:<64-hex>).",
        })

    for ln in raw_lines:
        if ln.upper().startswith("RUN ") and SHELL_PIPE_RE.search(ln):
            advisory_findings.append({
                "code": "SHELL_PIPE_INSTALL_DETECTED",
                "severity": "high",
                "message": f"Detected shell-pipe installer in '{ln[:100]}'. Prefer pinned package manager installs.",
            })

    last_user_idx = -1
    last_user_val = ""
    for idx, ln in enumerate(final_stage):
        if ln.upper().startswith("USER ") and len(ln.split(None, 1)) > 1:
            last_user_idx = idx
            last_user_val = ln.split(None, 1)[1].strip()

    user_name = last_user_val.split(":", 1)[0].strip().lower()
    if last_user_idx == -1 or "$" in last_user_val or user_name in ("root", "0", ""):
        advisory_findings.append({
            "code": "FINAL_STAGE_NON_ROOT_USER_MISSING",
            "severity": "high",
            "message": "Final stage must end with a literal non-root USER (such as 'USER scion').",
        })
    else:
        has_smoke = any(ln.upper().startswith("RUN ") for ln in final_stage[last_user_idx + 1 :])
        if not has_smoke:
            advisory_findings.append({
                "code": "MISSING_POST_USER_SMOKE_CHECK",
                "severity": "low",
                "message": "Add a non-root smoke check RUN command after the final USER instruction.",
            })

    ok = (not structural_errors) and (not strict or not advisory_findings)
    return {
        "ok": ok,
        "mode": "strict" if strict else "advisory",
        "structural_errors": structural_errors,
        "advisory_findings": advisory_findings,
    }
