#!/usr/bin/env python3
"""Thin Cloud Run HTTP composition root for the External Delta Watcher.

Exposes GET /healthz and POST /tick using Python stdlib HTTPServer with zero network
calls on import and structured single-line JSON logs for zero-token Kaizen telemetry.
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import sys
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

_THIS_DIR = str(pathlib.Path(__file__).resolve().parent)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from adapters.base import TrackerAdapter  # noqa: E402
from adapters.github import DEFAULT_GRAPHQL_URL, GitHubTrackerAdapter  # noqa: E402
from hub_notifier import DEFAULT_OIDC_AUDIENCE, HubNotifier  # noqa: E402
from intake_filter import DEFAULT_BOT_LOGINS, IntakePolicy  # noqa: E402
from intake_models import DEFAULT_ALLOWED_AUTHOR_ASSOCIATIONS  # noqa: E402
from state_store import ConcurrencyConflictError, GcsStateStore, LocalFileStateStore, StateStore  # noqa: E402
from watcher import run_tick  # noqa: E402

LOG = logging.getLogger("delta_watcher")


@dataclass
class WatcherRuntime:
    """Bundles initialized dependencies injected into the Cloud Run HTTP handler."""

    repo_slug: str
    policy: IntakePolicy
    adapter: TrackerAdapter
    state_store: StateStore
    notifier: HubNotifier | None


def _env_bool(name: str, default: bool) -> bool:
    """Parses a boolean environment variable cleanly."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def build_runtime_from_env() -> WatcherRuntime:
    """Constructs WatcherRuntime lazily from Cloud Run environment variables."""
    provider = os.environ.get("DELTA_WATCHER_PROVIDER", "github").strip().lower()
    repo_slug = os.environ.get("DELTA_WATCHER_REPO", "").strip()
    if provider != "github":
        raise ValueError(f"Unsupported tracker provider '{provider}' in Milestone 1 (expected 'github').")
    if not repo_slug:
        raise ValueError("DELTA_WATCHER_REPO must be set to 'owner/repo'.")

    extra_bots = [
        b.strip()
        for b in os.environ.get("DELTA_WATCHER_BOT_LOGINS", "").split(",")
        if b.strip()
    ]
    raw_assocs = [
        a.strip().upper()
        for a in os.environ.get("DELTA_WATCHER_ALLOWED_ASSOCIATIONS", "").split(",")
        if a.strip()
    ]
    policy = IntakePolicy(
        enabled=_env_bool("DELTA_WATCHER_ENABLED", True),
        provider=provider,
        max_concurrent_issues=int(os.environ.get("DELTA_WATCHER_MAX_CONCURRENT_ISSUES", "2")),
        scope_label=os.environ.get("DELTA_WATCHER_SCOPE_LABEL", "").strip(),
        release_label=os.environ.get("DELTA_WATCHER_RELEASE_LABEL", "factory:ready").strip(),
        hold_label=os.environ.get("DELTA_WATCHER_HOLD_LABEL", "factory:hold").strip(),
        paused=_env_bool("DELTA_WATCHER_PAUSED", False),
        bot_logins=tuple(dict.fromkeys([*DEFAULT_BOT_LOGINS, *extra_bots])),
        allowed_author_associations=tuple(raw_assocs) if raw_assocs else DEFAULT_ALLOWED_AUTHOR_ASSOCIATIONS,
    )

    # Filter open issues server-side strictly on release_label (never scope_label, because GitHub
    # GraphQL labels:[...] uses OR semantics that would re-introduce pagination overflow, H2/BG-H9).
    server_labels = (policy.release_label,) if policy.release_label else ()
    graphql_url = os.environ.get("DELTA_WATCHER_GITHUB_GRAPHQL_URL", DEFAULT_GRAPHQL_URL).strip() or DEFAULT_GRAPHQL_URL
    adapter: TrackerAdapter = GitHubTrackerAdapter(
        repo_slug=repo_slug,
        api_url=graphql_url,
        filter_labels=server_labels,
    )
    bucket = os.environ.get("DELTA_WATCHER_STATE_BUCKET", "").strip()
    obj_name = os.environ.get("DELTA_WATCHER_STATE_OBJECT", "delta-watcher/cursor.json").strip()
    if bucket:
        store: StateStore = GcsStateStore(bucket=bucket, object_name=obj_name)
    else:
        local_path = pathlib.Path(os.environ.get("DELTA_WATCHER_LOCAL_CURSOR", "/tmp/delta-watcher-cursor.json"))
        store = LocalFileStateStore(local_path)

    hub_url = os.environ.get("SCION_HUB_URL", "").strip()
    notifier = (
        HubNotifier(
            hub_url=hub_url,
            project_id=os.environ.get("SCION_HUB_PROJECT_ID", "").strip(),
            coordinator_agent=os.environ.get("DELTA_WATCHER_COORDINATOR_AGENT", "coordinator").strip(),
            oidc_audience=os.environ.get("DELTA_WATCHER_OIDC_AUDIENCE", DEFAULT_OIDC_AUDIENCE).strip(),
        )
        if hub_url
        else None
    )
    return WatcherRuntime(
        repo_slug=repo_slug,
        policy=policy,
        adapter=adapter,
        state_store=store,
        notifier=notifier,
    )


def create_handler(runtime: WatcherRuntime) -> type[BaseHTTPRequestHandler]:
    """Creates a request handler class bound to one WatcherRuntime instance."""

    class DeltaWatcherHandler(BaseHTTPRequestHandler):
        """Handles Cloud Run health probes and Cloud Scheduler tick invocations."""

        def _write_json(self, status: int, body: dict[str, Any]) -> None:
            raw = (json.dumps(body, sort_keys=True) + "\n").encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, format: str, *args: Any) -> None:
            """Suppresses unstructured stderr logs in favor of structured JSON output."""

        def do_GET(self) -> None:
            if self.path.split("?", 1)[0] == "/healthz":
                self._write_json(
                    200,
                    {
                        "status": "ok",
                        "provider": runtime.policy.provider,
                        "repo": runtime.repo_slug,
                        "paused": runtime.policy.paused,
                    },
                )
                return
            self._write_json(404, {"error": "not_found"})

        def do_POST(self) -> None:
            if self.path.split("?", 1)[0] != "/tick":
                self._write_json(404, {"error": "not_found"})
                return
            try:
                result = run_tick(
                    adapter=runtime.adapter,
                    state_store=runtime.state_store,
                    policy=runtime.policy,
                    repo_slug=runtime.repo_slug,
                    notifier=runtime.notifier,
                )
                LOG.info(json.dumps({"event": "delta_watcher_tick", **result}, sort_keys=True))
                self._write_json(200, result)
            except ConcurrencyConflictError as exc:
                LOG.warning(json.dumps({"event": "delta_watcher_conflict", "error": str(exc)}))
                self._write_json(409, {"error": "concurrency_conflict", "detail": str(exc)})
            except Exception as exc:
                LOG.error(json.dumps({"event": "delta_watcher_error", "error": str(exc)}))
                self._write_json(502, {"error": "tick_failed", "detail": str(exc)})

    return DeltaWatcherHandler


def main() -> int:
    """Starts the Cloud Run HTTP server on 0.0.0.0:$PORT."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    runtime = build_runtime_from_env()
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), create_handler(runtime))
    LOG.info(json.dumps({"event": "delta_watcher_started", "port": port, "repo": runtime.repo_slug}))
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
