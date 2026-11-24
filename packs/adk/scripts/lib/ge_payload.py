"""Gemini Enterprise (GE App) payload builder, A2A v0.3.0 AgentCard emitter, and Discovery Engine client.

Matches Discovery Engine v1alpha public schemas (rev 20261111):
1. export_mode="agent_engine": emits adkAgentDefinition.provisionedReasoningEngine (no undefined toolSettings)
   and optional authorizationConfig.toolAuthorizations.
2. export_mode="a2a": emits A2A v0.3.0 AgentCard (with mandatory skill tags) inside a2aAgentDefinition.jsonAgentCard
   and optional authorizationConfig.agentAuthorization.
Supports POST (create), PATCH (reuse single Sandbox registration to avoid 429 quota), and validated DELETE.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

from scripts.lib.schema_validator import validate_against_schema

HttpRequestFn = Callable[[str, str, dict[str, str], dict[str, Any] | None], tuple[int, dict[str, Any]]]

GE_AGENT_RESOURCE_RE = re.compile(
    r"^projects/([a-z0-9-]+)/locations/(global|us|eu)/collections/default_collection/"
    r"engines/[A-Za-z0-9_-]+/assistants/[A-Za-z0-9_-]+/agents/[A-Za-z0-9_-]+$"
)


def default_ge_schema(repo_root: pathlib.Path) -> pathlib.Path:
    """Locates schemas/ge-export.schema.json inside repo or container /opt/gcp-fde."""
    for cand in (
        repo_root / "schemas" / "ge-export.schema.json",
        pathlib.Path("/opt/gcp-fde/schemas/ge-export.schema.json"),
    ):
        if cand.is_file():
            return cand
    return repo_root / "schemas" / "ge-export.schema.json"


def default_http_request(
    method: str,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    """Executes an authenticated REST call against Discovery Engine with safe transport error handling."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            decoded = json.loads(raw) if raw.strip() else {}
            return resp.status, decoded if isinstance(decoded, dict) else {"data": decoded}
    except urllib.error.HTTPError as exc:
        return exc.code, {"error": exc.read().decode("utf-8", errors="replace")}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return 0, {"error": str(exc)}


def resolve_endpoint_location(ge_cfg: dict[str, Any]) -> str:
    """Derives the Discovery Engine endpoint prefix location from gemini_enterprise.location."""
    return str(ge_cfg.get("endpoint_location") or ge_cfg["location"])


def build_ge_agents_url(ge_cfg: dict[str, Any]) -> str:
    """Builds the Discovery Engine v1alpha assistant agents collection URL."""
    loc = str(ge_cfg["location"])
    endpoint_loc = resolve_endpoint_location(ge_cfg)
    prefix = "" if endpoint_loc == "global" else f"{endpoint_loc}-"
    project_id = str(ge_cfg["project_id"])
    app_id = str(ge_cfg["app_id"])
    assistant_id = str(ge_cfg.get("assistant_id") or "default_assistant")
    return (
        f"https://{prefix}discoveryengine.googleapis.com/v1alpha/"
        f"projects/{project_id}/locations/{loc}/collections/default_collection/"
        f"engines/{app_id}/assistants/{assistant_id}/agents"
    )


def build_agent_card(spec: dict[str, Any]) -> dict[str, Any]:
    """Builds a canonical A2A v0.3.0 AgentCard matching /.well-known/agent-card.json."""
    a2a = spec["a2a"]
    card: dict[str, Any] = {
        "protocolVersion": str(a2a["protocol_version"]),
        "name": str(spec["display_name"]),
        "description": str(spec["description"]),
        "url": str(a2a["url"]),
        "version": str(a2a["version"]),
        "capabilities": {"streaming": bool(a2a.get("streaming", True))},
        "defaultInputModes": list(a2a["default_input_modes"]),
        "defaultOutputModes": list(a2a["default_output_modes"]),
        "skills": list(a2a["skills"]),
    }
    for src_key, dst_key in (
        ("preferred_transport", "preferredTransport"),
        ("icon_url", "iconUrl"),
        ("provider", "provider"),
        ("security_schemes", "securitySchemes"),
        ("security", "security"),
    ):
        if a2a.get(src_key) is not None:
            card[dst_key] = a2a[src_key]
    return card


