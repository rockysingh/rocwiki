"""MCP server exposing RocWiki tools over stdio for Claude Code."""

from __future__ import annotations

from typing import Any, Optional

from fastmcp import FastMCP

from . import db

mcp = FastMCP(
    name="rocwiki",
    instructions=(
        "Local wiki backed by SQLite. Two tables: 'knowledge' (long-term product/domain/"
        "pattern/decision/question/person/reference) and 'short_term' (pr-review, incident, "
        "ops-note, task). Search across both with wiki_search. Prefer knowledge for anything "
        "worth pulling back into a future session; prefer short_term for ephemeral findings."
    ),
)


@mcp.tool
def wiki_search(
    query: str,
    table: str = "both",
    kind: Optional[str] = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Full-text search across the wiki.

    Args:
        query: FTS5 query. Simple keywords work; use quotes for phrases (`"mirror node"`).
        table: 'both' (default), 'knowledge', or 'short_term'.
        kind:  Optional filter, e.g. 'pattern', 'decision', 'question', 'pr-review'.
        limit: Max results (default 10).

    Returns list of entries sorted by relevance (bm25).
    """
    return db.search(query=query, table=table, kind=kind, limit=limit)  # type: ignore[arg-type]


@mcp.tool
def wiki_get(table: str, entry_id: int) -> Optional[dict[str, Any]]:
    """Fetch a single entry by id from `knowledge` or `short_term`."""
    return db.get_entry(table=table, entry_id=entry_id)


@mcp.tool
def wiki_list(
    table: str,
    kind: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 25,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List entries from a table, most-recently-updated first.

    Args:
        table:  'knowledge' or 'short_term'.
        kind:   optional filter by kind.
        status: optional filter by status ('active', 'resolved', 'superseded', 'stale').
        limit:  page size (default 25).
        offset: pagination offset.
    """
    return db.list_entries(table=table, kind=kind, status=status, limit=limit, offset=offset)


@mcp.tool
def wiki_add(
    table: str,
    kind: str,
    title: str,
    body: str,
    tags: Optional[str] = None,
    refs: Optional[dict[str, Any]] = None,
    status: str = "active",
) -> dict[str, Any]:
    """Add a new entry.

    Args:
        table: 'knowledge' or 'short_term'.
        kind:  knowledge kinds: domain, pattern, decision, question, person, reference.
               short_term kinds: pr-review, incident, ops-note, task.
        title: short one-line summary.
        body:  markdown body with the details.
        tags:  optional comma-separated tags.
        refs:  optional dict, e.g. {"prs":[3645],"issues":[3644],"files":["path/to/file"],"people":["ata-nas"]}
        status: 'active' (default), 'resolved', 'superseded', 'stale'.
    """
    return db.add_entry(
        table=table, kind=kind, title=title, body=body, tags=tags, refs=refs, status=status
    )


@mcp.tool
def wiki_update(
    table: str,
    entry_id: int,
    title: Optional[str] = None,
    body: Optional[str] = None,
    tags: Optional[str] = None,
    refs: Optional[dict[str, Any]] = None,
    status: Optional[str] = None,
    kind: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Update fields on an existing entry. Only provided fields are changed."""
    return db.update_entry(
        table=table,
        entry_id=entry_id,
        kind=kind,
        title=title,
        body=body,
        tags=tags,
        refs=refs,
        status=status,
    )


@mcp.tool
def wiki_delete(table: str, entry_id: int) -> bool:
    """Delete an entry. Returns True if a row was removed."""
    return db.delete_entry(table=table, entry_id=entry_id)


@mcp.tool
def wiki_promote(short_term_id: int, kind: str) -> Optional[dict[str, Any]]:
    """Promote a short_term entry into knowledge with the given kind.

    Copies title/body/tags/refs into knowledge, marks the source short_term row as resolved.
    Use when a PR-review finding, incident, or ops-note turns out to be worth long-term recall.
    """
    return db.promote_to_knowledge(short_term_id=short_term_id, kind=kind)


@mcp.tool
def wiki_stats() -> dict[str, Any]:
    """Return counts by table, kind, and status, plus last-updated timestamps and db_path."""
    return db.stats()


def run() -> None:
    """Entry point for stdio MCP mode."""
    db.init_schema()
    mcp.run()