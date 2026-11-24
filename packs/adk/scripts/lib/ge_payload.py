"""Gemini Enterprise (GE App) payload builder, AgentCard emitter, and Discovery Engine REST client.

Supports both official public Gemini Enterprise registration modes:
1. export_mode="agent_engine": emits adkAgentDefinition.provisionedReasoningEngine targeting
   a Vertex AI Agent Engine resource.
2. export_mode="a2a": emits a canonical A2A AgentCard and wraps it in a2aAgentDefinition.jsonAgentCard.
All HTTP calls accept injectable callables so CI and unit tests run offline without credentials.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import urllib.error
import urllib.request
from typing import Any, Callable

from scripts.lib.schema_validator import validate_against_schema

HttpRequestFn = Callable[[str, str, dict[str, str], dict[str, Any] | None], tuple[int, dict[str, Any]]]


def default_http_request(
    method: str,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    """Executes an authenticated REST call against Discovery Engine and returns status plus JSON."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        return exc.code, {"error": exc.read().decode("utf-8", errors="replace")}


def build_ge_agents_url(ge_cfg: dict[str, Any]) -> str:
    """Builds the Discovery Engine v1alpha assistant agents collection URL."""
    endpoint_loc = str(ge_cfg["endpoint_location"])
    prefix = "" if endpoint_loc == "global" else f"{endpoint_loc}-"
    project_id = str(ge_cfg["project_id"])
    location = str(ge_cfg["location"])
    app_id = str(ge_cfg["app_id"])
    assistant_id = str(ge_cfg.get("assistant_id") or "default_assistant")
    return (
        f"https://{prefix}discoveryengine.googleapis.com/v1alpha/"
        f"projects/{project_id}/locations/{location}/collections/default_collection/"
        f"engines/{app_id}/assistants/{assistant_id}/agents"
    )


def build_agent_card(spec: dict[str, Any]) -> dict[str, Any]:
    """Builds a canonical A2A AgentCard matching /.well-known/agent-card.json."""
    a2a = spec["a2a"]
    return {
        "protocolVersion": str(a2a["protocol_version"]),
        "name": str(spec["display_name"]),
        "description": str(spec["description"]),
        "url": str(a2a["url"]),
        "version": str(a2a["version"]),
        "capabilities": {
            "streaming": bool(a2a.get("streaming", True)),
        },
        "defaultInputModes": list(a2a["default_input_modes"]),
        "defaultOutputModes": list(a2a["default_output_modes"]),
        "skills": list(a2a["skills"]),
    }


def build_ge_registration_payload(spec: dict[str, Any], display_name_override: str = "") -> dict[str, Any]:
    """Builds the Discovery Engine POST body for adkAgentDefinition or a2aAgentDefinition."""
    display_name = display_name_override or str(spec["display_name"])
    payload: dict[str, Any] = {
        "displayName": display_name,
        "description": str(spec["description"]),
    }

    mode = str(spec["export_mode"])
    if mode == "agent_engine":
        re_name = str(spec["agent_engine"]["reasoning_engine_resource"])
        adk_def: dict[str, Any] = {
            "provisionedReasoningEngine": {
                "reasoningEngine": re_name,
            }
        }
        tool_desc = str(spec.get("tool_description") or spec["description"])
        adk_def["toolSettings"] = {"toolDescription": tool_desc}
        payload["adkAgentDefinition"] = adk_def
    elif mode == "a2a":
        card = build_agent_card(spec)
        payload["a2aAgentDefinition"] = {
            "jsonAgentCard": json.dumps(card, separators=(",", ":"), sort_keys=True),
        }
    else:
        raise ValueError(f"Unsupported export_mode '{mode}'. Expected 'agent_engine' or 'a2a'.")

    tool_auths = list(spec.get("tool_authorizations") or [])
    if tool_auths:
        payload["authorizationConfig"] = {"toolAuthorizations": tool_auths}
    return payload


def validate_ge_manifest(spec: dict[str, Any], schema_path: pathlib.Path) -> list[str]:
    """Validates a ge_manifest.json dict against schemas/ge-export.schema.json."""
    errors = validate_against_schema(spec, schema_path)
    if not errors and spec["export_mode"] == "a2a":
        card = build_agent_card(spec)
        if not card.get("url", "").startswith("https://"):
            errors.append("A2A AgentCard url must use HTTPS.")
    return errors


def _sha256_bytes(data: bytes) -> str:
    """Computes a lowercase SHA-256 hex digest."""
    return hashlib.sha256(data).hexdigest()


def export_ge_bundle(
    spec: dict[str, Any],
    out_dir: pathlib.Path,
    schema_path: pathlib.Path,
    display_name_override: str = "",
) -> dict[str, Any]:
    """Validates spec and writes a deterministic Gemini Enterprise export bundle to out_dir."""
    errors = validate_ge_manifest(spec, schema_path)
    if errors:
        raise ValueError("Invalid GE export manifest: " + " | ".join(errors))

    out_dir.mkdir(parents=True, exist_ok=True)
    payload = build_ge_registration_payload(spec, display_name_override=display_name_override)
    endpoint_url = build_ge_agents_url(spec["gemini_enterprise"])

    payload_bytes = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    payload_file = out_dir / "ge_registration_payload.json"
    payload_file.write_bytes(payload_bytes)

    files_meta: dict[str, str] = {
        "ge_registration_payload.json": _sha256_bytes(payload_bytes),
    }

    if spec["export_mode"] == "a2a":
        card = build_agent_card(spec)
        card_bytes = (json.dumps(card, indent=2, sort_keys=True) + "\n").encode("utf-8")
        (out_dir / "agent_card.json").write_bytes(card_bytes)
        files_meta["agent_card.json"] = _sha256_bytes(card_bytes)

    manifest = {
        "schema_version": "1",
        "export_mode": spec["export_mode"],
        "display_name": payload["displayName"],
        "endpoint_url": endpoint_url,
        "files_sha256": files_meta,
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
    http_fn: HttpRequestFn = default_http_request,
) -> tuple[int, dict[str, Any]]:
    """Registers an ADK or A2A agent in Gemini Enterprise via Discovery Engine REST API."""
    url = build_ge_agents_url(spec["gemini_enterprise"])
    payload = build_ge_registration_payload(spec, display_name_override=display_name_override)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "x-goog-user-project": quota_project,
    }
    return http_fn("POST", url, headers, payload)


def delete_ge_agent(
    agent_resource_name: str,
    endpoint_location: str,
    token: str,
    quota_project: str,
    http_fn: HttpRequestFn = default_http_request,
) -> tuple[int, dict[str, Any]]:
    """Deletes an ephemeral Gemini Enterprise registered agent resource by full name."""
    prefix = "" if endpoint_location == "global" else f"{endpoint_location}-"
    url = f"https://{prefix}discoveryengine.googleapis.com/v1alpha/{agent_resource_name}"
    headers = {
        "Authorization": f"Bearer {token}",
        "x-goog-user-project": quota_project,
    }
    return http_fn("DELETE", url, headers, None)