def build_ge_registration_payload(
    spec: dict[str, Any],
    display_name_override: str = "",
    reasoning_engine_override: str = "",
) -> dict[str, Any]:
    """Builds the Discovery Engine v1alpha POST/PATCH body for ADK or A2A agent registration."""
    display_name = (display_name_override or str(spec["display_name"]))[:120]
    payload: dict[str, Any] = {
        "displayName": display_name,
        "description": str(spec["description"]),
    }
    if spec.get("icon_uri"):
        payload["icon"] = {"uri": str(spec["icon_uri"])}

    mode = str(spec["export_mode"])
    if mode == "agent_engine":
        re_name = reasoning_engine_override or str(spec["agent_engine"]["reasoning_engine_resource"])
        payload["adkAgentDefinition"] = {
            "provisionedReasoningEngine": {"reasoningEngine": re_name},
        }
        tool_auths = list(spec.get("tool_authorizations") or [])
        if tool_auths:
            payload["authorizationConfig"] = {"toolAuthorizations": tool_auths}
    elif mode == "a2a":
        card = build_agent_card(spec)
        payload["a2aAgentDefinition"] = {
            "jsonAgentCard": json.dumps(card, separators=(",", ":"), sort_keys=True),
        }
        if spec.get("agent_authorization"):
            payload["authorizationConfig"] = {"agentAuthorization": str(spec["agent_authorization"])}
    else:
        raise ValueError(f"Unsupported export_mode '{mode}'. Expected 'agent_engine' or 'a2a'.")
    return payload


def validate_ge_manifest(spec: dict[str, Any], schema_path: pathlib.Path) -> list[str]:
    """Validates ge_manifest.json against schema plus location/region consistency rules."""
    errors = validate_against_schema(spec, schema_path)
    if errors:
        return errors

    ge = spec["gemini_enterprise"]
    loc = str(ge["location"])
    ep_loc = str(ge.get("endpoint_location") or loc)
    if ep_loc != loc:
        errors.append(f"endpoint_location '{ep_loc}' must match gemini_enterprise.location '{loc}'.")

    if spec["export_mode"] == "agent_engine":
        re_res = str(spec["agent_engine"]["reasoning_engine_resource"])
        engine_region = re_res.split("/locations/", 1)[1].split("/", 1)[0]
        if loc == "us" and not engine_region.startswith("us-"):
            errors.append(f"GE location 'us' requires a 'us-*' ReasoningEngine region, got '{engine_region}'.")
        if loc == "eu" and not engine_region.startswith("europe-"):
            errors.append(f"GE location 'eu' requires an 'europe-*' ReasoningEngine region, got '{engine_region}'.")

    return errors


def _sha256_bytes(data: bytes) -> str:
    """Computes a lowercase SHA-256 hex digest."""
    return hashlib.sha256(data).hexdigest()


