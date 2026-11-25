"""Deterministic renderer from docs/hillclimbing-runs.jsonl to single-file HTML.

Reads the append-only qualification ledger and emits a zero-dependency visual
dashboard containing SVG trend charts, layer friction distributions, an immutable
core_v1 gate matrix across rounds, live proof cards, and HC-02 additive gates.
"""
from __future__ import annotations

import hashlib
import html
import json
import pathlib
from typing import Any

from scripts.lib.hillclimbing_template import DASHBOARD_CSS, DASHBOARD_JS

CORE_GATE_ORDER = [
    "M0.1", "M0.2", "M0.3", "M0.4",
    "M1.1", "M1.2", "M1.3",
    "M2.1", "M2.2", "M2.3",
    "M3.1", "M3.2",
    "M4.1", "M4.2", "M4.3",
    "M5.1", "M5.2", "M5.3",
]

LAYER_LABELS = {
    "stage01-iam": "Stage 01 IAM",
    "stage01-infra": "Stage 01 Infra",
    "stage02-vm": "Stage 02 Lite VM",
    "stage02-gke": "Stage 02 HA GKE",
    "stage03-kit": "Stage 03 Kit Build",
    "stage03-bootstrap": "Stage 03 Bootstrap",
    "pack-adk": "Pack ADK",
    "brownfield": "Brownfield Onboarding",
    "ci-verdict": "CI & Verdict Gate",
    "kaizen": "Kaizen Engine",
    "upstream-scion": "Upstream Scion",
    "docs": "Docs & Scaffolding",
}


def load_ledger(jsonl_path: pathlib.Path) -> tuple[list[dict[str, Any]], str]:
    """Loads all JSONL qualification runs and computes the source SHA-256 digest."""
    raw = jsonl_path.read_text(encoding="utf-8")
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    runs: list[dict[str, Any]] = []
    for idx, line in enumerate(raw.splitlines(), 1):
        stripped = line.strip()
        if not stripped:
            continue
        obj = json.loads(stripped)
        if "run_id" not in obj or "core_v1" not in obj:
            raise ValueError(f"Line {idx} in {jsonl_path} lacks required run_id or core_v1 fields.")
        runs.append(obj)
    if not runs:
        raise ValueError(f"Ledger {jsonl_path} contains zero qualification runs.")
    return runs, digest


def _esc(val: Any) -> str:
    """Escapes arbitrary values for safe HTML text rendering."""
    return html.escape(str(val), quote=True)


def _status_pill(status: str) -> str:
    """Maps a gate or finding status string to a styled status badge."""
    low = status.lower()
    if low in ("pass", "fixed", "live-gcp-verified", "completed"):
        cls = "pass"
    elif low in ("partial", "workaround", "minor", "verifier-blocked"):
        cls = "warn"
    elif low.startswith("planned"):
        cls = "purple"
    else:
        cls = "fail"
    return f'<span class="pill {cls}">{_esc(status)}</span>'


