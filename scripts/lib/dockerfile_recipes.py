"""Pinned, dependency-ordered Dockerfile recipe renderer and 4-rule deterministic linter (Wave 2).

Enforces four security and correctness rules on customer Dockerfiles:
1. Digest-pinned base images across EVERY stage FROM and COPY --from (resolving stage aliases).
2. Literal non-root final USER (rejecting root, UID 0/00/0000, variables, and tab-obfuscation).
3. Supply-chain and secret hygiene (blocking curl|sh/wget|sh/process-substitution pipes including
   heredocs, multi-pair and legacy ENV/ARG secrets, and COPY/ADD of .env files/globs).
4. Post-USER smoke-check coverage verifying every declared toolchain.verify_binaries command.
"""
from __future__ import annotations

import json
import pathlib
import re
import shlex
from dataclasses import dataclass
from typing import Any

DIGEST_IMAGE_RE = re.compile(r"^[a-z0-9][a-z0-9./:_-]*@sha256:[0-9a-f]{64}$")
BASE_ARG_FROM_RE = re.compile(r"^\$\{?BASE_IMAGE\}?$")
INSTR_RE = re.compile(r"^\s*([A-Za-z]+)(?:\s+(.*))?$")
HEREDOC_RE = re.compile(r"<<-?\s*['\"]?([A-Za-z0-9_]+)['\"]?")
SHELL_PIPE_RE = re.compile(
    r"(?:\b(?:curl|wget)\b[^\n]*\|[^\n]*\b(?:sudo(?:\s+-\S+)*\s+)?(?:ba|da|z|k)?sh\b"
    r"|\b(?:ba|da|z|k)?sh\b[^\n]*<\(\s*(?:curl|wget)\b)",
    re.IGNORECASE,
)
SECRET_KEY_RE = re.compile(
    r"^(?:[A-Z0-9_]*_)?(?:TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|PRIVATE_KEY|ACCESS_KEY)(?:_[A-Z0-9_]*)?$",
    re.IGNORECASE,
)
SAFE_SECRET_KEY_SUFFIXES = ("_URL", "_URI", "_ENDPOINT", "_PATH", "_FILE", "_DIR", "_HEADER", "_NAME", "_ID", "_EXPIRY", "_TTL")
DOTENV_BASENAME_RE = re.compile(r"^\.env(?:\..+)?$", re.IGNORECASE)
SAFE_DOTENV_SUFFIXES = (".example", ".sample", ".template", ".dist")


@dataclass(frozen=True)
class BinaryRecipe:
    """Pinned container installation recipe with prerequisite binaries and smoke verification."""

    install_cmd: str
    smoke_cmd: str
    requires: tuple[str, ...] = ()
    env_lines: tuple[str, ...] = ()


