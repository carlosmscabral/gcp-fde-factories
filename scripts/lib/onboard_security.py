"""Untrusted workspace hazard scanner and AI instruction divergence detector.

Detects executable workspace metadata (MCP manifests, Claude/Gemini settings hooks,
recursive command keys and non-allowlisted env overrides, symlinked hazards, Git/Husky/
Lefthook/pre-commit hooks, .gemini/.env, and root/workspace package.json lifecycle scripts)
as blocking security hazards with content-addressed SHA-256 fingerprints.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
from typing import Any

HARNESS_SETTINGS_PATHS = (
    ".claude/settings.json",
    ".claude/settings.local.json",
    ".gemini/settings.json",
    ".gemini/settings.local.json",
)
DANGEROUS_SETTINGS_KEYS = frozenset({
    "hooks",
    "apiKeyHelper",
    "statusLine",
    "awsAuthRefresh",
    "awsCredentialExport",
    "otelHeadersHelper",
    "mcpServers",
    "enabledMcpjsonServers",
    "enableAllProjectMcpServers",
    "discoveryCommand",
    "callCommand",
    "mcp",
})
SAFE_SETTINGS_ENV_KEYS = frozenset({
    "LANG",
    "LC_ALL",
    "TERM",
    "TZ",
    "NO_COLOR",
    "FORCE_COLOR",
    "COLORTERM",
    "EDITOR",
    "VISUAL",
})
PACKAGE_LIFECYCLE_HOOKS = (
    "preinstall",
    "install",
    "postinstall",
    "prepare",
    "preprepare",
    "postprepare",
    "prepublish",
    "prepublishOnly",
)
PRECOMMIT_FILES = (".pre-commit-config.yaml", ".pre-commit-config.yml", "lefthook.yml", ".lefthook.yml")
SKIP_WALK_DIRS = frozenset({".git", "node_modules", ".venv", "venv", "vendor", "dist", "build", "target", ".terraform"})
FALLBACK_SETTINGS_KEY_RE = re.compile(
    r"""["'](hooks|apiKeyHelper|statusLine|awsAuthRefresh|awsCredentialExport|otelHeadersHelper|discoveryCommand|callCommand|mcpServers|enabledMcpjsonServers|enableAllProjectMcpServers|ANTHROPIC_|CLAUDE_CODE_|GOOGLE_|HTTP_PROXY|HTTPS_PROXY|NODE_OPTIONS|LD_PRELOAD)["']"""
)


def _resolve_in_repo(repo: pathlib.Path, target: pathlib.Path) -> tuple[pathlib.Path | None, bool]:
    """Resolves symlinks safely, returning (resolved_path, escaped_repo)."""
    repo_root = repo.resolve()
    try:
        resolved = target.resolve()
        resolved.relative_to(repo_root)
        return resolved, False
    except (OSError, ValueError):
        return None, True


def _read_text_safe(path: pathlib.Path) -> str:
    """Reads UTF-8 text safely and returns an empty string on I/O errors."""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _has_dangerous_settings_node(node: Any) -> bool:
    """Walks parsed settings JSON recursively for executable hooks, helper commands, or non-allowlisted env keys."""
    if isinstance(node, dict):
        for key, val in node.items():
            if key in DANGEROUS_SETTINGS_KEYS and val not in (None, False, {}, [], ""):
                return True
            if key == "env" and isinstance(val, dict):
                for env_key in val:
                    if str(env_key).strip().upper() not in SAFE_SETTINGS_ENV_KEYS:
                        return True
            if _has_dangerous_settings_node(val):
                return True
    elif isinstance(node, list):
        return any(_has_dangerous_settings_node(item) for item in node)
    return False


def _inspect_harness_settings(repo: pathlib.Path, rel: str) -> list[str]:
    """Inspects a Claude or Gemini settings JSON file (including symlinks) for executable hooks or env redirects."""
    raw_path = repo / rel
    if not raw_path.exists() and not raw_path.is_symlink():
        return []
    resolved, escaped = _resolve_in_repo(repo, raw_path)
    if escaped:
        return [rel]
    if resolved is None or not resolved.is_file():
        return []
    raw = _read_text_safe(resolved)
    if not raw.strip():
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return [rel] if FALLBACK_SETTINGS_KEY_RE.search(raw) else []
    return [rel] if _has_dangerous_settings_node(parsed) else []


