"""Authenticated Scion Hub message notifier using GCP Service Account OIDC.

Mints a short-lived GCP OIDC identity token lazily from the Cloud Run metadata server
and posts SEP-aligned delta summaries to the Hub coordinator with wake=true.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

from intake_filter import WakeupEvent

METADATA_ID_URL = (
    "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity"
)
DEFAULT_OIDC_AUDIENCE = "32555940559.apps.googleusercontent.com"

HttpPostFn = Callable[[str, dict[str, Any], dict[str, str], float], tuple[int, bytes]]
IdentityTokenFn = Callable[[str], str]


def _default_identity_token(audience: str) -> str:
    """Mints an OIDC identity token from the Cloud Run metadata server or env override."""
    override = os.environ.get("SCION_HUB_TOKEN", "").strip()
    if override:
        return override
    query = urllib.parse.urlencode({"audience": audience, "format": "full"})
    req = urllib.request.Request(
        f"{METADATA_ID_URL}?{query}",
        headers={"Metadata-Flavor": "Google"},
    )
    with urllib.request.urlopen(req, timeout=5.0) as resp:
        token = resp.read().decode("utf-8").strip()
    if not token:
        raise RuntimeError("Metadata server returned an empty OIDC identity token.")
    return token


def _default_http_post(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout: float,
) -> tuple[int, bytes]:
    """Posts JSON via stdlib urllib and returns (status_code, body_bytes)."""
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(resp.status), resp.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read()


def format_wakeup_message(repo_slug: str, provider: str, events: list[WakeupEvent]) -> str:
    """Renders a concise SEP-aligned coordinator wakeup payload for the detected deltas."""
    lines = [
        f"[External Delta Watcher | provider={provider} | repo={repo_slug}]",
        f"Detected {len(events)} actionable delta event(s). Follow SEP (Depth-1 vs Depth-3) without adding non-SEP status labels:",
    ]
    for ev in events:
        if ev.kind == "new_issue":
            lines.append(f"- NEW ISSUE #{ev.issue_number}: {ev.title} ({ev.url})")
        elif ev.kind == "human_comment":
            lines.append(f"- HUMAN REPLY on #{ev.issue_number} by @{ev.author}: {ev.summary} ({ev.url})")
        elif ev.kind == "pr_action_needed":
            lines.append(f"- PR ACTION #{ev.pr_number} (issue #{ev.issue_number}): {ev.summary} ({ev.url})")
        else:
            lines.append(f"- DELTA #{ev.issue_number}: {ev.summary} ({ev.url})")
    return "\n".join(lines)


class HubNotifier:
    """Sends wake=true coordinator notifications to a private Scion Hub endpoint."""

    def __init__(
        self,
        hub_url: str,
        project_id: str = "",
        coordinator_agent: str = "coordinator",
        oidc_audience: str = DEFAULT_OIDC_AUDIENCE,
        token_provider: IdentityTokenFn | None = None,
        http_post: HttpPostFn | None = None,
        timeout: float = 20.0,
    ) -> None:
        if not hub_url.strip():
            raise ValueError("HubNotifier requires a non-empty hub_url.")
        self._hub_url = hub_url.strip().rstrip("/")
        self._project_id = project_id.strip()
        self._coordinator = coordinator_agent.strip() or "coordinator"
        self._audience = oidc_audience.strip() or DEFAULT_OIDC_AUDIENCE
        self._token_provider = token_provider or _default_identity_token
        self._http_post = http_post or _default_http_post
        self._timeout = timeout

    def _endpoint(self) -> str:
        """Builds the Scion Hub message API URL scoped to the configured project and agent."""
        agent_q = urllib.parse.quote(self._coordinator, safe="")
        if self._project_id:
            proj_q = urllib.parse.quote(self._project_id, safe="")
            return f"{self._hub_url}/api/v1/projects/{proj_q}/agents/{agent_q}/message"
        return f"{self._hub_url}/api/v1/agents/{agent_q}/message"

    def wake_coordinator(self, repo_slug: str, provider: str, events: list[WakeupEvent]) -> dict[str, Any]:
        """Posts a wake=true message to the Scion Hub coordinator when events is non-empty."""
        if not events:
            return {"status": "skipped", "reason": "no_events"}
        token = self._token_provider(self._audience)
        message_text = format_wakeup_message(repo_slug, provider, events)
        payload = {
            "message": message_text,
            "wake": True,
            "source": "delta-watcher",
            "events": [
                {
                    "kind": ev.kind,
                    "issue_number": ev.issue_number,
                    "pr_number": ev.pr_number,
                    "url": ev.url,
                }
                for ev in events
            ],
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "gcp-fde-factories-delta-watcher",
        }
        status, raw = self._http_post(self._endpoint(), payload, headers, self._timeout)
        if status < 200 or status >= 300:
            detail = raw.decode("utf-8", errors="replace")[:300]
            raise RuntimeError(f"Scion Hub wake failed ({status}): {detail}")
        return {"status": "woken", "http_status": status, "event_count": len(events)}
