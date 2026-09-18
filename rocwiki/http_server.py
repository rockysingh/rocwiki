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
<html>
<head>
  <meta charset="utf-8">
  <title>RocWiki</title>
  <style>
    :root { color-scheme: light dark; }
    body { font-family: ui-sans-serif, system-ui, sans-serif; margin: 0; padding: 24px; max-width: 1100px; margin-inline: auto; }
    h1 { margin-top: 0; font-size: 1.4rem; }
    h2 { font-size: 1.05rem; margin-top: 2rem; border-bottom: 1px solid #8884; padding-bottom: 4px; }
    .row { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
    input[type=search], select { padding: 6px 10px; font-size: 0.9rem; border-radius: 4px; border: 1px solid #8884; }
    input[type=search] { flex: 1; min-width: 240px; }
    .card { border: 1px solid #8884; border-radius: 6px; padding: 12px; margin: 10px 0; }
    .card h3 { margin: 0 0 4px 0; font-size: 1rem; }
    .meta { color: #888; font-size: 0.8rem; }
    .kind { display: inline-block; padding: 1px 6px; background: #7773; border-radius: 3px; font-size: 0.75rem; margin-right: 6px; }
    .body { white-space: pre-wrap; font-size: 0.9rem; margin-top: 8px; }
    .stats { font-size: 0.85rem; color: #888; }
    details { margin: 6px 0; }
    summary { cursor: pointer; }
  </style>
</head>
<body>
  <h1>RocWiki</h1>
  <div class="stats" id="stats">loading stats...</div>

  <div class="row" style="margin: 16px 0;">
    <input id="q" type="search" placeholder="search...">
    <select id="table">
      <option value="both">both</option>
      <option value="knowledge">knowledge</option>
      <option value="short_term">short_term</option>
    </select>
    <select id="kind">
      <option value="">all kinds</option>
      <option>domain</option><option>pattern</option><option>decision</option>
      <option>question</option><option>person</option><option>reference</option>
      <option>pr-review</option><option>incident</option><option>ops-note</option><option>task</option>
    </select>
  </div>

  <div id="results"></div>

  <script>
    const $q = document.getElementById('q');
    const $tbl = document.getElementById('table');
    const $kind = document.getElementById('kind');
    const $results = document.getElementById('results');
    const $stats = document.getElementById('stats');

    async function renderStats() {
      const r = await fetch('/api/stats').then(r => r.json());
      const bits = [];
      for (const [tbl, s] of Object.entries(r.tables)) {
        bits.push(`${tbl}: ${s.total} (${Object.entries(s.by_kind).map(([k,v]) => k+':'+v).join(', ')})`);
      }
      $stats.textContent = bits.join(' — ');
    }

    function renderCard(e) {
      const refs = e.refs ? Object.entries(e.refs).map(([k,v]) => `${k}: ${Array.isArray(v)?v.join(', '):v}`).join(' | ') : '';
      const src = e.source ? `<span class="kind">${e.source}</span>` : '';
      return `<div class="card">
        <h3>${src}<span class="kind">${e.kind}</span>${e.title}</h3>
        <div class="meta">id ${e.id} · updated ${e.updated_at} · status ${e.status} · tags: ${e.tags || ''}</div>
        <details><summary>body</summary><div class="body">${(e.body||'').replace(/</g,'&lt;')}</div></details>
        ${refs ? `<div class="meta" style="margin-top:6px">refs: ${refs}</div>` : ''}
      </div>`;
    }

    async function runSearch() {
      const q = $q.value.trim();
      const t = $tbl.value;
      const k = $kind.value;
      let entries = [];
      if (q) {
        const url = `/api/search?q=${encodeURIComponent(q)}&table=${t}&limit=50` + (k ? `&kind=${k}` : '');
        entries = (await fetch(url).then(r=>r.json())).results || [];
      } else {
        const tables = t === 'both' ? ['knowledge','short_term'] : [t];
        for (const table of tables) {
          const url = `/api/${table}?limit=25` + (k ? `&kind=${k}` : '');
          const r = await fetch(url).then(r=>r.json());
          (r.entries||[]).forEach(e => { e.source = table; entries.push(e); });
        }
      }
      $results.innerHTML = entries.length ? entries.map(renderCard).join('') : '<div class="meta">no results</div>';
    }

    $q.addEventListener('input', runSearch);
    $tbl.addEventListener('change', runSearch);
    $kind.addEventListener('change', runSearch);
    renderStats().then(runSearch);
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