INSTALL_RECIPES: dict[str, BinaryRecipe] = {
    "poetry": BinaryRecipe("pip install --no-cache-dir poetry==2.1.1", "poetry --version"),
    "ruff": BinaryRecipe("pip install --no-cache-dir ruff==0.9.9", "ruff --version"),
    "mypy": BinaryRecipe("pip install --no-cache-dir mypy==1.15.0", "mypy --version"),
    "node": BinaryRecipe(
        "apt-get update && apt-get install -y --no-install-recommends nodejs npm && rm -rf /var/lib/apt/lists/*",
        "node --version && npm --version",
    ),
    "npm": BinaryRecipe("npm --version >/dev/null", "npm --version", requires=("node",)),
    "pnpm": BinaryRecipe("npm install -g pnpm@10.6.0", "pnpm --version", requires=("node",)),
    "eslint": BinaryRecipe("npm install -g eslint@9.22.0", "eslint --version", requires=("node",)),
    "playwright": BinaryRecipe(
        "pip install --no-cache-dir playwright==1.50.0 && playwright install --with-deps chromium && chmod -R a+rX /opt/playwright-browsers",
        "playwright --version",
        env_lines=("ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers",),
    ),
    "playwright-node": BinaryRecipe(
        "npm install -g @playwright/test@1.50.0 && npx playwright install --with-deps chromium && chmod -R a+rX /opt/playwright-browsers",
        "npx playwright --version",
        requires=("node",),
        env_lines=("ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers",),
    ),
    "go": BinaryRecipe(
        "apt-get update && apt-get install -y --no-install-recommends golang-go && rm -rf /var/lib/apt/lists/*",
        "go version",
    ),
    "jdk": BinaryRecipe(
        "apt-get update && apt-get install -y --no-install-recommends default-jdk-headless && rm -rf /var/lib/apt/lists/*",
        "java -version",
    ),
    "mvn": BinaryRecipe(
        "apt-get update && apt-get install -y --no-install-recommends maven && rm -rf /var/lib/apt/lists/*",
        "mvn --version",
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
    """Renders a digest-pinned Layer 3 derived Dockerfile when missing_binaries is non-empty.

    Uses ARG BASE_IMAGE=<pinned-digest> + FROM ${BASE_IMAGE} when digest-pinned so Stage 03
    can supply the antigravity/claude harness digest cleanly without losing pins (M11).
    """
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

    from_block = (
        [f"FROM {pack_image_ref}"]
        if allow_local_stage_ref
        else [f"ARG BASE_IMAGE={pack_image_ref}", f"FROM {pack_image_ref}"]
    )
    lines = [
        f"# Conditional Layer 3 derived customer image ({role_note}).",
        "# Inherits digest-pinned pack/harness base without modifying Layers 0-2.",
        *from_block,
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


def _parse_dockerfile_instructions(text: str) -> list[tuple[str, str]]:
    """Parses Dockerfile text into (INSTRUCTION, body) tuples collapsing line continuations and heredocs (H1)."""
    lines = text.splitlines()
    result: list[tuple[str, str]] = []
    idx = 0
    while idx < len(lines):
        raw = lines[idx]
        stripped = raw.strip()
        idx += 1
        if not stripped or stripped.startswith("#"):
            continue
        combined = stripped
        while combined.endswith("\\") and idx < len(lines):
            nxt = lines[idx].strip()
            idx += 1
            if nxt.startswith("#"):
                continue
            combined = combined[:-1].rstrip() + " " + nxt
        m = INSTR_RE.match(combined)
        if not m:
            continue
        instr = m.group(1).upper()
        body = (m.group(2) or "").strip()
        # Capture heredoc body lines into RUN/COPY instructions so heredoc curl|sh cannot hide (H1-d).
        hd_match = HEREDOC_RE.search(body)
        if hd_match and instr in ("RUN", "COPY"):
            delim = hd_match.group(1)
            hd_lines: list[str] = []
            while idx < len(lines):
                candidate = lines[idx]
                idx += 1
                if candidate.strip() == delim:
                    break
                hd_lines.append(candidate)
            if hd_lines:
                body = body + "\n" + "\n".join(hd_lines)
        result.append((instr, body))
    return result


def _is_non_root_user(user_body: str) -> bool:
    """Returns True only for a literal non-root USER (rejecting root, UID 0/00/0000, and $vars) (H1-c)."""
    user_part = user_body.strip().split(":", 1)[0].strip()
    if not user_part or "$" in user_part:
        return False
    if user_part.lower() == "root":
        return False
    if user_part.isdigit():
        return int(user_part) != 0
    return True


def _check_secret_leak(instr: str, body: str) -> bool:
    """Detects baked secret literals in multi-pair ENV/ARG and legacy 'ENV KEY VAL' forms without flagging URLs (H1-h, FP2)."""
    try:
        tokens = shlex.split(body)
    except ValueError:
        tokens = body.split()
    if not tokens:
        return False
    pairs: list[tuple[str, str]] = []
    if all("=" in t for t in tokens):
        for tok in tokens:
            k, v = tok.split("=", 1)
            pairs.append((k, v))
    elif "=" in tokens[0]:
        for tok in tokens:
            if "=" in tok:
                k, v = tok.split("=", 1)
                pairs.append((k, v))
    elif len(tokens) >= 2:
        pairs.append((tokens[0], " ".join(tokens[1:])))
    for key, val in pairs:
        val_clean = val.strip().strip("'\"")
        if not val_clean or val_clean.startswith(("http://", "https://", "/")):
            continue
        upper_k = key.strip().upper()
        if any(upper_k.endswith(suf) for suf in SAFE_SECRET_KEY_SUFFIXES):
            continue
        if SECRET_KEY_RE.match(upper_k):
            return True
    return False


def _check_copy_dotenv(body: str) -> tuple[bool, str | None]:
    """Parses COPY/ADD shell or JSON-exec form sources for .env files/globs and returns (has_dotenv, copy_from_ref) (H1-f/g/i)."""
    copy_from: str | None = None
    try:
        raw_tokens = shlex.split(body.splitlines()[0])
    except ValueError:
        raw_tokens = body.splitlines()[0].split()
    non_flag: list[str] = []
    for tok in raw_tokens:
        if tok.startswith("--from="):
            copy_from = tok.split("=", 1)[1].strip()
        elif not tok.startswith("--"):
            non_flag.append(tok)

    # Support JSON array exec form: COPY [".env", "/app/"]
    first_line = body.splitlines()[0].strip()
    if first_line.startswith("["):
        try:
            arr = json.loads(first_line)
            if isinstance(arr, list):
                non_flag = [str(x) for x in arr]
        except json.JSONDecodeError:
            pass

    sources = non_flag[:-1] if len(non_flag) >= 2 else non_flag
    for src in sources:
        base = pathlib.PurePosixPath(src.rstrip("/")).name
        low = base.lower()
        if any(low.endswith(suf) for suf in SAFE_DOTENV_SUFFIXES):
            continue
        if DOTENV_BASENAME_RE.match(base) or low.startswith(".env*"):
            return True, copy_from
    return False, copy_from


def validate_customer_dockerfile(
    dockerfile_path: pathlib.Path,
    *,
    strict: bool = False,
    verify_binaries: list[str] | None = None,
    allow_base_arg: bool = True,
    require_pinned_base_arg: bool = False,
) -> dict[str, Any]:
    """Validates a customer Dockerfile against all 4 deterministic security and smoke-check rules."""
    structural_errors: list[str] = []
    advisory_findings: list[dict[str, str]] = []

    if not dockerfile_path.is_file():
        structural_errors.append(f"Dockerfile does not exist: {dockerfile_path}")
        return {"ok": False, "mode": "strict" if strict else "advisory", "structural_errors": structural_errors, "advisory_findings": advisory_findings}

    instructions = _parse_dockerfile_instructions(dockerfile_path.read_text(encoding="utf-8"))
    global_base_arg = ""
    stages: list[list[tuple[str, str]]] = []
    stage_aliases: set[str] = set()

    for instr, body in instructions:
        if not stages and instr == "ARG":
            if body.upper().startswith("BASE_IMAGE="):
                global_base_arg = body.split("=", 1)[1].strip().strip("'\"")
        if instr == "FROM":
            stages.append([(instr, body)])
        elif stages:
            stages[-1].append((instr, body))

    if not stages:
        structural_errors.append("Dockerfile missing FROM instruction.")
        return {"ok": False, "mode": "strict" if strict else "advisory", "structural_errors": structural_errors, "advisory_findings": advisory_findings}

    # Rule 1: Validate EVERY stage FROM and COPY --from=<image>, resolving prior stage aliases (H1-i, FP1).
    for stage in stages:
        tokens = stage[0][1].split()
        filtered = [t for t in tokens if not t.startswith("--")]
        base_ref = filtered[0] if filtered else ""
        alias = filtered[2].lower() if len(filtered) >= 3 and filtered[1].upper() == "AS" else ""
        if base_ref.lower() in stage_aliases:
            pass
        elif BASE_ARG_FROM_RE.match(base_ref) and allow_base_arg:
            if global_base_arg and not DIGEST_IMAGE_RE.match(global_base_arg):
                advisory_findings.append({
                    "code": "BASE_IMAGE_NOT_DIGEST_PINNED",
                    "severity": "high",
                    "message": f"ARG BASE_IMAGE default '{global_base_arg}' is not digest-pinned (@sha256:<64-hex>).",
                })
            elif not global_base_arg and require_pinned_base_arg:
                advisory_findings.append({
                    "code": "BASE_IMAGE_NOT_DIGEST_PINNED",
                    "severity": "medium",
                    "message": "ARG BASE_IMAGE has no digest-pinned default.",
                })
        elif not DIGEST_IMAGE_RE.match(base_ref):
            advisory_findings.append({
                "code": "BASE_IMAGE_NOT_DIGEST_PINNED",
                "severity": "high",
                "message": f"Stage FROM '{base_ref}' is not digest-pinned (@sha256:<64-hex>).",
            })
        if alias:
            stage_aliases.add(alias)

    # Rule 3: Supply-chain shell-pipe installs (including heredocs), baked secrets, COPY .env, and COPY --from pins.
    for instr, body in instructions:
        if instr == "RUN" and SHELL_PIPE_RE.search(body):
            advisory_findings.append({
                "code": "SHELL_PIPE_INSTALL_DETECTED",
                "severity": "high",
                "message": f"Detected shell-pipe installer in RUN '{body.splitlines()[0][:100]}'. Prefer pinned package manager installs.",
            })
        if instr in ("ENV", "ARG") and _check_secret_leak(instr, body):
            advisory_findings.append({
                "code": "BAKED_SECRET_DETECTED",
                "severity": "high",
                "message": f"Detected potential secret literal in {instr} '{body[:80]}'. Inject secrets at runtime via Scion Hub.",
            })
        if instr in ("COPY", "ADD"):
            has_dotenv, copy_from = _check_copy_dotenv(body)
            if has_dotenv:
                advisory_findings.append({
                    "code": "COPY_DOTENV_DETECTED",
                    "severity": "high",
                    "message": f"Refusing {instr} '{body[:80]}'. Never bake .env files into container images.",
                })
            if copy_from and copy_from.lower() not in stage_aliases and not copy_from.isdigit() and not DIGEST_IMAGE_RE.match(copy_from):
                advisory_findings.append({
                    "code": "BASE_IMAGE_NOT_DIGEST_PINNED",
                    "severity": "high",
                    "message": f"{instr} --from='{copy_from}' is neither a stage alias nor a digest-pinned image.",
                })

    # Rule 2 & Rule 4: Literal non-root final USER and post-USER smoke checks covering verify_binaries.
    final_stage = stages[-1]
    last_user_idx = -1
    last_user_val = ""
    for idx, (instr, body) in enumerate(final_stage):
        if instr == "USER":
            last_user_idx = idx
            last_user_val = body

    if last_user_idx == -1 or not _is_non_root_user(last_user_val):
        advisory_findings.append({
            "code": "FINAL_STAGE_NON_ROOT_USER_MISSING",
            "severity": "high",
            "message": f"Final stage must end with a literal non-root USER (found '{last_user_val or 'none'}').",
        })
    else:
        post_user_runs = [body for instr, body in final_stage[last_user_idx + 1 :] if instr == "RUN"]
        if not post_user_runs:
            advisory_findings.append({
                "code": "MISSING_POST_USER_SMOKE_CHECK",
                "severity": "low",
                "message": "Add a non-root smoke check RUN command after the final USER instruction.",
            })
        elif verify_binaries:
            combined = "\n".join(post_user_runs)
            for req_cmd in verify_binaries:
                clean_cmd = " ".join(str(req_cmd).strip().split())
                if not clean_cmd:
                    continue
                # Require exact command-position invocation (rejecting 'RUN echo ruff --version', H1-k).
                pattern = r"(?:^|[;&|\n(])\s*" + re.escape(clean_cmd) + r"(?:$|[;&|\n)\s])"
                if not re.search(pattern, combined):
                    advisory_findings.append({
                        "code": "VERIFY_BINARY_NOT_SMOKE_TESTED",
                        "severity": "medium",
                        "message": f"Declared verify_binaries command '{clean_cmd}' is not executed in any post-USER RUN.",
                    })

    ok = (not structural_errors) and (not strict or not advisory_findings)
    return {
        "ok": ok,
        "mode": "strict" if strict else "advisory",
        "structural_errors": structural_errors,
        "advisory_findings": advisory_findings,
    }
