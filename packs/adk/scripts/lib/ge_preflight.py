"""Zero-PII Gemini Enterprise license and UserStore preflight checks for ADK Sandbox registration.

Separates IAM authorization failures (HTTP 403) from missing Gemini Enterprise project licenses
or disabled auto-registration (HTTP 400 FAILED_PRECONDITION) before adk-deployer calls agents:create.
Queries project metadata only (licenseConfigs and default_user_store) and never reads userLicenses.
"""
from __future__ import annotations

import re
from typing import Any

from .ge_payload import HttpRequestFn, default_http_request

PROJECT_SEG_RE = re.compile(r"^[a-z0-9-]+$")
VALID_GE_LOCATIONS = ("global", "us", "eu")


def _endpoint_prefix(location: str) -> str:
    """Returns the Discovery Engine host prefix for a validated location."""
    return "" if location == "global" else f"{location}-"


def _error_text(body: dict[str, Any]) -> str:
    """Flattens a Discovery Engine error payload to lowercase text for classification."""
    return str(body.get("error", body)).lower()


def classify_ge_registration_error(status_code: int, body: dict[str, Any]) -> str:
    """Classifies a Discovery Engine agents:create or agents:patch HTTP response."""
    if 200 <= status_code < 300:
        return "OK"
    text = _error_text(body)
    if status_code == 400 and (
        "active gemini enterprise license" in text
        or "license config quota" in text
        or "required subscriptions" in text
    ):
        return "LICENSE_REQUIRED"
    if status_code == 403:
        if "service_disabled" in text or "has not been used in project" in text:
            return "API_DISABLED"
        return "IAM_DENIED"
    if status_code == 429:
        return "QUOTA_EXCEEDED"
    return "API_ERROR"


def preflight_ge_registration(
    project_id: str,
    location: str,
    token: str,
    quota_project: str = "",
    endpoint_location: str = "",
    http_fn: HttpRequestFn = default_http_request,
) -> dict[str, Any]:
    """Checks Discovery Engine licenseConfigs and default_user_store before agents:create."""
    project_seg = project_id.strip()
    if not PROJECT_SEG_RE.fullmatch(project_seg):
        raise ValueError(f"Invalid GCP project identifier for GE preflight: '{project_id}'")
    loc = location.strip()
    if loc not in VALID_GE_LOCATIONS:
        raise ValueError(f"Unsupported GE location '{location}'. Expected one of {VALID_GE_LOCATIONS}.")
    ep_loc = (endpoint_location or loc).strip()
    if ep_loc not in VALID_GE_LOCATIONS:
        raise ValueError(f"Unsupported GE endpoint_location '{ep_loc}'.")

    prefix = _endpoint_prefix(ep_loc)
    headers = {
        "Authorization": f"Bearer {token}",
        "x-goog-user-project": (quota_project or project_seg).strip(),
    }
    lc_url = (
        f"https://{prefix}discoveryengine.googleapis.com/v1alpha/"
        f"projects/{project_seg}/locations/{loc}/licenseConfigs"
    )
    us_url = (
        f"https://{prefix}discoveryengine.googleapis.com/v1alpha/"
        f"projects/{project_seg}/locations/{loc}/userStores/default_user_store"
    )

    lc_status, lc_body = http_fn("GET", lc_url, headers, None)
    if lc_status == 0 or lc_status >= 500:
        return {
            "status": "TRANSPORT_ERROR",
            "ready": False,
            "http_status": lc_status,
            "project": project_seg,
            "location": loc,
            "detail": _error_text(lc_body)[:300],
        }
    if lc_status == 403:
        cat = classify_ge_registration_error(lc_status, lc_body)
        return {
            "status": cat,
            "ready": False,
            "http_status": lc_status,
            "project": project_seg,
            "location": loc,
            "remediation": (
                "Enable discoveryengine.googleapis.com on the Sandbox project."
                if cat == "API_DISABLED"
                else "Grant discoveryengine.licenseConfigs.list and discoveryengine.userStores.get to adkSandboxDeployer."
            ),
        }
    if lc_status != 200:
        return {
            "status": "API_ERROR",
            "ready": False,
            "http_status": lc_status,
            "project": project_seg,
            "location": loc,
            "detail": _error_text(lc_body)[:300],
        }

    raw_configs = lc_body.get("licenseConfigs") or []
    active_configs = [
        cfg for cfg in raw_configs if isinstance(cfg, dict) and str(cfg.get("state", "")).upper() == "ACTIVE"
    ]
    active_names = [str(cfg.get("name", "")) for cfg in active_configs if cfg.get("name")]

    if not active_names:
        return {
            "status": "NO_PROJECT_LICENSE",
            "ready": False,
            "project": project_seg,
            "location": loc,
            "active_license_configs": [],
            "total_license_configs": len(raw_configs),
            "remediation": (
                "Distribute an active Gemini Enterprise billingAccountLicenseConfig to this project "
                "(or request free project seats in Argolis). Export dist/ge-export/ and skip agents:create retries."
            ),
        }

    us_status, us_body = http_fn("GET", us_url, headers, None)
    if us_status == 403:
        return {
            "status": "IAM_DENIED",
            "ready": False,
            "http_status": us_status,
            "project": project_seg,
            "location": loc,
            "active_license_configs": active_names,
            "remediation": "Grant discoveryengine.userStores.get to adkSandboxDeployer.",
        }
    if us_status != 200:
        return {
            "status": "API_ERROR",
            "ready": False,
            "http_status": us_status,
            "project": project_seg,
            "location": loc,
            "active_license_configs": active_names,
            "detail": _error_text(us_body)[:300],
        }

    default_cfg = str(us_body.get("defaultLicenseConfig") or "")
    auto_reg = bool(us_body.get("enableLicenseAutoRegister"))
    if auto_reg and default_cfg and default_cfg in active_names:
        return {
            "status": "READY",
            "ready": True,
            "project": project_seg,
            "location": loc,
            "active_license_configs": active_names,
            "default_license_config": default_cfg,
            "enable_license_auto_register": True,
        }

    return {
        "status": "AUTO_REGISTER_DISABLED",
        "ready": False,
        "project": project_seg,
        "location": loc,
        "active_license_configs": active_names,
        "default_license_config": default_cfg or None,
        "enable_license_auto_register": auto_reg,
        "remediation": (
            "Project has active GE licenses, but default_user_store auto-registration is disabled or points to an inactive config. "
            "Enable enableLicenseAutoRegister on default_user_store, allocate a seat to the deployer SA via batchUpdateUserLicenses, "
            "or register via a licensed human principal using dist/ge-export/."
        ),
    }
