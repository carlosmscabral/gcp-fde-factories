"""Pinned, dependency-ordered Dockerfile recipe renderer for Layer 3 brownfield overlays.

Enforces three security and correctness invariants:
1. Strict allowlist of known binaries with real smoke checks (zero arbitrary shell interpolation).
2. Strict digest-pinned base image regex (literal FROM without overridable ARG).
3. Topological dependency ordering so base runtimes (e.g. node) install before global tools (e.g. eslint).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

DIGEST_IMAGE_RE = re.compile(r"^[a-z0-9][a-z0-9./:_-]*@sha256:[0-9a-f]{64}$")


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
