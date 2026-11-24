#!/usr/bin/env python3
"""Canary contract verifier for packs/adk Gemini Enterprise (GE App) export payloads.

Validates that both adkAgentDefinition and a2aAgentDefinition outputs from ge_payload.py
satisfy the pinned Discovery Engine v1alpha API contract in canaries/adk/ge_export_contract.json.
"""
from __future__ import annotations

import json
import pathlib
import sys
from typing import Any

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from packs.adk.scripts.lib.ge_payload import build_ge_agents_url, build_ge_registration_payload


def _has_dotted_path(obj: dict[str, Any], dotted: str) -> bool:
    """Checks whether a nested dotted key path exists with a truthy value."""
    cur: Any = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return False
        cur = cur[part]
    return bool(cur)


def check_ge_export_contract(contract_path: pathlib.Path) -> list[str]:
    """Verifies ge_payload.py outputs against canaries/adk/ge_export_contract.json."""
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    errors: list[str] = []

    sample_ae = {
        "schema_version": "1",
        "export_mode": "agent_engine",
        "display_name": "Synthetic ADK Assistant",
        "description": "Synthetic Vertex AI Agent Engine assistant for Canary contract checks.",
        "gemini_enterprise": {
            "project_id": "synthetic-sbx-001",
            "location": "global",
            "endpoint_location": "global",
            "app_id": "synthetic-ge-app",
        },
        "agent_engine": {
            "reasoning_engine_resource": "projects/synthetic-sbx-001/locations/us-central1/reasoningEngines/123456789"
        },
    }
    ae_payload = build_ge_registration_payload(sample_ae)
    for field in contract["required_payload_fields"]["common"] + contract["required_payload_fields"]["agent_engine"]:
        if not _has_dotted_path(ae_payload, field):
            errors.append(f"agent_engine payload missing required field '{field}'.")

    sample_a2a = {
        "schema_version": "1",
        "export_mode": "a2a",
        "display_name": "Synthetic A2A Assistant",
        "description": "Synthetic A2A assistant for Gemini Enterprise Canary contract checks.",
        "gemini_enterprise": {
            "project_id": "synthetic-sbx-001",
            "location": "us",
            "endpoint_location": "us",
            "app_id": "synthetic-ge-app",
        },
        "a2a": {
            "protocol_version": "0.3.0",
            "url": "https://synthetic-agent.run.app/a2a",
            "version": "1.0.0",
            "default_input_modes": ["text"],
            "default_output_modes": ["text"],
            "skills": [{"id": "triage", "name": "Triage", "description": "Routes synthetic requests."}],
        },
    }
    a2a_payload = build_ge_registration_payload(sample_a2a)
    for field in contract["required_payload_fields"]["common"] + contract["required_payload_fields"]["a2a"]:
        if not _has_dotted_path(a2a_payload, field):
            errors.append(f"a2a payload missing required field '{field}'.")

    card = json.loads(a2a_payload["a2aAgentDefinition"]["jsonAgentCard"])
    for key in contract["required_agent_card_fields"]:
        if key not in card or not card[key]:
            errors.append(f"A2A jsonAgentCard missing required field '{key}'.")

    url = build_ge_agents_url(sample_a2a["gemini_enterprise"])
    if not url.startswith("https://us-discoveryengine.googleapis.com/v1alpha/"):
        errors.append(f"Unexpected regional Discovery Engine URL: {url}")

    return errors


if __name__ == "__main__":
    errs = check_ge_export_contract(pathlib.Path(__file__).resolve().parent / "ge_export_contract.json")
    if errs:
        for e in errs:
            print(f"CANARY ERROR: {e}", file=sys.stderr)
        raise SystemExit(1)
    print("ADK GE EXPORT CANARY OK")
