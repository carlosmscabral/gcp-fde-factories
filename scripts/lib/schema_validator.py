"""JSON Schema validator for all 5 factory contracts.

Validates pack.yaml, compat.yaml, hub-project.yaml, and Verdict JSON against schemas/*.json.
"""
from __future__ import annotations

import pathlib
from typing import Any

import jsonschema

from scripts.lib.io_utils import load_json, load_yaml


def validate_against_schema(payload: dict[str, Any], schema_path: pathlib.Path) -> list[str]:
    """Validates payload against a Draft 2020-12 JSON Schema and returns error strings."""
    schema = load_json(schema_path)
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    errors = sorted(validator.iter_errors(payload), key=lambda err: list(err.path))
    formatted: list[str] = []
    for err in errors:
        loc = ".".join(str(p) for p in err.path) or "<root>"
        formatted.append(f"{schema_path.name} [{loc}]: {err.message}")
    return formatted


def validate_yaml_file(yaml_path: pathlib.Path, schema_path: pathlib.Path) -> list[str]:
    """Loads a YAML document and validates it against schema_path."""
    return validate_against_schema(load_yaml(yaml_path), schema_path)


def validate_json_file(json_path: pathlib.Path, schema_path: pathlib.Path) -> list[str]:
    """Loads a JSON document and validates it against schema_path."""
    return validate_against_schema(load_json(json_path), schema_path)
