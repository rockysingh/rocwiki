"""MCP server exposing RocWiki tools over stdio."""

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
        "worth pulling back into a future session; prefer short_term for ephemeral findings. "
        "When adding entries, pass source_ai (e.g. 'claude-code', 'codex') and source_model so "
        "cross-tool authorship stays queryable. Pass `project` to route to a specific project DB; "
        "otherwise the server's default project is used."
    ),
)


@mcp.tool
def wiki_search(
    query: str,
    table: str = "both",
    kind: Optional[str] = None,
    limit: int = 10,
    project: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Full-text search across the wiki (FTS5, bm25-ranked)."""
    return db.search(query=query, table=table, kind=kind, limit=limit, project=project)  # type: ignore[arg-type]


@mcp.tool
def wiki_get(table: str, entry_id: int, project: Optional[str] = None) -> Optional[dict[str, Any]]:
    """Fetch a single entry by id from `knowledge` or `short_term`."""
    return db.get_entry(table=table, entry_id=entry_id, project=project)


@mcp.tool
def wiki_list(
    table: str,
    kind: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 25,
    offset: int = 0,
    project: Optional[str] = None,
) -> list[dict[str, Any]]:
    """List entries from a table, most-recently-updated first."""
    return db.list_entries(
        table=table, kind=kind, status=status, limit=limit, offset=offset, project=project
    )


@mcp.tool
def wiki_add(
    table: str,
    kind: str,
    title: str,
    body: str,
    tags: Optional[str] = None,
    refs: Optional[dict[str, Any]] = None,
    status: str = "active",
    source_ai: Optional[str] = None,
    source_model: Optional[str] = None,
    project: Optional[str] = None,
) -> dict[str, Any]:
    """Add a new entry.

    Args:
        table:        'knowledge' or 'short_term'.
        kind:         knowledge kinds: domain, pattern, decision, question, person, reference.
                      short_term kinds: pr-review, incident, ops-note, task.
        title:        short one-line summary.
        body:         markdown body with the details.
        tags:         optional comma-separated tags.
        refs:         optional dict, e.g. {"prs":[3645],"issues":[3644],"files":["..."],"people":["..."]}
        status:       'active' (default), 'resolved', 'superseded', 'stale'.
        source_ai:    which AI tool authored this entry (e.g. 'claude-code', 'codex', 'cursor', 'human').
                      Recommend always passing this so cross-tool provenance stays queryable.
        source_model: which model authored (e.g. 'claude-opus-4-7', 'gpt-5').
        project:      optional project slug override.
    """
    return db.add_entry(
        table=table, kind=kind, title=title, body=body, tags=tags, refs=refs, status=status,
        source_ai=source_ai, source_model=source_model, project=project,
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
    source_ai: Optional[str] = None,
    source_model: Optional[str] = None,
    project: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Update fields on an existing entry. Only provided fields are changed."""
    return db.update_entry(
        table=table, entry_id=entry_id, kind=kind, title=title, body=body, tags=tags,
        refs=refs, status=status, source_ai=source_ai, source_model=source_model, project=project,
    )


@mcp.tool
def wiki_delete(table: str, entry_id: int, project: Optional[str] = None) -> bool:
    """Delete an entry. Returns True if a row was removed."""
    return db.delete_entry(table=table, entry_id=entry_id, project=project)


@mcp.tool
def wiki_promote(
    short_term_id: int, kind: str, project: Optional[str] = None
) -> Optional[dict[str, Any]]:
    """Promote a short_term entry into knowledge with the given kind.

    Copies title/body/tags/refs into knowledge, marks the source short_term row as resolved.
    """
    return db.promote_to_knowledge(short_term_id=short_term_id, kind=kind, project=project)


@mcp.tool
def wiki_stats(project: Optional[str] = None) -> dict[str, Any]:
    """Return counts by table, kind, and status, plus last-updated timestamps and db_path."""
    return db.stats(project=project)


@mcp.tool
def wiki_projects() -> list[dict[str, Any]]:
    """List every project DB currently on disk with slug, path, and size."""
    return db.list_projects()


def run() -> None:
    """Entry point for stdio MCP mode."""
    db.init_schema()
    mcp.run()