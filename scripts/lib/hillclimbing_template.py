"""HTML and CSS shell template for the Hillclimbing progression dashboard.

Isolates visual styles and client-side filter scripts from ledger aggregation logic
so the generated single-file HTML works identically offline and in Artifacts Service.
Uses Artifacts CSS theme tokens (--bg, --surface, --text-primary, --border, --accent)
with explicit light and dark fallbacks.
"""
from __future__ import annotations

DASHBOARD_CSS = """
:root {
  --bg: #f8fafc;
  --surface: #ffffff;
  --surface-alt: #f1f5f9;
  --text-primary: #0f172a;
  --text-muted: #475569;
  --border: #e2e8f0;
  --accent: #1a73e8;
  --pass: #137333;
  --pass-bg: #e6f4ea;
  --warn: #b06000;
  --warn-bg: #fef7e0;
  --fail: #c5221f;
  --fail-bg: #fce8e6;
  --info: #1967d2;
  --info-bg: #e8f0fe;
  --purple: #7627bb;
  --purple-bg: #f3e8fd;
  --radius: 10px;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0f172a;
    --surface: #1e293b;
    --surface-alt: #0b1220;
    --text-primary: #f1f5f9;
    --text-muted: #94a3b8;
    --border: #334155;
    --accent: #8ab4f8;
    --pass: #81c995;
    --pass-bg: #133120;
    --warn: #fdd663;
    --warn-bg: #36290c;
    --fail: #f28b82;
    --fail-bg: #3b1718;
    --info: #8ab4f8;
    --info-bg: #17253d;
    --purple: #c58af9;
    --purple-bg: #2a183b;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Inter, sans-serif;
  background: var(--bg);
  color: var(--text-primary);
  line-height: 1.5;
  padding: 24px 20px 56px;
}
.wrap { max-width: 1180px; margin: 0 auto; }
header.hero {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 22px 24px;
  margin-bottom: 18px;
}
.hero-top {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}
h1 { margin: 0 0 6px; font-size: 1.55rem; letter-spacing: -0.02em; }
h2 { margin: 0 0 12px; font-size: 1.12rem; letter-spacing: -0.01em; }
h3 { margin: 0 0 8px; font-size: 0.96rem; }
.sub { margin: 0; color: var(--text-muted); font-size: 0.92rem; }
.meta-pills { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 0.78rem;
  font-weight: 600;
  border: 1px solid var(--border);
  background: var(--surface-alt);
  color: var(--text-primary);
}
.pill.pass { background: var(--pass-bg); color: var(--pass); border-color: transparent; }
.pill.warn { background: var(--warn-bg); color: var(--warn); border-color: transparent; }
.pill.fail { background: var(--fail-bg); color: var(--fail); border-color: transparent; }
.pill.info { background: var(--info-bg); color: var(--info); border-color: transparent; }
.pill.purple { background: var(--purple-bg); color: var(--purple); border-color: transparent; }
.run-tabs { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
.run-tab {
  cursor: pointer;
  padding: 7px 14px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--surface-alt);
  color: var(--text-primary);
  font-size: 0.85rem;
  font-weight: 600;
}
.run-tab.active {
  background: var(--accent);
  color: #ffffff;
  border-color: var(--accent);
}
.grid { display: grid; gap: 16px; margin-bottom: 18px; }
.grid-3 { grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); }
.grid-2 { grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); }
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 18px 20px;
}
.kpi-label {
  font-size: 0.78rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--text-muted);
  font-weight: 700;
}
.kpi-val { font-size: 2rem; font-weight: 800; margin: 4px 0 6px; letter-spacing: -0.03em; }
.kpi-note { font-size: 0.84rem; color: var(--text-muted); margin: 0; }
.bar-track {
  height: 10px;
  background: var(--surface-alt);
  border-radius: 999px;
  overflow: hidden;
  margin: 10px 0 6px;
  display: flex;
}
.bar-fill { height: 100%; }
.bar-pass { background: var(--pass); }
.bar-fail { background: var(--fail); }
.bar-warn { background: var(--warn); }
.bar-info { background: var(--accent); }
.bar-caption {
  display: flex;
  justify-content: space-between;
  font-size: 0.76rem;
  color: var(--text-muted);
}
table { width: 100%; border-collapse: collapse; font-size: 0.86rem; }
th, td {
  text-align: left;
  padding: 9px 10px;
  border-bottom: 1px solid var(--border);
  vertical-align: top;
}
th {
  font-size: 0.76rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--text-muted);
  background: var(--surface-alt);
}
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 0.82rem; }
.proof-box {
  background: var(--surface-alt);
  border-left: 3px solid var(--accent);
  border-radius: 6px;
  padding: 10px 12px;
  margin: 8px 0;
  font-size: 0.84rem;
}
.proof-box.sec { border-left-color: var(--fail); }
.proof-box.ok { border-left-color: var(--pass); }
.filter-bar { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
.filter-btn {
  cursor: pointer;
  padding: 5px 11px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: var(--surface-alt);
  color: var(--text-primary);
  font-size: 0.8rem;
  font-weight: 600;
}
.filter-btn.active {
  background: var(--accent);
  color: #ffffff;
  border-color: var(--accent);
}
.hidden { display: none !important; }
.svg-box { width: 100%; overflow-x: auto; }
footer.sync {
  margin-top: 24px;
  padding: 14px 18px;
  border-radius: var(--radius);
  border: 1px dashed var(--border);
  background: var(--surface);
  font-size: 0.8rem;
  color: var(--text-muted);
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 8px;
}
"""

DASHBOARD_JS = """
function selectRun(runId) {
  document.querySelectorAll('.run-panel').forEach(function(el) {
    el.classList.toggle('hidden', el.dataset.run !== runId);
  });
  document.querySelectorAll('.run-tab').forEach(function(btn) {
    btn.classList.toggle('active', btn.dataset.run === runId);
  });
}

function filterFindings(runId, mode, btn) {
  var panel = document.querySelector('.run-panel[data-run="' + runId + '"]');
  if (!panel) return;
  panel.querySelectorAll('.filter-btn').forEach(function(b) {
    b.classList.remove('active');
  });
  btn.classList.add('active');
  panel.querySelectorAll('tr.finding-row').forEach(function(row) {
    var show = true;
    if (mode === 'showstopper') show = row.dataset.severity === 'showstopper';
    else if (mode === 'minor') show = row.dataset.severity === 'minor';
    else if (mode === 'escape') show = row.dataset.escape === 'true';
    else if (mode === 'workaround') show = row.dataset.status === 'workaround';
    row.classList.toggle('hidden', !show);
  });
}
"""