def export_ge_bundle(
    spec: dict[str, Any],
    out_dir: pathlib.Path,
    schema_path: pathlib.Path,
    display_name_override: str = "",
    commit_sha: str = "",
    evals_tree_sha256: str = "",
) -> dict[str, Any]:
    """Validates spec and writes a deterministic Gemini Enterprise export bundle to out_dir."""
    errors = validate_ge_manifest(spec, schema_path)
    if errors:
        raise ValueError("Invalid GE export manifest: " + " | ".join(errors))

    out_dir.mkdir(parents=True, exist_ok=True)
    payload = build_ge_registration_payload(spec, display_name_override=display_name_override)
    endpoint_url = build_ge_agents_url(spec["gemini_enterprise"])

    payload_bytes = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    (out_dir / "ge_registration_payload.json").write_bytes(payload_bytes)
    files_meta: dict[str, str] = {"ge_registration_payload.json": _sha256_bytes(payload_bytes)}

    if spec["export_mode"] == "a2a":
        card_bytes = (json.dumps(build_agent_card(spec), indent=2, sort_keys=True) + "\n").encode("utf-8")
        (out_dir / "agent_card.json").write_bytes(card_bytes)
        files_meta["agent_card.json"] = _sha256_bytes(card_bytes)

    manifest: dict[str, Any] = {
        "schema_version": "1",
        "export_mode": spec["export_mode"],
        "display_name": payload["displayName"],
        "endpoint_url": endpoint_url,
        "files_sha256": files_meta,
        "commit_sha": commit_sha or None,
        "evals_tree_sha256": evals_tree_sha256 or None,
        "dry_run_curl": (
            f"curl -X POST -H 'Authorization: Bearer <TOKEN>' "
            f"-H 'Content-Type: application/json' "
            f"-H 'x-goog-user-project: {spec['gemini_enterprise']['project_id']}' "
            f"-d @ge_registration_payload.json '{endpoint_url}'"
        ),
    }
    (out_dir / "ge_export_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def register_ge_agent(
    spec: dict[str, Any],
    token: str,
    quota_project: str,
    display_name_override: str = "",
    reasoning_engine_override: str = "",
    http_fn: HttpRequestFn = default_http_request,
) -> tuple[int, dict[str, Any]]:
    """Registers an ADK or A2A agent in Gemini Enterprise via Discovery Engine POST."""
    url = build_ge_agents_url(spec["gemini_enterprise"])
    payload = build_ge_registration_payload(
        spec, display_name_override=display_name_override, reasoning_engine_override=reasoning_engine_override
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "x-goog-user-project": quota_project,
    }
    return http_fn("POST", url, headers, payload)


def patch_ge_agent(
    agent_resource_name: str,
    spec: dict[str, Any],
    token: str,
    quota_project: str,
    display_name_override: str = "",
    reasoning_engine_override: str = "",
    http_fn: HttpRequestFn = default_http_request,
) -> tuple[int, dict[str, Any]]:
    """Updates an existing Sandbox Gemini Enterprise agent via PATCH to avoid daily creation quota 429s."""
    m = GE_AGENT_RESOURCE_RE.match(agent_resource_name)
    if not m:
        raise ValueError(f"Invalid Gemini Enterprise agent resource name: '{agent_resource_name}'")
    if m.group(1) != quota_project:
        raise ValueError(f"Refusing cross-project PATCH: resource project '{m.group(1)}' != '{quota_project}'.")
    loc = m.group(2)
    prefix = "" if loc == "global" else f"{loc}-"
    mask = "displayName,description," + ("adkAgentDefinition" if spec["export_mode"] == "agent_engine" else "a2aAgentDefinition")
    url = f"https://{prefix}discoveryengine.googleapis.com/v1alpha/{agent_resource_name}?updateMask={urllib.parse.quote(mask)}"
    payload = build_ge_registration_payload(
        spec, display_name_override=display_name_override, reasoning_engine_override=reasoning_engine_override
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "x-goog-user-project": quota_project,
    }
    return http_fn("PATCH", url, headers, payload)


def delete_ge_agent(
    agent_resource_name: str,
    endpoint_location: str,
    token: str,
    quota_project: str,
    http_fn: HttpRequestFn = default_http_request,
) -> tuple[int, dict[str, Any]]:
    """Deletes a validated Gemini Enterprise agent resource, refusing non-agent or cross-project paths."""
    m = GE_AGENT_RESOURCE_RE.match(agent_resource_name)
    if not m:
        raise ValueError(f"Refusing DELETE on non-agent Discovery Engine path: '{agent_resource_name}'")
    if m.group(1) != quota_project:
        raise ValueError(f"Refusing cross-project DELETE: resource project '{m.group(1)}' != '{quota_project}'.")
    loc = endpoint_location or m.group(2)
    prefix = "" if loc == "global" else f"{loc}-"
    url = f"https://{prefix}discoveryengine.googleapis.com/v1alpha/{agent_resource_name}"
    headers = {"Authorization": f"Bearer {token}", "x-goog-user-project": quota_project}
    return http_fn("DELETE", url, headers, None)
