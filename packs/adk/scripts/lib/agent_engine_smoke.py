"""Remote conversational smoke test for deployed Vertex AI Agent Engine runtimes.

Verifies end-to-end session creation (async_create_session) and streamed model/tool
execution (async_stream_query) against the live ReasoningEngine endpoint using the
Evaluator OAuth token. Catches both regional session misconfiguration (HC-10 F9)
and missing runtime SA session IAM permissions (HC-11 F1) that local in-process
adk eval runs cannot detect.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable

PostFn = Callable[[str, dict[str, str], dict[str, Any]], tuple[int, str]]


def default_http_post(url: str, headers: dict[str, str], body: dict[str, Any]) -> tuple[int, str]:
    """Sends a JSON POST request and returns the HTTP status code and raw response body."""
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return 0, str(exc)


def _extract_session_id(raw_body: str) -> str:
    """Extracts the created session ID from an async_create_session JSON response."""
    try:
        data = json.loads(raw_body)
    except json.JSONDecodeError:
        return ""
    if not isinstance(data, dict):
        return ""
    output = data.get("output")
    if isinstance(output, dict) and output.get("id"):
        return str(output["id"])
    if data.get("id"):
        return str(data["id"])
    return ""


def _stream_has_non_empty_content(raw_stream: str) -> bool:
    """Checks that an Agent Engine SSE or JSON response contains model or tool output without top-level errors."""
    stripped = raw_stream.strip()
    if not stripped:
        return False
    for line in stripped.splitlines():
        payload = line[5:].strip() if line.startswith("data:") else line.strip()
        if not payload:
            continue
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            if event.get("error"):
                return False
            content = event.get("content")
            if isinstance(content, dict) and content.get("parts"):
                return True
            if event.get("output") or event.get("text"):
                return True
    return False


def run_remote_agent_engine_smoke(
    reasoning_engine: str,
    access_token: str,
    quota_project: str,
    prompt: str = "Hello, run a quick health status check.",
    user_id: str = "factory-eval-smoke",
    post_fn: PostFn = default_http_post,
) -> tuple[bool, str]:
    """Executes a live two-step session and streamQuery check against reasoning_engine.

    Returns (True, session_id) on verified non-empty response or (False, error_detail) on failure.
    """
    if "/locations/" not in reasoning_engine or "/reasoningEngines/" not in reasoning_engine:
        return False, f"Invalid ReasoningEngine resource path: '{reasoning_engine}'."

    loc = reasoning_engine.split("/locations/", 1)[1].split("/", 1)[0]
    base_url = f"https://{loc}-aiplatform.googleapis.com/v1beta1/{reasoning_engine}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "x-goog-user-project": quota_project,
        "Content-Type": "application/json",
    }

    st_sess, body_sess = post_fn(
        f"{base_url}:query",
        headers,
        {"class_method": "async_create_session", "input": {"user_id": user_id}},
    )
    if st_sess != 200:
        return False, f"Remote async_create_session returned HTTP {st_sess}: {body_sess[:240]}"

    session_id = _extract_session_id(body_sess)
    if not session_id:
        return False, f"Remote async_create_session returned HTTP 200 without session id: {body_sess[:200]}"

    st_stream, body_stream = post_fn(
        f"{base_url}:streamQuery?alt=sse",
        headers,
        {
            "class_method": "async_stream_query",
            "input": {"user_id": user_id, "session_id": session_id, "message": prompt},
        },
    )
    if st_stream != 200:
        return False, f"Remote async_stream_query returned HTTP {st_stream}: {body_stream[:240]}"
    if not _stream_has_non_empty_content(body_stream):
        return False, f"Remote async_stream_query returned empty or error stream: {body_stream[:240]}"
    return True, session_id
