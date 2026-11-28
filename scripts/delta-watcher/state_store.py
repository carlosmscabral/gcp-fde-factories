"""Optimistic-concurrency cursor state stores (GCS ifGenerationMatch and local file).

Persists Delta Watcher cursor JSON in a single GCS object inside hub_project_id without
requiring Firestore, Spanner, or Cloud SQL, while rejecting concurrent tick races via HTTP 412.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Protocol

METADATA_TOKEN_URL = (
    "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
)


class ConcurrencyConflictError(RuntimeError):
    """Raised when a state write fails optimistic generation matching."""


class StateStore(Protocol):
    """Defines optimistic-concurrency load and save operations for watcher cursors."""

    def load(self) -> tuple[dict[str, Any], str]:
        """Loads persisted state and returns (state_dict, generation_token)."""

    def save(self, state: dict[str, Any], expected_generation: str) -> str:
        """Persists state only if current generation matches expected_generation."""


def _state_hash(raw_bytes: bytes) -> str:
    """Computes a deterministic content generation token for local file optimistic locking."""
    return hashlib.sha256(raw_bytes).hexdigest()[:16]


class LocalFileStateStore:
    """Persists cursor JSON to a local file with atomic rename and optimistic hash checks."""

    def __init__(self, path: pathlib.Path) -> None:
        self._path = path

    def load(self) -> tuple[dict[str, Any], str]:
        """Reads the local JSON cursor or returns an empty state with generation '0'."""
        if not self._path.exists():
            return {}, "0"
        raw = self._path.read_bytes()
        return json.loads(raw.decode("utf-8")), _state_hash(raw)

    def save(self, state: dict[str, Any], expected_generation: str) -> str:
        """Writes state atomically if the on-disk hash still matches expected_generation."""
        current_gen = _state_hash(self._path.read_bytes()) if self._path.exists() else "0"
        if current_gen != expected_generation:
            raise ConcurrencyConflictError(
                f"Local state conflict on {self._path}: expected {expected_generation}, found {current_gen}."
            )
        payload = (json.dumps(state, indent=2, sort_keys=True) + "\n").encode("utf-8")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".cursor-", dir=str(self._path.parent))
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(payload)
            os.replace(tmp_name, self._path)
        except Exception:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
            raise
        return _state_hash(payload)


HttpRequestFn = Callable[[str, str, dict[str, str], bytes | None, float], tuple[int, bytes]]
TokenProviderFn = Callable[[], str]


def _default_metadata_token() -> str:
    """Fetches a short-lived OAuth2 access token from the GCP metadata server."""
    env_tok = os.environ.get("GCS_ACCESS_TOKEN", "").strip()
    if env_tok:
        return env_tok
    req = urllib.request.Request(METADATA_TOKEN_URL, headers={"Metadata-Flavor": "Google"})
    with urllib.request.urlopen(req, timeout=5.0) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    token = str(data.get("access_token") or "")
    if not token:
        raise RuntimeError("Metadata server returned an empty access_token.")
    return token


def _default_http_request(
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes | None,
    timeout: float,
) -> tuple[int, bytes]:
    """Executes one HTTP request via stdlib urllib and returns (status_code, body_bytes)."""
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(resp.status), resp.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read()


class GcsStateStore:
    """Stores cursor JSON in a GCS object using ifGenerationMatch optimistic concurrency."""

    def __init__(
        self,
        bucket: str,
        object_name: str,
        token_provider: TokenProviderFn | None = None,
        http_request: HttpRequestFn | None = None,
        timeout: float = 15.0,
    ) -> None:
        if not bucket.strip() or not object_name.strip():
            raise ValueError("GcsStateStore requires non-empty bucket and object_name.")
        self._bucket = bucket.strip()
        self._object = object_name.strip().lstrip("/")
        self._token_provider = token_provider or _default_metadata_token
        self._http_request = http_request or _default_http_request
        self._timeout = timeout

    def _auth_headers(self, content_type: str = "") -> dict[str, str]:
        """Builds Authorization headers lazily using the active GCP service account token."""
        headers = {"Authorization": f"Bearer {self._token_provider()}"}
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def load(self) -> tuple[dict[str, Any], str]:
        """Loads GCS object metadata and JSON payload, returning ({}, '0') when absent."""
        encoded = urllib.parse.quote(self._object, safe="")
        meta_url = f"https://storage.googleapis.com/storage/v1/b/{self._bucket}/o/{encoded}"
        status, raw_meta = self._http_request("GET", meta_url, self._auth_headers(), None, self._timeout)
        if status == 404:
            return {}, "0"
        if status != 200:
            raise RuntimeError(f"GCS metadata load failed ({status}): {raw_meta[:200]!r}")
        meta = json.loads(raw_meta.decode("utf-8"))
        generation = str(meta.get("generation") or "0")

        media_url = f"{meta_url}?alt=media&generation={urllib.parse.quote(generation, safe='')}"
        m_status, raw_body = self._http_request("GET", media_url, self._auth_headers(), None, self._timeout)
        if m_status == 404:
            return {}, "0"
        if m_status != 200:
            raise RuntimeError(f"GCS object load failed ({m_status}): {raw_body[:200]!r}")
        data = json.loads(raw_body.decode("utf-8")) if raw_body.strip() else {}
        return (data if isinstance(data, dict) else {}), generation

    def save(self, state: dict[str, Any], expected_generation: str) -> str:
        """Uploads cursor JSON guarded by ifGenerationMatch to prevent concurrent overwrites."""
        query = urllib.parse.urlencode(
            {
                "uploadType": "media",
                "name": self._object,
                "ifGenerationMatch": str(expected_generation),
            }
        )
        upload_url = f"https://storage.googleapis.com/upload/storage/v1/b/{self._bucket}/o?{query}"
        payload = (json.dumps(state, indent=2, sort_keys=True) + "\n").encode("utf-8")
        status, raw_resp = self._http_request(
            "POST",
            upload_url,
            self._auth_headers("application/json"),
            payload,
            self._timeout,
        )
        if status == 412:
            raise ConcurrencyConflictError(
                f"GCS precondition failed (412) for gs://{self._bucket}/{self._object} "
                f"with ifGenerationMatch={expected_generation}."
            )
        if status not in (200, 201):
            raise RuntimeError(f"GCS state save failed ({status}): {raw_resp[:200]!r}")
        resp = json.loads(raw_resp.decode("utf-8")) if raw_resp.strip() else {}
        return str(resp.get("generation") or expected_generation)