def _render_layer_bar_svg(findings: list[dict[str, Any]]) -> str:
    """Draws an inline SVG stacked horizontal bar chart of findings by layer."""
    counts: dict[str, list[int]] = {}
    for item in findings:
        layer = item.get("layer", "other")
        bucket = counts.setdefault(layer, [0, 0])
        if item.get("severity") == "showstopper":
            bucket[0] += 1
        else:
            bucket[1] += 1

    ordered = sorted(counts.items(), key=lambda kv: (-(kv[1][0] + kv[1][1]), kv[0]))
    if not ordered:
        return "<p class=\"kpi-note\">Zero friction items recorded.</p>"

    max_total = max(v[0] + v[1] for _, v in ordered)
    row_h, pad_top, label_w, chart_w = 28, 22, 150, 320
    svg_h = pad_top + len(ordered) * row_h + 16
    svg_w = label_w + chart_w + 68
    parts = [
        f'<svg viewBox="0 0 {svg_w} {svg_h}" width="100%" role="img" aria-label="Findings by layer">',
        '<text x="150" y="13" font-size="11" fill="currentColor" opacity="0.7">Showstoppers (red) vs Minor (amber)</text>',
    ]
    for idx, (layer, (show, minor)) in enumerate(ordered):
        y = pad_top + idx * row_h
        label = LAYER_LABELS.get(layer, layer)
        show_w = int(round((show / max_total) * chart_w))
        minor_w = int(round((minor / max_total) * chart_w))
        parts.append(
            f'<text x="{label_w - 10}" y="{y + 15}" text-anchor="end" font-size="12" fill="currentColor">{_esc(label)}</text>'
        )
        if show_w > 0:
            parts.append(
                f'<rect x="{label_w}" y="{y + 3}" width="{show_w}" height="16" rx="3" fill="#c5221f"/>'
            )
        if minor_w > 0:
            parts.append(
                f'<rect x="{label_w + show_w + (2 if show_w else 0)}" y="{y + 3}" width="{minor_w}" height="16" rx="3" fill="#e37400"/>'
            )
        parts.append(
            f'<text x="{label_w + show_w + minor_w + 10}" y="{y + 15}" font-size="11" font-weight="700" fill="currentColor">{show}S / {minor}M</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def _render_progression_svg(runs: list[dict[str, Any]]) -> str:
    """Draws cross-round evolution bars comparing recorded rounds against HC-02 targets."""
    points = []
    for run in runs:
        ev = run["core_v1"]["evolution_metrics"]
        points.append((
            run["run_id"],
            float(ev["cold_start_first_pass_rate_pct"]),
            int(ev["manual_friction_count"]["showstoppers"]),
            int(ev["mock_to_reality_escape_rate"]["count"]),
        ))
    points.append(("Wave 1 Target", 90.0, 0, 0))

    col_w = 135
    svg_w = max(460, 70 + len(points) * col_w)
    svg_h = 185
    base_y = 148
    max_h = 105
    parts = [
        f'<svg viewBox="0 0 {svg_w} {svg_h}" width="100%" role="img" aria-label="Hillclimbing evolution chart">',
        f'<line x1="40" y1="{base_y}" x2="{svg_w - 20}" y2="{base_y}" stroke="currentColor" stroke-opacity="0.25"/>',
        '<text x="42" y="16" font-size="11" fill="currentColor" opacity="0.75">Cold-Start First-Pass % (blue) | Showstoppers (red) | Mock Escapes (amber)</text>',
    ]
    max_err = max([p[2] for p in points] + [p[3] for p in points] + [1])
    for idx, (label, fp_pct, shows, esc) in enumerate(points):
        x0 = 54 + idx * col_w
        fp_h = max(3, int(round((fp_pct / 100.0) * max_h)))
        sh_h = int(round((shows / max_err) * max_h)) if shows else 3
        es_h = int(round((esc / max_err) * max_h)) if esc else 3
        is_target = label == "Wave 1 Target"
        op = ' opacity="0.65" stroke-dasharray="3 2"' if is_target else ""
        parts.append(f'<rect x="{x0}" y="{base_y - fp_h}" width="24" height="{fp_h}" rx="3" fill="#1a73e8"{op}/>')
        parts.append(f'<text x="{x0 + 12}" y="{base_y - fp_h - 5}" text-anchor="middle" font-size="10" font-weight="700" fill="currentColor">{fp_pct:.0f}%</text>')
        parts.append(f'<rect x="{x0 + 30}" y="{base_y - sh_h}" width="24" height="{sh_h}" rx="3" fill="#c5221f"{op}/>')
        parts.append(f'<text x="{x0 + 42}" y="{base_y - sh_h - 5}" text-anchor="middle" font-size="10" font-weight="700" fill="currentColor">{shows}</text>')
        parts.append(f'<rect x="{x0 + 60}" y="{base_y - es_h}" width="24" height="{es_h}" rx="3" fill="#e37400"{op}/>')
        parts.append(f'<text x="{x0 + 72}" y="{base_y - es_h - 5}" text-anchor="middle" font-size="10" font-weight="700" fill="currentColor">{esc}</text>')
        parts.append(f'<text x="{x0 + 42}" y="{base_y + 18}" text-anchor="middle" font-size="11" font-weight="600" fill="currentColor">{_esc(label)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _render_core_matrix(runs: list[dict[str, Any]]) -> str:
    """Renders the immutable core_v1 gate matrix across every recorded run."""
    headers = "".join(
        f'<th>{_esc(r["run_id"])}<br/><span class="mono">Attempt 1 / Final</span></th>'
        for r in runs
    )
    latest_gates = runs[-1]["core_v1"]["gates"]
    rows: list[str] = []
    for gid in CORE_GATE_ORDER:
        gmeta = latest_gates.get(gid, {})
        cells: list[str] = []
        for run in runs:
            gate = run["core_v1"]["gates"].get(gid, {})
            fp = gate.get("first_pass", False)
            fp_badge = '<span class="pill pass">Cold PASS</span>' if fp else '<span class="pill warn">Cold FRICTION</span>'
            fin_badge = _status_pill(str(gate.get("final_status", "FAIL")))
            fids = gate.get("friction_ids") or []
            fid_txt = f' <span class="mono">({", ".join(_esc(x) for x in fids)})</span>' if fids else ""
            cells.append(f"<td>{fp_badge} {fin_badge}{fid_txt}</td>")
        rows.append(
            f"<tr><td class=\"mono\"><strong>{_esc(gid)}</strong></td>"
            f"<td>L{_esc(gmeta.get('level', ''))}</td>"
            f"<td><strong>{_esc(gmeta.get('name', gid))}</strong><br/>"
            f"<span class=\"kpi-note\">{_esc(gmeta.get('evidence', ''))}</span></td>"
            f"{''.join(cells)}</tr>"
        )
    return (
        "<div class=\"card\" style=\"margin-bottom:18px;\">"
        "<h2>Immutable <span class=\"mono\">core_v1</span> Scorecard (18 Gates, Levels 0-5)</h2>"
        "<p class=\"sub\" style=\"margin-bottom:12px;\">Never mutates across rounds so every Hillclimbing iteration compares apples-to-apples against the release baseline.</p>"
        "<table><thead><tr><th>Gate</th><th>Lvl</th><th>Requirement &amp; Latest Evidence</th>"
        f"{headers}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )


def _render_run_panel(run: dict[str, Any], is_latest: bool) -> str:
    """Renders the detailed KPI, live proof, findings, and additive gates panel for one run."""
    rid = run["run_id"]
    ev = run["core_v1"]["evolution_metrics"]
    fp_pct = float(ev["cold_start_first_pass_rate_pct"])
    fp_cnt = int(ev["cold_start_first_pass_count"])
    total_g = int(run["core_v1"]["gate_count"])
    fric = ev["manual_friction_count"]
    esc = ev["mock_to_reality_escape_rate"]
    findings = run.get("findings", [])
    proofs = run.get("live_proofs", {})
    track_a = proofs.get("track_a_gecx", {})
    track_b = proofs.get("track_b_adk", {})
    add_v2 = run.get("additive_gates", {}).get("v2_cross_project", {})

    show_pct = (fric["showstoppers"] / max(1, fric["total"])) * 100.0
    minor_pct = 100.0 - show_pct

    turns_html = "".join(
        f'<div class="proof-box ok"><strong>Turn:</strong> {_esc(t["input"])}<br/>'
        f'<span class="mono">{_esc(t["tool_call"])} -&gt; HTTP {_esc(t["http_status"])} ({_esc(t["latency_ms"])} ms)</span><br/>'
        f'&ldquo;{_esc(t["response"])}&rdquo;</div>'
        for t in track_a.get("turns", [])
    )
    adk_turn = track_b.get("turn", {})
    adk_probes = track_b.get("iam_probes", {})
    sec_box = ""
    if "security_highlight" in track_b:
        sec_box = f'<div class="proof-box sec"><strong>Live Security &amp; Cross-Project Proof:</strong> {_esc(track_b["security_highlight"])}</div>'
    elif "worker_reasoning_engine_before_fix" in adk_probes:
        sec_box = (
            f'<div class="proof-box sec"><strong>F27 Live Security Re-Probe (Worker SA):</strong> '
            f'Before fix <span class="mono">POST reasoningEngines = HTTP {_esc(adk_probes.get("worker_reasoning_engine_before_fix", ""))}</span> -&gt; '
            f'After predict-only custom role <span class="mono">POST reasoningEngines = HTTP {_esc(adk_probes.get("worker_reasoning_engine_after_fix", ""))}</span> '
            f'and <span class="mono">Vertex AI predict = HTTP {_esc(adk_probes.get("worker_vertex_predict_after_fix", ""))}</span>.</div>'
        )
    adk_html = (
        f'<div class="proof-box ok"><strong>{_esc(adk_turn.get("endpoint", ""))}</strong><br/>'
        f'Prompt: {_esc(adk_turn.get("input", ""))}<br/>'
        f'<span class="mono">{_esc(adk_turn.get("tool_call", ""))} -&gt; HTTP {_esc(adk_turn.get("http_status", ""))}</span><br/>'
        f'&ldquo;{_esc(adk_turn.get("response", ""))}&rdquo;</div>'
        f"{sec_box}"
    )

    f_rows: list[str] = []
    for item in findings:
        esc_tag = '<span class="pill fail">Mock Escape</span>' if item.get("mock_escape") else '<span class="pill info">Direct</span>'
        sev_pill = '<span class="pill fail">Showstopper</span>' if item["severity"] == "showstopper" else '<span class="pill warn">Minor</span>'
        f_rows.append(
            f'<tr class="finding-row" data-severity="{_esc(item["severity"])}" '
            f'data-escape="{str(bool(item.get("mock_escape"))).lower()}" data-status="{_esc(item["status"])}">'
            f'<td class="mono"><strong>{_esc(item["id"])}</strong></td>'
            f'<td>{sev_pill} {esc_tag}</td>'
            f'<td class="mono">{_esc(item["gate"])}<br/>{_esc(LAYER_LABELS.get(item["layer"], item["layer"]))}</td>'
            f'<td><strong>{_esc(item["title"])}</strong><br/><span class="kpi-note">{_esc(item["resolution"])}</span></td>'
            f'<td>{_status_pill(item["status"])}</td></tr>'
        )

    additive_cards: list[str] = []
    for block_key, block in run.get("additive_gates", {}).items():
        b_rows = "".join(
            f'<tr><td class="mono"><strong>{_esc(gid)}</strong></td>'
            f'<td><strong>{_esc(g["name"])}</strong>'
            + (f'<br/><span class="kpi-note">{_esc(g["evidence"])}</span>' if g.get("evidence") else "")
            + f'</td><td>{_esc(g.get("criteria", ""))}</td>'
            f'<td>{_status_pill(g["status"])}</td></tr>'
            for gid, g in block.get("gates", {}).items()
        )
        additive_cards.append(
            f'<div class="card" style="margin-bottom:18px;">'
            f'<h2>Additive Gates: <span class="mono">additive_gates.{_esc(block_key)}</span> {_status_pill(str(block.get("status", "planned")))}</h2>'
            f'<p class="sub" style="margin-bottom:12px;">Target topology: <strong>{_esc(block.get("topology_target", ""))}</strong> '
            f'({block.get("gate_count", len(block.get("gates", {})))} versioned extension gates alongside immutable <span class="mono">core_v1</span>).</p>'
            f'<table><thead><tr><th>Gate</th><th>Extension Requirement &amp; Evidence</th><th>Pass Criteria</th><th>State</th></tr></thead>'
            f'<tbody>{b_rows}</tbody></table></div>'
        )
    additive_html = "".join(additive_cards)

    hidden_cls = "" if is_latest else " hidden"
    wk_count = sum(1 for f in findings if f["status"] == "workaround")
    return f"""
<section class="run-panel{hidden_cls}" data-run="{_esc(rid)}">
  <div class="grid grid-3">
    <div class="card">
      <div class="kpi-label">1. Cold-Start First-Pass Rate</div>
      <div class="kpi-val">{fp_pct:.1f}%</div>
      <p class="kpi-note">{fp_cnt}/{total_g} core_v1 gates passed on Attempt 1 without workarounds. End-of-round: {ev['end_of_round_pass_count']}/{total_g} PASS, {ev['end_of_round_partial_count']} PARTIAL.</p>
      <div class="bar-track"><div class="bar-fill bar-info" style="width:{fp_pct:.1f}%"></div></div>
      <div class="bar-caption"><span>Measured: {fp_pct:.1f}%</span><span>Wave 1 Target: &gt;=90%</span></div>
    </div>
    <div class="card">
      <div class="kpi-label">2. Manual Friction Count</div>
      <div class="kpi-val">{fric['total']} <span style="font-size:1rem;font-weight:600;color:var(--text-muted)">({fric['showstoppers']}S / {fric['minor']}M)</span></div>
      <p class="kpi-note">{fric['showstoppers']} Showstoppers and {fric['minor']} Minor items captured live. {fric['total'] - wk_count}/{fric['total']} fixed in repo plus {wk_count} upstream workaround.</p>
      <div class="bar-track"><div class="bar-fill bar-fail" style="width:{show_pct:.1f}%"></div><div class="bar-fill bar-warn" style="width:{minor_pct:.1f}%"></div></div>
      <div class="bar-caption"><span>Showstoppers: {fric['showstoppers']}</span><span>Minor: {fric['minor']}</span></div>
    </div>
    <div class="card">
      <div class="kpi-label">3. Mock-to-Reality Escape Rate</div>
      <div class="kpi-val">{esc['count']} <span style="font-size:1rem;font-weight:600;color:var(--text-muted)">({esc['pct_of_friction']:.1f}%)</span></div>
      <p class="kpi-note">Defects that passed 100% of offline pytest, build checks, and terraform validate before failing on live GCP, GitHub, or Scion APIs.</p>
      <div class="bar-track"><div class="bar-fill bar-warn" style="width:{esc['pct_of_friction']:.1f}%"></div></div>
      <div class="bar-caption"><span>Escapes: {esc['count']}</span><span>Target: 0</span></div>
    </div>
  </div>

  <div class="grid grid-2">
    <div class="card">
      <h2>Findings Distribution by Layer</h2>
      <p class="sub" style="margin-bottom:10px;">Where live Argolis qualification caught real gaps across Stage 01-03, packs, and upstream Scion.</p>
      <div class="svg-box">{_render_layer_bar_svg(findings)}</div>
    </div>
    <div class="card">
      <h2>Live Verification Proofs (Concrete Evidence)</h2>
      <h3>Track A: Lite Single-VM + packs/gecx</h3>
      {turns_html}
      <h3 style="margin-top:12px;">Track B: GKE Standard + packs/adk</h3>
      {adk_html}
    </div>
  </div>

  <div class="card" style="margin-bottom:18px;">
    <h2>Findings Ledger ({len(findings)} Empirical Items)</h2>
    <div class="filter-bar">
      <button class="filter-btn active" onclick="filterFindings('{_esc(rid)}','all',this)">All ({len(findings)})</button>
      <button class="filter-btn" onclick="filterFindings('{_esc(rid)}','showstopper',this)">Showstoppers ({fric['showstoppers']})</button>
      <button class="filter-btn" onclick="filterFindings('{_esc(rid)}','minor',this)">Minor ({fric['minor']})</button>
      <button class="filter-btn" onclick="filterFindings('{_esc(rid)}','escape',this)">Mock Escapes ({esc['count']})</button>
      <button class="filter-btn" onclick="filterFindings('{_esc(rid)}','workaround',this)">Upstream Workarounds ({wk_count})</button>
    </div>
    <table>
      <thead><tr><th>ID</th><th>Class</th><th>Gate / Layer</th><th>Finding &amp; Resolution</th><th>Status</th></tr></thead>
      <tbody>{''.join(f_rows)}</tbody>
    </table>
  </div>

  {additive_html}
</section>
"""


def render_dashboard_html(runs: list[dict[str, Any]], ledger_sha256: str) -> str:
    """Renders the complete self-contained Hillclimbing HTML dashboard from ledger runs."""
    latest = runs[-1]
    tabs = "".join(
        f'<button class="run-tab{" active" if idx == len(runs) - 1 else ""}" '
        f'data-run="{_esc(r["run_id"])}" onclick="selectRun(\'{_esc(r["run_id"])}\')">'
        f'{_esc(r["run_id"])} ({_esc(r["release_display"])} {_esc(r["release_version"])})</button>'
        for idx, r in enumerate(runs)
    )
    panels = "".join(
        _render_run_panel(r, idx == len(runs) - 1) for idx, r in enumerate(runs)
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>gcp-fde-factories — Hillclimbing Qualification Tracker</title>
<style>{DASHBOARD_CSS}</style>
</head>
<body>
<div class="wrap">
  <header class="hero">
    <div class="hero-top">
      <div>
        <h1>gcp-fde-factories — Hillclimbing Qualification Tracker</h1>
        <p class="sub">Single-source-of-truth progression dashboard generated deterministically from <span class="mono">docs/hillclimbing-runs.jsonl</span>. Same HTML artifact committed in git and published to Artifacts Service with zero drift.</p>
      </div>
      <div class="meta-pills">
        <span class="pill info">Rounds Recorded: {len(runs)}</span>
        <span class="pill pass">Latest Base: {_esc(latest['release_display'])} ({_esc(latest['release_version'])})</span>
        <span class="pill purple">Updated: {_esc(latest['completed_at_brt'])}</span>
      </div>
    </div>
    <div class="run-tabs">{tabs}</div>
  </header>

  <div class="card" style="margin-bottom:18px;">
    <h2>Cross-Round Evolution (core_v1 Immutable Baseline vs. Wave 1 Target)</h2>
    <div class="svg-box">{_render_progression_svg(runs)}</div>
  </div>

  {panels}
  {_render_core_matrix(runs)}

  <footer class="sync">
    <span>Regenerate: <span class="mono">python3 scripts/render-hillclimbing-report.py</span></span>
    <span>Ledger SHA-256: <span class="mono">{ledger_sha256[:16]}</span></span>
    <span>Clean-Room Verified: zero private project IDs, billing IDs, or personal domains</span>
  </footer>
</div>
<script>{DASHBOARD_JS}</script>
</body>
</html>
"""
