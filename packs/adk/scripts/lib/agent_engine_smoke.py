"""Remote conversational smoke test for deployed Vertex AI Agent Engine runtimes.

Verifies end-to-end session creation (async_create_session) and streamed model/tool
execution (async_stream_query) against the live ReasoningEngine endpoint using the
Evaluator OAuth token. Catches both regional session misconfiguration (HC-10 F9)
and missing runtime SA session IAM permissions (HC-11 F1) that local in-process
adk eval runs cannot detect.
"""
from __future__ import annotations

import http.client
import json
import re
import urllib.error
import urllib.request
from typing import Any, Callable

PostFn = Callable[[str, dict[str, str], dict[str, Any]], tuple[int, str]]
LOCATION_RE = re.compile(r"^[a-z0-9-]+$")


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
    except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException, ValueError) as exc:
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


def _classify_stream_event(obj: Any) -> str:
    """Classifies one parsed stream JSON object as error, content, or ignore."""
    if isinstance(obj, list):
        has_content = False
        for item in obj:
            state = _classify_stream_event(item)
            if state == "error":
                return "error"
            if state == "content":
                has_content = True
        return "content" if has_content else "ignore"
    if not isinstance(obj, dict):
        return "ignore"
    if obj.get("error") or obj.get("error_code") or obj.get("error_message"):
        return "error"
    if ("code" in obj or "status" in obj) and "message" in obj and "content" not in obj:
        return "error"
    content = obj.get("content")
    if isinstance(content, dict):
        role = str(content.get("role") or "").strip().lower()
        if role == "user":
            return "ignore"
        parts = content.get("parts")
        if isinstance(parts, list):
            for part in parts:
                if not isinstance(part, dict):
                    continue
                if isinstance(part.get("text"), str) and part["text"].strip():
                    return "content"
                if any(part.get(k) for k in ("function_call", "functionCall", "function_response", "functionResponse")):
                    return "content"
    return "ignore"


def _stream_has_non_empty_content(raw_stream: str) -> bool:
    """Checks that an Agent Engine SSE or JSON stream contains valid model/tool content and zero error events."""
    stripped = raw_stream.strip()
    if not stripped:
        return False
    # Support single pretty-printed JSON objects or top-level JSON arrays directly.
    if stripped[0] in ("{", "["):
        try:
            whole = json.loads(stripped)
            return _classify_stream_event(whole) == "content"
        except json.JSONDecodeError:
            pass

    has_content = False
    for line in stripped.splitlines():
        raw_line = line.strip()
        if not raw_line or raw_line.startswith((":", "event:", "id:", "retry:")):
            continue
        payload = raw_line[5:].strip() if raw_line.startswith("data:") else raw_line
        if not payload:
            continue
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            return False
        state = _classify_stream_event(event)
        if state == "error":
            return False
        if state == "content":
            has_content = True
    return has_content


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
    Deletes the temporary smoke session on a best-effort basis after completion.
    """
    if "/locations/" not in reasoning_engine or "/reasoningEngines/" not in reasoning_engine:
        return False, f"Invalid ReasoningEngine resource path: '{reasoning_engine}'."

    loc = reasoning_engine.split("/locations/", 1)[1].split("/", 1)[0]
    if not LOCATION_RE.fullmatch(loc):
        return False, f"Invalid ReasoningEngine location segment: '{loc}'."
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

    try:
        st_stream, body_stream = post_fn(
            f"{base_url}:streamQuery?alt=sse",
            headers,
            {
                "class_method": "async_stream_query",
                "input": {"user_id": user_id, "session_id": session_id, "message": prompt},
            },
        )
    finally:
        # Best-effort cleanup of the ephemeral smoke session (never fails the smoke result).
        try:
            post_fn(
                f"{base_url}:query",
                headers,
                {"class_method": "async_delete_session", "input": {"user_id": user_id, "session_id": session_id}},
            )
        except Exception:
            pass

    if st_stream != 200:
        return False, f"Remote async_stream_query returned HTTP {st_stream}: {body_stream[:240]}"
    if not _stream_has_non_empty_content(body_stream):
        return False, f"Remote async_stream_query returned empty or error stream: {body_stream[:240]}"
    return True, session_id
