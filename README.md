# rocwiki

A local, per-project wiki backed by SQLite, exposed as **both** a Model Context Protocol (MCP) server *and* an HTTP + HTML dashboard.

It's the missing "notes / knowledge base" layer for AI-agent workflows: your coding agent (Claude Code, Claude Desktop, or anything speaking MCP) writes findings, decisions, patterns, and open questions into it via native tool calls, then searches back into it on the next session — without stuffing the prompt with a giant memory file.

- **MCP surface** — Claude invokes `wiki_search`, `wiki_add`, `wiki_promote`, etc. as first-class tool calls. Only tool results enter the prompt.
- **HTTP + HTML surface** — a small self-contained dashboard at `http://127.0.0.1:8787/` for humans, plus a JSON REST API at `/api/*` for anything else you want to layer on top.
- **Two tables, one philosophy**: `knowledge` is long-term (product truths, patterns, decisions); `short_term` is prunable (PR reviews, incidents, tasks). Both are FTS5-indexed. Short-term entries can be promoted to knowledge with one call.
- **Per-project** — each project gets its own SQLite file under `~/.rocwiki/projects/<slug>/context.db`. Slug is auto-detected from your git repo.

Everything runs locally over SQLite. No cloud, no accounts, no external services.

---

## Table of contents

- [Why](#why)
- [How it works](#how-it-works)
- [Install](#install)
- [Quick start](#quick-start)
- [CLI reference](#cli-reference)
- [MCP tools](#mcp-tools)
- [HTTP API](#http-api)
- [Web dashboard](#web-dashboard)
- [Schema](#schema)
- [Configuration](#configuration)
- [Wire into Claude Code](#wire-into-claude-code)
- [Wire into Claude Desktop](#wire-into-claude-desktop)
- [Recipes](#recipes)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [License](#license)

---

## Why

Large-language-model coding assistants have short-term memory only. Every session starts blank unless you paste your notes back in. If you paste too much, you burn tokens on stuff you might not need this session. If you paste too little, you re-do work you already did last week.

rocwiki gives the agent a persistent, queryable, per-project notebook it can search *on demand*. It's the practical unit of "the thing I would have written down if I'd had time" — code patterns, WTF gotchas, open design questions, recurring incidents, decisions with rationale, people and roles, PR-review findings — all in one small SQLite file per project.

Because it speaks MCP, the agent adds and retrieves entries as ordinary tool calls, so nothing enters the prompt unless it's the search result you asked for.

## How it works

- Two SQLite tables (`knowledge`, `short_term`), each with an FTS5 virtual-table mirror kept in sync by triggers.
- The same process can serve stdio MCP (`rocwiki mcp`) or HTTP (`rocwiki http`).
- One database per project. Project slug is resolved by (in order): `--project` flag → `ROCWIKI_PROJECT` env var → `git rev-parse --show-toplevel` basename → cwd basename → `default`.
- DB path defaults to `~/.rocwiki/projects/<slug>/context.db`, overridable with `ROCWIKI_DB=/some/other/path.db`.

No migrations to manage: the schema is idempotent (`CREATE TABLE IF NOT EXISTS`), and `rocwiki init` will lay it down on first use.

## Install

Requires Python 3.11+.

```bash
git clone https://github.com/rockysingh/rocwiki.git ~/tools/rocwiki
cd ~/tools/rocwiki
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e .
```

Verify:

```bash
~/tools/rocwiki/.venv/bin/rocwiki --help
~/tools/rocwiki/.venv/bin/rocwiki stats
```

(Optional) drop the venv binary onto your `PATH`:

```bash
ln -s ~/tools/rocwiki/.venv/bin/rocwiki ~/.local/bin/rocwiki
```

## Quick start

Create a project DB from inside any git repo — the slug comes from your repo name:

```bash
cd ~/code/my-app
rocwiki init
rocwiki stats
```

Add a knowledge entry:

```bash
rocwiki http &   # start dashboard on http://127.0.0.1:8787/
curl -s -X POST http://127.0.0.1:8787/api/knowledge \
  -H 'content-type: application/json' \
  -d '{
    "kind": "pattern",
    "title": "Never mock the payments client in integration tests",
    "body": "We got burned in Q2 when a mocked client masked a real 4xx from the provider. Integration tests always hit the sandbox.",
    "tags": "testing,payments,gotcha",
    "refs": {"prs": [1234], "people": ["rockysingh"]}
  }'
```

Search:

```bash
curl -s 'http://127.0.0.1:8787/api/search?q=mock+integration&limit=5' | jq .
```

## CLI reference

```
rocwiki [--project SLUG] SUBCOMMAND [args...]

  init         Create or upgrade schema for the current project.
  stats        Print counts by kind / status, latest updated timestamp, DB path.
  projects     List every project DB currently on disk with size.

  mcp          Run the stdio MCP server (for Claude Code / Desktop).
  http         Run the HTTP dashboard + JSON API. --host / --port supported.
```

Examples:

```bash
# Auto-detect from git repo (basename)
cd ~/code/my-app && rocwiki stats

# Explicit project
rocwiki --project side-project init
rocwiki --project side-project stats

# List everything on disk
rocwiki projects

# Point at a specific db file, no project resolution
ROCWIKI_DB=/tmp/scratch.db rocwiki stats

# HTTP server on a different port
rocwiki http --port 9000

# Bind on all interfaces (be careful — no auth)
rocwiki http --host 0.0.0.0 --port 8787
```

## MCP tools

The MCP server exposes eight tools. Types below are the ones an MCP client sees.

| Tool | Signature | Returns |
|---|---|---|
| `wiki_search` | `(query, table="both", kind=None, limit=10)` | list of entries, bm25-ranked |
| `wiki_get` | `(table, entry_id)` | single entry or `None` |
| `wiki_list` | `(table, kind=None, status=None, limit=25, offset=0)` | list, most-recently-updated first |
| `wiki_add` | `(table, kind, title, body, tags?, refs?, status="active")` | the created entry |
| `wiki_update` | `(table, entry_id, title?, body?, tags?, refs?, status?, kind?)` | updated entry |
| `wiki_delete` | `(table, entry_id)` | `bool` |
| `wiki_promote` | `(short_term_id, kind)` | the created knowledge entry |
| `wiki_stats` | `()` | counts by table/kind/status + db_path |

Argument notes:

- `table` is `knowledge`, `short_term`, or (for `wiki_search`) `both`.
- `knowledge` kinds: `domain`, `pattern`, `decision`, `question`, `person`, `reference`.
- `short_term` kinds: `pr-review`, `incident`, `ops-note`, `task`.
- `refs` is a free-form dict; the convention we use is `{"prs":[…],"issues":[…],"files":[…],"commits":[…],"people":[…]}` but any JSON-serializable object works.
- `wiki_search` FTS syntax is SQLite FTS5 — plain keywords work, use `"quoted phrases"` for phrases, `AND`/`OR`/`NOT` for boolean, `^col:` for column restriction.

## HTTP API

Base URL: `http://127.0.0.1:8787` (or whatever host/port you pass to `rocwiki http`).

| Method | Path | Body / Query | Response |
|---|---|---|---|
| `GET` | `/` | — | HTML dashboard |
| `GET` | `/api/stats` | — | `{tables:{knowledge:{…},short_term:{…}}, db_path, project}` |
| `GET` | `/api/search` | `?q=&table=both&kind=&limit=10` | `{results:[…], count}` |
| `GET` | `/api/knowledge` | `?kind=&status=&limit=25&offset=0` | `{entries:[…], count}` |
| `GET` | `/api/short_term` | `?kind=&status=&limit=25&offset=0` | `{entries:[…], count}` |
| `GET` | `/api/{table}/{id}` | — | single entry, `404` if missing |
| `POST` | `/api/{table}` | `{kind, title, body, tags?, refs?, status?}` | `201` + the created entry |

Errors are always `{"error": "..."}` with an HTTP 4xx status.

### curl examples

```bash
# Stats
curl -s http://127.0.0.1:8787/api/stats | jq .

# Search across both tables
curl -s 'http://127.0.0.1:8787/api/search?q=mirror+node+dns&limit=5' | jq .

# List active questions
curl -s 'http://127.0.0.1:8787/api/knowledge?kind=question&status=active' | jq .

# Get one entry
curl -s http://127.0.0.1:8787/api/knowledge/12 | jq .

# Add a short-term entry
curl -s -X POST http://127.0.0.1:8787/api/short_term \
  -H 'content-type: application/json' \
  -d '{
    "kind":"pr-review",
    "title":"PR #1234 review — 2 nits, non-blocking",
    "body":"...",
    "tags":"pr-review,payments",
    "refs":{"prs":[1234]}
  }' | jq .
```

## Web dashboard

`GET /` serves a self-contained single-page HTML dashboard with:

- Live stats bar (total per table, breakdown by kind).
- Search input that queries `/api/search` as you type, with table and kind filters.
- Card view for each result: kind chip, title, updated-at, status, tags, expandable body, refs list.

There is no auth. Run behind localhost only unless you add your own.

## Schema

Two tables share the same shape.

```sql
CREATE TABLE knowledge (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at    TEXT NOT NULL,               -- ISO 8601 UTC
    updated_at    TEXT NOT NULL,               -- ISO 8601 UTC
    kind          TEXT NOT NULL,               -- see kinds below
    title         TEXT NOT NULL,
    body          TEXT NOT NULL,               -- markdown
    tags          TEXT,                        -- comma-separated
    refs_json     TEXT,                        -- JSON blob
    status        TEXT DEFAULT 'active'        -- active | superseded | resolved
);
CREATE INDEX idx_knowledge_kind    ON knowledge(kind);
CREATE INDEX idx_knowledge_status  ON knowledge(status);
CREATE INDEX idx_knowledge_updated ON knowledge(updated_at);

CREATE VIRTUAL TABLE knowledge_fts USING fts5(
    title, body, tags,
    content='knowledge', content_rowid='id',
    tokenize='porter unicode61'
);
-- + AI / AD / AU triggers to keep FTS in sync
```

`short_term` is structurally identical; only the valid `kind` values differ. Both tables have an FTS5 mirror and sync triggers so searches stay in step with edits.

`kind` values are validated in Python before insert/update. Everything else is free-form.

## Configuration

| Variable | Purpose | Default |
|---|---|---|
| `ROCWIKI_DB` | Full path to a specific SQLite file; overrides project resolution entirely. | — |
| `ROCWIKI_PROJECT` | Project slug; used when `--project` is not passed. | — |

Project resolution when `ROCWIKI_DB` is unset:

1. `--project SLUG` flag.
2. `ROCWIKI_PROJECT` env var.
3. `git rev-parse --show-toplevel` basename (if you're inside a git repo).
4. Basename of your current working directory.
5. Literal `default`.

Slugs are sanitized (`[^a-zA-Z0-9_.-]+` collapsed to `-`).

## Using it with Claude

Once you've wired rocwiki into Claude Code (or Claude Desktop) via the MCP config below, Claude sees eight tools it can call natively:

`mcp__rocwiki__wiki_search`, `mcp__rocwiki__wiki_get`, `mcp__rocwiki__wiki_list`, `mcp__rocwiki__wiki_add`, `mcp__rocwiki__wiki_update`, `mcp__rocwiki__wiki_delete`, `mcp__rocwiki__wiki_promote`, `mcp__rocwiki__wiki_stats`.

You don't need to remember tool names — talk to Claude naturally and it will pick the right one. A few starter prompts to try:

**Ask Claude to look something up:**

> Check my wiki for anything on WebSocket reconnect logic in this repo.

Claude calls `wiki_search("WebSocket reconnect", table="both")` and only the matching entries come back into the conversation.

**Ask Claude to save what you're discussing:**

> Save this as a pattern: we always run migrations behind a feature flag on Fridays. Tag it with `deploy,migration,gotcha`.

Claude calls `wiki_add(table="knowledge", kind="pattern", title="Fridays: migrations behind a feature flag", body="…", tags="deploy,migration,gotcha")`.

**Log a PR review for later:**

> Note that PR #4021 has a subtle race in the token refresh path. Store it as a PR review.

Claude calls `wiki_add(table="short_term", kind="pr-review", title="PR #4021 — token refresh race", body="…", refs={"prs":[4021]})`.

**Promote a short-term finding once it proves durable:**

> That PR-review note about the race turned out to be a general pattern in our auth layer. Promote it to a pattern.

Claude calls `wiki_promote(short_term_id=…, kind="pattern")`.

**Ask for a summary at the start of a session:**

> What's in the wiki for this project? Show me the open questions and recent decisions.

Claude calls `wiki_stats()` plus `wiki_list(table="knowledge", kind="question", status="active")` and summarizes.

**Suggested project-level habit for Claude:**

Add a note like the following to your project's `CLAUDE.md` (or the system-prompt equivalent your tool uses) so Claude reaches for the wiki reflexively:

```
This project has rocwiki wired in via MCP. Before answering questions
about ongoing work, patterns, or open questions, call wiki_search first.
When you learn something worth remembering (a decision, a gotcha, a
recurring incident), save it with wiki_add — use `knowledge` for
long-term truths and `short_term` for PR reviews and one-off ops notes.
```

## Wire into Claude Code

Add to `~/.claude.json` (or a per-project `.mcp.json`):

```json
{
  "mcpServers": {
    "rocwiki": {
      "command": "/absolute/path/to/rocwiki/.venv/bin/rocwiki",
      "args": ["mcp"]
    }
  }
}
```

Claude Code launches the MCP server with cwd set to your project root, so auto-detect will pick the correct project DB.

To pin a specific project regardless of cwd:

```json
{
  "mcpServers": {
    "rocwiki-notes": {
      "command": "/absolute/path/to/rocwiki/.venv/bin/rocwiki",
      "args": ["--project", "notes", "mcp"]
    }
  }
}
```

Restart Claude Code. Tools appear as `mcp__rocwiki__wiki_search`, `mcp__rocwiki__wiki_add`, etc.

## Wire into Codex

OpenAI Codex CLI supports MCP servers via `~/.codex/config.toml`:

```toml
[mcp_servers.rocwiki]
command = "/absolute/path/to/rocwiki/.venv/bin/rocwiki"
args    = ["mcp"]
```

Or pin a specific project:

```toml
[mcp_servers.rocwiki-notes]
command = "/absolute/path/to/rocwiki/.venv/bin/rocwiki"
args    = ["--project", "notes", "mcp"]
```

Restart the Codex CLI. Tools appear namespaced as `rocwiki__wiki_search`, `rocwiki__wiki_add`, etc. (Codex tool naming is close to Claude's; the exact prefix may depend on the Codex version — check `codex mcp list` after restart.)

If your Codex build uses a JSON config instead of TOML (older releases), the equivalent shape is:

```json
{
  "mcpServers": {
    "rocwiki": {
      "command": "/absolute/path/to/rocwiki/.venv/bin/rocwiki",
      "args": ["mcp"]
    }
  }
}
```

## Wire into Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

```json
{
  "mcpServers": {
    "rocwiki": {
      "command": "/absolute/path/to/rocwiki/.venv/bin/rocwiki",
      "args": ["mcp"]
    }
  }
}
```

Then quit and restart Claude Desktop.

## Recipes

**Promote a short-term finding to knowledge:**

```python
# via MCP tool call inside your agent
wiki_promote(short_term_id=42, kind="pattern")
```

This copies the entry into `knowledge` as a `pattern`, and marks the source `short_term` row as `resolved`.

**Add a decision with structured refs:**

```python
wiki_add(
    table="knowledge",
    kind="decision",
    title="Adopt Turbo Repo for the monorepo",
    body="Chosen over Nx because … see PR #987 for the migration checklist.",
    tags="build,monorepo",
    refs={"prs": [987], "people": ["alice", "bob"]},
)
```

**Search only open questions on the long-term table:**

```python
wiki_search(query="signature verification", table="knowledge", kind="question")
```

**Sync notes across machines** — the whole DB is a single `~/.rocwiki/projects/<slug>/context.db` file. rsync, git-annex, iCloud, whatever. Watch out for concurrent-writer WAL contention if multiple machines write at once.

## Troubleshooting

**`error: unsafe use of virtual table "..._fts"`** — you're on a very old SQLite. rocwiki sets `PRAGMA trusted_schema=1` on every connection, but if you're seeing this outside the CLI, make sure your embedding tool does the same before executing the schema.

**Auto-detected the wrong project.** Force it with `--project my-slug` or `ROCWIKI_PROJECT=my-slug`.

**Dashboard shows old data.** The dashboard fetches on load and on every filter change; refresh the page. If a tool call went through the MCP surface, it's already committed and visible.

**Multiple processes writing at once.** SQLite in WAL mode handles multiple readers + one writer. If both the MCP server and HTTP server are running against the same file, that's fine (they contend as needed).

**Move a DB between machines.** Copy the file at `~/.rocwiki/projects/<slug>/context.db` (and the `.wal` / `.shm` sidecars if they exist) to the same relative path on the target machine.

**Reset a project.** `rm -rf ~/.rocwiki/projects/<slug>/` then `rocwiki --project <slug> init`.

## Development

```bash
git clone https://github.com/rockysingh/rocwiki.git
cd rocwiki
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e .
```

Run the tests (once added — currently there are none):

```bash
.venv/bin/pip install pytest
.venv/bin/pytest
```

The code is intentionally small — three modules:

```
rocwiki/
├── __main__.py     # CLI dispatcher
├── db.py           # SQLite + project resolution + CRUD
├── mcp_server.py   # FastMCP tools
└── http_server.py  # Starlette routes + HTML dashboard
```

## License

Apache-2.0. See [LICENSE](./LICENSE).