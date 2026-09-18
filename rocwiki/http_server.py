"""HTTP surface for RocWiki. Small JSON API plus a self-contained HTML dashboard."""

from __future__ import annotations

import json
from typing import Any

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from . import db


def _json(value: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(value, status_code=status)


async def route_stats(request: Request) -> JSONResponse:
    return _json(db.stats())


async def route_list(request: Request) -> JSONResponse:
    table = request.path_params["table"]
    kind = request.query_params.get("kind")
    status = request.query_params.get("status")
    try:
        limit = int(request.query_params.get("limit", "50"))
        offset = int(request.query_params.get("offset", "0"))
    except ValueError:
        return _json({"error": "limit and offset must be integers"}, status=400)
    try:
        entries = db.list_entries(table=table, kind=kind, status=status, limit=limit, offset=offset)
    except ValueError as e:
        return _json({"error": str(e)}, status=400)
    return _json({"entries": entries, "count": len(entries)})


async def route_get(request: Request) -> JSONResponse:
    table = request.path_params["table"]
    try:
        entry_id = int(request.path_params["entry_id"])
    except ValueError:
        return _json({"error": "entry_id must be an integer"}, status=400)
    try:
        entry = db.get_entry(table=table, entry_id=entry_id)
    except ValueError as e:
        return _json({"error": str(e)}, status=400)
    if entry is None:
        return _json({"error": "not found"}, status=404)
    return _json(entry)


async def route_search(request: Request) -> JSONResponse:
    query = request.query_params.get("q", "")
    table = request.query_params.get("table", "both")
    kind = request.query_params.get("kind")
    try:
        limit = int(request.query_params.get("limit", "10"))
    except ValueError:
        return _json({"error": "limit must be an integer"}, status=400)
    try:
        results = db.search(query=query, table=table, kind=kind, limit=limit)  # type: ignore[arg-type]
    except ValueError as e:
        return _json({"error": str(e)}, status=400)
    return _json({"results": results, "count": len(results)})


async def route_add(request: Request) -> JSONResponse:
    table = request.path_params["table"]
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return _json({"error": "request body must be JSON"}, status=400)
    if not isinstance(payload, dict):
        return _json({"error": "request body must be a JSON object"}, status=400)
    try:
        entry = db.add_entry(
            table=table,
            kind=payload["kind"],
            title=payload["title"],
            body=payload["body"],
            tags=payload.get("tags"),
            refs=payload.get("refs"),
            status=payload.get("status", "active"),
        )
    except KeyError as e:
        return _json({"error": f"missing required field: {e.args[0]}"}, status=400)
    except ValueError as e:
        return _json({"error": str(e)}, status=400)
    return _json(entry, status=201)


DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>rocwiki</title>
  <style>
    /* ── Theme tokens ────────────────────────────────────────────────── */
    /* Default: Dracula (dark). Toggle to a solarised-light variant. */
    :root {
      --bg:            #282a36;
      --bg-elev:       #21222c;
      --bg-card:       #2d2f3f;
      --bg-card-hover: #343648;
      --fg:            #f8f8f2;
      --fg-muted:      #a8adc8;
      --fg-dim:        #6272a4;
      --border:        #44475a;
      --accent:        #bd93f9;   /* purple  */
      --accent-2:      #ff79c6;   /* pink    */
      --cyan:          #8be9fd;
      --green:         #50fa7b;
      --yellow:        #f1fa8c;
      --orange:        #ffb86c;
      --red:           #ff5555;
      --link:          #8be9fd;
      --font-sans:     ui-sans-serif, -apple-system, "SF Pro Text", "Segoe UI", system-ui, sans-serif;
      --font-mono:     "JetBrains Mono", "SF Mono", ui-monospace, Menlo, Consolas, monospace;
      --radius:        8px;
      --shadow-card:   0 1px 0 rgba(255,255,255,0.03) inset, 0 1px 2px rgba(0,0,0,0.35);
      color-scheme: dark;
    }
    :root[data-theme="light"] {
      --bg:            #fdf6e3;
      --bg-elev:       #eee8d5;
      --bg-card:       #ffffff;
      --bg-card-hover: #f5efd7;
      --fg:            #073642;
      --fg-muted:      #586e75;
      --fg-dim:        #93a1a1;
      --border:        #e0dbc8;
      --accent:        #6c71c4;
      --accent-2:      #d33682;
      --cyan:          #2aa198;
      --green:         #859900;
      --yellow:        #b58900;
      --orange:        #cb4b16;
      --red:           #dc322f;
      --link:          #268bd2;
      --shadow-card:   0 1px 0 rgba(0,0,0,0.02) inset, 0 1px 2px rgba(0,0,0,0.08);
      color-scheme: light;
    }

    /* ── Base ──────────────────────────────────────────────────────────── */
    * { box-sizing: border-box; }
    html, body { background: var(--bg); color: var(--fg); }
    body {
      font-family: var(--font-sans);
      margin: 0;
      min-height: 100vh;
      font-size: 14px;
      line-height: 1.55;
    }
    a { color: var(--link); text-decoration: none; }
    a:hover { text-decoration: underline; }
    code, pre { font-family: var(--font-mono); font-size: 0.85em; }
    code { background: var(--bg-elev); padding: 1px 5px; border-radius: 3px; color: var(--cyan); }
    pre {
      background: var(--bg-elev); border: 1px solid var(--border);
      border-radius: 6px; padding: 10px 12px; overflow-x: auto;
      color: var(--fg);
    }
    pre code { background: none; padding: 0; color: inherit; }

    /* ── Layout ────────────────────────────────────────────────────────── */
    .app { max-width: 1180px; margin-inline: auto; padding: 20px 24px 60px; }
    header.top {
      display: flex; align-items: center; gap: 12px;
      padding: 8px 0 16px; border-bottom: 1px solid var(--border);
      position: sticky; top: 0; background: var(--bg); z-index: 10;
    }
    header.top .brand { font-size: 1.15rem; font-weight: 600; letter-spacing: 0.02em; color: var(--accent); }
    header.top .brand::before { content: "◆ "; color: var(--accent-2); }
    header.top .grow { flex: 1; }
    .icon-btn {
      background: var(--bg-elev); border: 1px solid var(--border); color: var(--fg);
      border-radius: 6px; padding: 6px 10px; font-family: var(--font-mono);
      font-size: 0.8rem; cursor: pointer;
    }
    .icon-btn:hover { background: var(--bg-card-hover); border-color: var(--accent); }

    .stats-strip {
      display: flex; gap: 16px; flex-wrap: wrap;
      padding: 12px 0; color: var(--fg-muted); font-size: 0.82rem;
    }
    .stat { display: flex; align-items: baseline; gap: 6px; }
    .stat .n { color: var(--fg); font-weight: 600; font-variant-numeric: tabular-nums; }
    .stat .lbl { color: var(--fg-dim); }
    .stat .k { color: var(--fg-muted); font-family: var(--font-mono); font-size: 0.78em; }

    /* ── Tabs ──────────────────────────────────────────────────────────── */
    .tabs {
      display: flex; gap: 4px; margin: 10px 0 4px;
      border-bottom: 1px solid var(--border);
      font-family: var(--font-mono);
      font-size: 0.85rem;
    }
    .tab {
      background: none; border: none; color: var(--fg-muted);
      padding: 8px 14px 10px; cursor: pointer;
      border-bottom: 2px solid transparent;
      display: flex; align-items: center; gap: 8px;
      transition: color 0.12s ease, border-color 0.12s ease;
    }
    .tab:hover { color: var(--fg); }
    .tab[aria-selected="true"] {
      color: var(--accent);
      border-bottom-color: var(--accent);
    }
    .tab .badge {
      background: var(--bg-elev); color: var(--fg-dim);
      border-radius: 10px; padding: 1px 8px;
      font-size: 0.72rem; font-variant-numeric: tabular-nums;
      border: 1px solid var(--border);
    }
    .tab[aria-selected="true"] .badge {
      color: var(--accent);
      border-color: color-mix(in srgb, var(--accent) 45%, var(--border));
    }

    /* ── Filter bar ────────────────────────────────────────────────────── */
    .controls {
      display: flex; gap: 10px; flex-wrap: wrap; align-items: center;
      padding: 14px 0 18px;
    }
    .controls input[type=search], .controls select {
      background: var(--bg-elev); border: 1px solid var(--border);
      color: var(--fg); border-radius: 6px; padding: 8px 12px;
      font-size: 0.9rem; font-family: var(--font-sans);
    }
    .controls input[type=search] {
      flex: 1; min-width: 260px;
      font-family: var(--font-mono);
    }
    .controls input[type=search]:focus,
    .controls select:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 25%, transparent); }
    .controls select { cursor: pointer; }

    /* ── Cards ─────────────────────────────────────────────────────────── */
    #results { display: grid; grid-template-columns: 1fr; gap: 12px; }
    .card {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 14px 16px;
      box-shadow: var(--shadow-card);
      transition: background 0.12s ease, border-color 0.12s ease;
    }
    .card:hover { background: var(--bg-card-hover); border-color: color-mix(in srgb, var(--accent) 35%, var(--border)); }
    .card h3 { margin: 0 0 6px 0; font-size: 1rem; font-weight: 600; color: var(--fg); display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
    .card .title-text { flex: 1; min-width: 0; }

    .chip {
      display: inline-flex; align-items: center;
      padding: 2px 8px; border-radius: 999px;
      font-family: var(--font-mono); font-size: 0.7rem;
      font-weight: 500; letter-spacing: 0.03em;
      border: 1px solid var(--border);
      background: var(--bg-elev);
      color: var(--fg-muted);
    }
    /* Kind-specific chip colors */
    .chip.k-domain     { color: var(--cyan);   border-color: color-mix(in srgb, var(--cyan) 45%, var(--border)); }
    .chip.k-pattern    { color: var(--accent); border-color: color-mix(in srgb, var(--accent) 45%, var(--border)); }
    .chip.k-decision   { color: var(--accent-2); border-color: color-mix(in srgb, var(--accent-2) 45%, var(--border)); }
    .chip.k-question   { color: var(--yellow); border-color: color-mix(in srgb, var(--yellow) 45%, var(--border)); }
    .chip.k-person     { color: var(--green);  border-color: color-mix(in srgb, var(--green) 45%, var(--border)); }
    .chip.k-reference  { color: var(--fg-muted); }
    .chip.k-pr-review  { color: var(--accent-2); border-color: color-mix(in srgb, var(--accent-2) 45%, var(--border)); }
    .chip.k-incident   { color: var(--red);    border-color: color-mix(in srgb, var(--red) 45%, var(--border)); }
    .chip.k-ops-note   { color: var(--orange); border-color: color-mix(in srgb, var(--orange) 45%, var(--border)); }
    .chip.k-task       { color: var(--yellow); border-color: color-mix(in srgb, var(--yellow) 45%, var(--border)); }
    /* Source chip */
    .chip.src-knowledge  { color: var(--cyan);   border-color: color-mix(in srgb, var(--cyan) 45%, var(--border)); }
    .chip.src-short_term { color: var(--orange); border-color: color-mix(in srgb, var(--orange) 45%, var(--border)); }

    .meta {
      color: var(--fg-dim); font-size: 0.78rem; font-family: var(--font-mono);
      display: flex; gap: 12px; flex-wrap: wrap; align-items: center;
    }
    .meta .sep { color: var(--border); }
    .meta .tags a {
      background: var(--bg-elev); border: 1px solid var(--border);
      border-radius: 3px; padding: 1px 6px; margin-right: 4px;
      color: var(--fg-muted); text-decoration: none; font-size: 0.78em;
    }

    details { margin: 10px 0 0; }
    details summary {
      cursor: pointer; color: var(--fg-muted); font-size: 0.82rem;
      list-style: none; user-select: none;
    }
    details summary::-webkit-details-marker { display: none; }
    details summary::before { content: "▸ "; color: var(--accent); }
    details[open] summary::before { content: "▾ "; }
    details .body {
      margin-top: 10px; padding: 10px 12px;
      background: var(--bg-elev); border-left: 3px solid var(--accent);
      border-radius: 4px;
      white-space: pre-wrap;
      color: var(--fg);
      font-size: 0.88rem;
    }
    .refs {
      margin-top: 8px; font-size: 0.78rem; color: var(--fg-dim);
      font-family: var(--font-mono);
    }
    .refs .rk { color: var(--accent); }

    .empty {
      color: var(--fg-dim); font-style: italic; padding: 40px; text-align: center;
      border: 1px dashed var(--border); border-radius: 8px;
    }

    /* narrow */
    @media (max-width: 640px) {
      .app { padding: 16px; }
      .controls input[type=search] { min-width: 100%; }
    }
  </style>
</head>
<body>
  <div class="app">
    <header class="top">
      <div class="brand">rocwiki</div>
      <div class="grow"></div>
      <button class="icon-btn" id="theme-btn" title="toggle theme">☾ dark</button>
    </header>

    <div class="stats-strip" id="stats"><span class="stat"><span class="lbl">loading…</span></span></div>

    <nav class="tabs" role="tablist" id="tabs">
      <button class="tab" role="tab" data-table="both" aria-selected="true">All <span class="badge" id="badge-both">·</span></button>
      <button class="tab" role="tab" data-table="knowledge" aria-selected="false">Knowledge <span class="badge" id="badge-knowledge">·</span></button>
      <button class="tab" role="tab" data-table="short_term" aria-selected="false">Short-Term <span class="badge" id="badge-short_term">·</span></button>
    </nav>

    <div class="controls">
      <input id="q" type="search" placeholder="search  (FTS5: keywords, &quot;quoted phrases&quot;, AND/OR/NOT)" autofocus>
      <select id="kind" title="kind"></select>
    </div>

    <div id="results"></div>
  </div>

  <script>
    const $q = document.getElementById('q');
    const $kind = document.getElementById('kind');
    const $results = document.getElementById('results');
    const $stats = document.getElementById('stats');
    const $tabs = document.getElementById('tabs');
    const $themeBtn = document.getElementById('theme-btn');
    const THEME_KEY = 'rocwiki-theme';
    const TAB_KEY = 'rocwiki-tab';

    const KNOWLEDGE_KINDS = ['domain','pattern','decision','question','person','reference'];
    const SHORT_TERM_KINDS = ['pr-review','incident','ops-note','task'];
    let activeTable = localStorage.getItem(TAB_KEY) || 'both';

    function applyTheme(t) {
      if (t === 'light') {
        document.documentElement.setAttribute('data-theme', 'light');
        $themeBtn.textContent = '☀ light';
      } else {
        document.documentElement.removeAttribute('data-theme');
        $themeBtn.textContent = '☾ dark';
      }
      localStorage.setItem(THEME_KEY, t);
    }
    (function initTheme() {
      const saved = localStorage.getItem(THEME_KEY);
      if (saved) return applyTheme(saved);
      const prefersLight = matchMedia('(prefers-color-scheme: light)').matches;
      applyTheme(prefersLight ? 'light' : 'dark');
    })();
    $themeBtn.addEventListener('click', () => {
      const cur = document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
      applyTheme(cur === 'light' ? 'dark' : 'light');
    });

    function esc(s) { return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

    async function renderStats() {
      const r = await fetch('/api/stats').then(r => r.json());
      const bits = [];
      bits.push(`<span class="stat"><span class="lbl">project</span><span class="n">${esc(r.project || '?')}</span></span>`);
      let both = 0;
      for (const [tbl, s] of Object.entries(r.tables)) {
        both += s.total;
        const badge = document.getElementById('badge-' + tbl);
        if (badge) badge.textContent = s.total;
        const kinds = Object.entries(s.by_kind).map(([k,v]) => `<span class="k">${esc(k)}:${v}</span>`).join(' ');
        bits.push(`<span class="stat"><span class="lbl">${esc(tbl)}</span><span class="n">${s.total}</span> ${kinds}</span>`);
      }
      const badgeBoth = document.getElementById('badge-both');
      if (badgeBoth) badgeBoth.textContent = both;
      $stats.innerHTML = bits.join('');
    }

    function populateKindOptions() {
      let options = ['<option value="">all kinds</option>'];
      if (activeTable === 'both' || activeTable === 'knowledge') {
        options.push('<optgroup label="knowledge">' +
          KNOWLEDGE_KINDS.map(k => `<option>${k}</option>`).join('') + '</optgroup>');
      }
      if (activeTable === 'both' || activeTable === 'short_term') {
        options.push('<optgroup label="short_term">' +
          SHORT_TERM_KINDS.map(k => `<option>${k}</option>`).join('') + '</optgroup>');
      }
      const prev = $kind.value;
      $kind.innerHTML = options.join('');
      const still = Array.from($kind.options).some(o => o.value === prev);
      $kind.value = still ? prev : '';
    }

    function setActiveTab(table) {
      activeTable = table;
      localStorage.setItem(TAB_KEY, table);
      $tabs.querySelectorAll('.tab').forEach(b => {
        b.setAttribute('aria-selected', String(b.dataset.table === table));
      });
      populateKindOptions();
      runSearch();
    }
    $tabs.addEventListener('click', ev => {
      const t = ev.target.closest('.tab');
      if (t) setActiveTab(t.dataset.table);
    });

    function renderCard(e) {
      const kindClass = 'k-' + esc(e.kind);
      const srcChip = e.source ? `<span class="chip src-${esc(e.source)}">${esc(e.source)}</span>` : '';
      const kindChip = `<span class="chip ${kindClass}">${esc(e.kind)}</span>`;
      const tags = (e.tags || '').split(',').filter(Boolean).map(t => `<a href="#" data-tag="${esc(t.trim())}">#${esc(t.trim())}</a>`).join('');
      const refs = e.refs ? Object.entries(e.refs)
        .filter(([,v]) => v && (Array.isArray(v) ? v.length : true))
        .map(([k,v]) => `<span class="rk">${esc(k)}:</span> ${Array.isArray(v) ? v.map(esc).join(', ') : esc(v)}`)
        .join(' &nbsp;·&nbsp; ') : '';
      return `<article class="card">
        <h3>${srcChip}${kindChip}<span class="title-text">${esc(e.title)}</span></h3>
        <div class="meta">
          <span>id ${esc(e.id)}</span><span class="sep">·</span>
          <span>updated ${esc((e.updated_at||'').slice(0,10))}</span><span class="sep">·</span>
          <span>status ${esc(e.status)}</span>
          ${tags ? `<span class="sep">·</span><span class="tags">${tags}</span>` : ''}
        </div>
        <details><summary>body</summary><div class="body">${esc(e.body)}</div></details>
        ${refs ? `<div class="refs">refs: ${refs}</div>` : ''}
      </article>`;
    }

    async function runSearch() {
      const q = $q.value.trim();
      const t = activeTable;
      const k = $kind.value;
      let entries = [];
      try {
        if (q) {
          const url = `/api/search?q=${encodeURIComponent(q)}&table=${t}&limit=50` + (k ? `&kind=${k}` : '');
          entries = (await fetch(url).then(r=>r.json())).results || [];
        } else {
          const tables = t === 'both' ? ['knowledge','short_term'] : [t];
          for (const table of tables) {
            const url = `/api/${table}?limit=40` + (k ? `&kind=${k}` : '');
            const r = await fetch(url).then(r=>r.json());
            (r.entries||[]).forEach(e => { e.source = table; entries.push(e); });
          }
          entries.sort((a,b) => (b.updated_at||'').localeCompare(a.updated_at||''));
        }
      } catch (err) {
        $results.innerHTML = `<div class="empty">error: ${esc(err.message)}</div>`;
        return;
      }
      $results.innerHTML = entries.length
        ? entries.map(renderCard).join('')
        : '<div class="empty">no results</div>';
      document.querySelectorAll('.tags a').forEach(a => a.addEventListener('click', ev => {
        ev.preventDefault();
        $q.value = a.dataset.tag;
        runSearch();
      }));
    }

    let debounce;
    $q.addEventListener('input', () => { clearTimeout(debounce); debounce = setTimeout(runSearch, 120); });
    $kind.addEventListener('change', runSearch);
    // initial paint: apply persisted tab (sets tab aria + fills kinds + runs search)
    setActiveTab(activeTable);
    renderStats();
  </script>
</body>
</html>"""


async def route_index(request: Request) -> HTMLResponse:
    return HTMLResponse(DASHBOARD_HTML)


routes = [
    Route("/", route_index),
    Route("/api/stats", route_stats),
    Route("/api/search", route_search),
    Route("/api/{table}", route_list),
    Route("/api/{table}", route_add, methods=["POST"]),
    Route("/api/{table}/{entry_id}", route_get),
]

app = Starlette(routes=routes)


def run(host: str = "127.0.0.1", port: int = 8787) -> None:
    """Entry point for HTTP mode."""
    db.init_schema()
    uvicorn.run(app, host=host, port=port, log_level="info")