def _inspect_package_json_scripts(repo: pathlib.Path) -> list[str]:
    """Detects executable npm lifecycle scripts in root and workspace package.json files (depth <= 3)."""
    found: list[str] = []
    repo_root = repo.resolve()
    for dirpath, dirnames, filenames in os.walk(repo_root):
        rel_dir = pathlib.Path(dirpath).relative_to(repo_root)
        depth = 0 if rel_dir == pathlib.Path(".") else len(rel_dir.parts)
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_WALK_DIRS and not d.startswith(".")) if depth < 3 else []
        if "package.json" not in filenames:
            continue
        raw_pkg = pathlib.Path(dirpath) / "package.json"
        rel_pkg = raw_pkg.relative_to(repo_root).as_posix()
        resolved, escaped = _resolve_in_repo(repo_root, raw_pkg)
        if escaped:
            found.append(rel_pkg)
            continue
        if resolved is None or not resolved.is_file():
            continue
        try:
            pkg = json.loads(_read_text_safe(resolved))
        except json.JSONDecodeError:
            continue
        scripts = pkg.get("scripts") if isinstance(pkg, dict) else None
        if not isinstance(scripts, dict):
            continue
        for hook_name in PACKAGE_LIFECYCLE_HOOKS:
            val = scripts.get(hook_name)
            if isinstance(val, str) and val.strip():
                found.append(f"{rel_pkg}:scripts.{hook_name}")
    return found


def compute_hazard_digests(repo: pathlib.Path, hazards: list[str]) -> dict[str, str]:
    """Computes content-addressed path@sha256:<12hex> fingerprints so later edits invalidate stale approvals."""
    repo_root = repo.resolve()
    digests: dict[str, str] = {}
    for hazard in hazards:
        rel_file = hazard.split(":scripts.", 1)[0]
        target = repo_root / rel_file
        resolved, escaped = _resolve_in_repo(repo_root, target)
        if escaped or resolved is None or not resolved.is_file():
            raw = f"symlink-or-missing:{rel_file}".encode("utf-8")
        else:
            raw = resolved.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()[:12]
        digests[hazard] = f"{hazard}@sha256:{digest}"
    return digests


def detect_hooks_and_ai_divergence(repo: pathlib.Path) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    """Detects blocking untrusted workspace hazards and diverging AI instruction files."""
    hazards: list[str] = []
    advisory: list[dict[str, Any]] = []

    # 1. Detect project-scoped MCP manifests and Gemini auto-loaded .gemini/.env (CVE-2025-59536).
    for direct_rel in (".mcp.json", ".gemini/.env", *PRECOMMIT_FILES):
        p = repo / direct_rel
        if p.exists() or p.is_symlink():
            hazards.append(direct_rel)

    # 2. Detect Claude and Gemini settings hooks, helper commands, MCP auto-enable, and env overrides (CVE-2026-21852).
    for rel in HARNESS_SETTINGS_PATHS:
        hazards.extend(_inspect_harness_settings(repo, rel))

    # 3. Detect Git hooks, Husky hooks, and Gemini project hooks (following in-repo symlinks, flagging escapes).
    for hook_dir in (".githooks", ".husky", ".gemini/hooks"):
        d = repo / hook_dir
        if not d.exists() and not d.is_symlink():
            continue
        resolved_dir, escaped = _resolve_in_repo(repo, d)
        if escaped:
            hazards.append(hook_dir)
            continue
        if resolved_dir is not None and resolved_dir.is_dir():
            for child in sorted(resolved_dir.iterdir()):
                if child.name.startswith("."):
                    continue
                if child.is_file() or child.is_symlink():
                    hazards.append(f"{hook_dir}/{child.name}")

    # 4. Detect npm lifecycle scripts across root and workspace package.json files.
    hazards.extend(_inspect_package_json_scripts(repo))

    # 5. Detect diverging AGENTS.md, CLAUDE.md, and GEMINI.md files (treating @AGENTS.md includes as parity).
    ai_present: dict[str, bytes] = {}
    for fname in ("AGENTS.md", "CLAUDE.md", "GEMINI.md"):
        p = repo / fname
        if p.is_file() and not p.is_symlink():
            ai_present[fname] = p.read_bytes().replace(b"\r\n", b"\n").strip()
    resolved_contents: set[bytes] = set()
    for norm in ai_present.values():
        if norm.startswith(b"@") and b"\n" not in norm:
            target_name = norm[1:].decode("utf-8", errors="ignore").strip()
            if target_name in ai_present:
                resolved_contents.add(ai_present[target_name])
                continue
        resolved_contents.add(norm)
    diverged = sorted(ai_present.keys()) if len(ai_present) >= 2 and len(resolved_contents) > 1 else []

    unique_hazards = sorted(set(hazards))
    if unique_hazards:
        advisory.append({
            "code": "UNTRUSTED_WORKSPACE_HOOKS",
            "severity": "high",
            "blocking": True,
            "paths": unique_hazards,
            "digests": compute_hazard_digests(repo, unique_hazards),
            "message": (
                f"Detected blocking untrusted workspace hazards ({', '.join(unique_hazards)}). "
                "Review and acknowledge explicitly (acknowledged_workspace_hazards or --acknowledge-workspace-hazards) before emit."
            ),
        })
    if diverged:
        advisory.append({
            "code": "AI_INSTRUCTION_DIVERGENCE",
            "severity": "low",
            "blocking": False,
            "paths": diverged,
            "message": f"Pre-existing AI instruction files diverge ({', '.join(diverged)}). Consolidate key rules into absorbed_conventions.",
        })
    return unique_hazards, diverged, advisory
