"""SQLite access layer for RocWiki.

Two tables, both with FTS5 mirrors:
    knowledge  — long-term product/domain/pattern/decision/question/person/reference
    short_term — PR reviews, incidents, ops one-offs (prunable)
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Literal, Optional

# ────────────────────────────────────────────────────────────────────────
# Configuration — per-project DB resolution
# ────────────────────────────────────────────────────────────────────────
#
# Resolution order (highest priority first):
#   1. ROCWIKI_DB env var — full path, overrides everything
#   2. --project flag / ROCWIKI_PROJECT env var — explicit project slug
#   3. Auto-detect: `git rev-parse --show-toplevel` basename
#   4. Fallback: cwd basename
#   5. Ultimate fallback: 'default'
#
# DB path: ~/.rocwiki/projects/<slug>/context.db

ROOT_DIR = Path.home() / ".rocwiki"
PROJECTS_DIR = ROOT_DIR / "projects"

_SLUG_SAFE = re.compile(r"[^a-zA-Z0-9_.-]+")


def _slugify(name: str) -> str:
    slug = _SLUG_SAFE.sub("-", name.strip()).strip("-.")
    return slug or "default"


def _detect_project_slug() -> str:
    """Detect project slug from git root or cwd. Falls back to 'default'."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=False, timeout=2,
        )
        if result.returncode == 0 and result.stdout.strip():
            return _slugify(Path(result.stdout.strip()).name)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return _slugify(Path.cwd().name)


def current_project() -> str:
    explicit = os.environ.get("ROCWIKI_PROJECT")
    if explicit:
        return _slugify(explicit)
    return _detect_project_slug()


def project_db_path(slug: str) -> Path:
    return PROJECTS_DIR / _slugify(slug) / "context.db"


def db_path() -> Path:
    override = os.environ.get("ROCWIKI_DB")
    if override:
        return Path(override).expanduser()
    return project_db_path(current_project())


def list_projects() -> list[dict[str, Any]]:
    """Return one dict per known project DB (excluding env-var overrides)."""
    if not PROJECTS_DIR.exists():
        return []
    out: list[dict[str, Any]] = []
    for child in sorted(PROJECTS_DIR.iterdir()):
        db_file = child / "context.db"
        if db_file.exists():
            out.append({
                "slug": child.name,
                "db_path": str(db_file),
                "size_bytes": db_file.stat().st_size,
            })
    return out

TableName = Literal["knowledge", "short_term"]
VALID_TABLES: tuple[TableName, ...] = ("knowledge", "short_term")

KNOWLEDGE_KINDS = ("domain", "pattern", "decision", "question", "person", "reference")
SHORT_TERM_KINDS = ("pr-review", "incident", "ops-note", "task")


# ────────────────────────────────────────────────────────────────────────
# Schema
# ────────────────────────────────────────────────────────────────────────

SCHEMA_SQL = """
PRAGMA trusted_schema = 1;
PRAGMA journal_mode   = WAL;
PRAGMA foreign_keys   = ON;

CREATE TABLE IF NOT EXISTS knowledge (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at    TEXT    NOT NULL,
    updated_at    TEXT    NOT NULL,
    kind          TEXT    NOT NULL,
    title         TEXT    NOT NULL,
    body          TEXT    NOT NULL,
    tags          TEXT,
    refs_json     TEXT,
    status        TEXT    DEFAULT 'active'
);
CREATE INDEX IF NOT EXISTS idx_knowledge_kind    ON knowledge(kind);
CREATE INDEX IF NOT EXISTS idx_knowledge_status  ON knowledge(status);
CREATE INDEX IF NOT EXISTS idx_knowledge_updated ON knowledge(updated_at);

CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
    title, body, tags,
    content='knowledge', content_rowid='id',
    tokenize='porter unicode61'
);
CREATE TRIGGER IF NOT EXISTS knowledge_ai AFTER INSERT ON knowledge BEGIN
    INSERT INTO knowledge_fts(rowid, title, body, tags) VALUES(new.id, new.title, new.body, new.tags);
END;
CREATE TRIGGER IF NOT EXISTS knowledge_ad AFTER DELETE ON knowledge BEGIN
    INSERT INTO knowledge_fts(knowledge_fts, rowid, title, body, tags) VALUES('delete', old.id, old.title, old.body, old.tags);
END;
CREATE TRIGGER IF NOT EXISTS knowledge_au AFTER UPDATE ON knowledge BEGIN
    INSERT INTO knowledge_fts(knowledge_fts, rowid, title, body, tags) VALUES('delete', old.id, old.title, old.body, old.tags);
    INSERT INTO knowledge_fts(rowid, title, body, tags)                 VALUES(new.id, new.title, new.body, new.tags);
END;

CREATE TABLE IF NOT EXISTS short_term (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at    TEXT    NOT NULL,
    updated_at    TEXT    NOT NULL,
    kind          TEXT    NOT NULL,
    title         TEXT    NOT NULL,
    body          TEXT    NOT NULL,
    tags          TEXT,
    refs_json     TEXT,
    status        TEXT    DEFAULT 'active'
);
CREATE INDEX IF NOT EXISTS idx_short_term_kind    ON short_term(kind);
CREATE INDEX IF NOT EXISTS idx_short_term_status  ON short_term(status);
CREATE INDEX IF NOT EXISTS idx_short_term_created ON short_term(created_at);

CREATE VIRTUAL TABLE IF NOT EXISTS short_term_fts USING fts5(
    title, body, tags,
    content='short_term', content_rowid='id',
    tokenize='porter unicode61'
);
CREATE TRIGGER IF NOT EXISTS short_term_ai AFTER INSERT ON short_term BEGIN
    INSERT INTO short_term_fts(rowid, title, body, tags) VALUES(new.id, new.title, new.body, new.tags);
END;
CREATE TRIGGER IF NOT EXISTS short_term_ad AFTER DELETE ON short_term BEGIN
    INSERT INTO short_term_fts(short_term_fts, rowid, title, body, tags) VALUES('delete', old.id, old.title, old.body, old.tags);
END;
CREATE TRIGGER IF NOT EXISTS short_term_au AFTER UPDATE ON short_term BEGIN
    INSERT INTO short_term_fts(short_term_fts, rowid, title, body, tags) VALUES('delete', old.id, old.title, old.body, old.tags);
    INSERT INTO short_term_fts(rowid, title, body, tags)                  VALUES(new.id, new.title, new.body, new.tags);
END;
"""


# ────────────────────────────────────────────────────────────────────────
# Connection + row shaping
# ────────────────────────────────────────────────────────────────────────


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA trusted_schema = 1;")
    conn.execute("PRAGMA journal_mode   = WAL;")
    conn.execute("PRAGMA foreign_keys   = ON;")
    return conn


def init_schema() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA_SQL)


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    raw_refs = d.pop("refs_json", None)
    if raw_refs:
        try:
            d["refs"] = json.loads(raw_refs)
        except (TypeError, ValueError):
            d["refs"] = None
    else:
        d["refs"] = None
    return d


# ────────────────────────────────────────────────────────────────────────
# Validation helpers
# ────────────────────────────────────────────────────────────────────────


def _validate_table(table: str) -> TableName:
    if table not in VALID_TABLES:
        raise ValueError(f"invalid table {table!r}; must be one of {VALID_TABLES}")
    return table  # type: ignore[return-value]


def _validate_kind(table: TableName, kind: str) -> str:
    valid = KNOWLEDGE_KINDS if table == "knowledge" else SHORT_TERM_KINDS
    if kind not in valid:
        raise ValueError(f"invalid kind {kind!r} for {table}; must be one of {valid}")
    return kind


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _refs_to_json(refs: Optional[dict[str, Any]]) -> Optional[str]:
    if refs is None:
        return None
    if not isinstance(refs, dict):
        raise ValueError("refs must be a dict, e.g. {'prs':[3645],'issues':[3644]}")
    return json.dumps(refs, separators=(",", ":"), sort_keys=True)


# ────────────────────────────────────────────────────────────────────────
# Read operations
# ────────────────────────────────────────────────────────────────────────


def get_entry(table: str, entry_id: int) -> Optional[dict[str, Any]]:
    tbl = _validate_table(table)
    with connect() as conn:
        row = conn.execute(f"SELECT * FROM {tbl} WHERE id = ?", (entry_id,)).fetchone()
    return row_to_dict(row) if row else None


def list_entries(
    table: str,
    kind: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 25,
    offset: int = 0,
) -> list[dict[str, Any]]:
    tbl = _validate_table(table)
    where: list[str] = []
    params: list[Any] = []
    if kind:
        where.append("kind = ?")
        params.append(kind)
    if status:
        where.append("status = ?")
        params.append(status)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    sql = f"SELECT * FROM {tbl} {where_sql} ORDER BY updated_at DESC LIMIT ? OFFSET ?"
    params.extend([int(limit), int(offset)])
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [row_to_dict(r) for r in rows]


def search(
    query: str,
    table: Literal["knowledge", "short_term", "both"] = "both",
    kind: Optional[str] = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """FTS search across knowledge and/or short_term. Returns entries with a `source` field."""
    if not query.strip():
        return []
    tables: Iterable[TableName]
    if table == "both":
        tables = ("knowledge", "short_term")
    else:
        tables = (_validate_table(table),)

    results: list[dict[str, Any]] = []
    with connect() as conn:
        for tbl in tables:
            fts = f"{tbl}_fts"
            sql = (
                f"SELECT {tbl}.*, bm25({fts}) AS score, ? AS source "
                f"FROM {fts} JOIN {tbl} ON {tbl}.id = {fts}.rowid "
                f"WHERE {fts} MATCH ? "
            )
            params: list[Any] = [tbl, query]
            if kind:
                sql += "AND kind = ? "
                params.append(kind)
            sql += "ORDER BY score LIMIT ?"
            params.append(int(limit))
            rows = conn.execute(sql, params).fetchall()
            results.extend(row_to_dict(r) for r in rows)

    # Merge sort by score (lower is better in bm25).
    results.sort(key=lambda r: r.get("score", 0.0))
    return results[:limit]


def stats() -> dict[str, Any]:
    out: dict[str, Any] = {"tables": {}}
    with connect() as conn:
        for tbl in VALID_TABLES:
            total = conn.execute(f"SELECT COUNT(*) AS c FROM {tbl}").fetchone()["c"]
            by_kind_rows = conn.execute(
                f"SELECT kind, COUNT(*) AS c FROM {tbl} GROUP BY kind ORDER BY c DESC"
            ).fetchall()
            by_status_rows = conn.execute(
                f"SELECT status, COUNT(*) AS c FROM {tbl} GROUP BY status ORDER BY c DESC"
            ).fetchall()
            latest = conn.execute(
                f"SELECT MAX(updated_at) AS ts FROM {tbl}"
            ).fetchone()["ts"]
            out["tables"][tbl] = {
                "total": total,
                "by_kind": {r["kind"]: r["c"] for r in by_kind_rows},
                "by_status": {r["status"]: r["c"] for r in by_status_rows},
                "latest_updated_at": latest,
            }
    out["db_path"] = str(db_path())
    out["project"] = current_project() if not os.environ.get("ROCWIKI_DB") else "(ROCWIKI_DB override)"
    return out


# ────────────────────────────────────────────────────────────────────────
# Write operations
# ────────────────────────────────────────────────────────────────────────


def add_entry(
    table: str,
    kind: str,
    title: str,
    body: str,
    tags: Optional[str] = None,
    refs: Optional[dict[str, Any]] = None,
    status: str = "active",
) -> dict[str, Any]:
    tbl = _validate_table(table)
    _validate_kind(tbl, kind)
    if not title.strip() or not body.strip():
        raise ValueError("title and body are required")
    now = _now_utc_iso()
    refs_json = _refs_to_json(refs)
    with connect() as conn:
        cur = conn.execute(
            f"INSERT INTO {tbl} (created_at, updated_at, kind, title, body, tags, refs_json, status) "
            f"VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (now, now, kind, title, body, tags, refs_json, status),
        )
        entry_id = cur.lastrowid
        conn.commit()
    return get_entry(tbl, entry_id)  # type: ignore[return-value]


def update_entry(
    table: str,
    entry_id: int,
    *,
    kind: Optional[str] = None,
    title: Optional[str] = None,
    body: Optional[str] = None,
    tags: Optional[str] = None,
    refs: Optional[dict[str, Any]] = None,
    status: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    tbl = _validate_table(table)
    updates: list[str] = []
    params: list[Any] = []
    if kind is not None:
        _validate_kind(tbl, kind)
        updates.append("kind = ?")
        params.append(kind)
    if title is not None:
        updates.append("title = ?")
        params.append(title)
    if body is not None:
        updates.append("body = ?")
        params.append(body)
    if tags is not None:
        updates.append("tags = ?")
        params.append(tags)
    if refs is not None:
        updates.append("refs_json = ?")
        params.append(_refs_to_json(refs))
    if status is not None:
        updates.append("status = ?")
        params.append(status)
    if not updates:
        return get_entry(tbl, entry_id)
    updates.append("updated_at = ?")
    params.append(_now_utc_iso())
    params.append(entry_id)
    with connect() as conn:
        conn.execute(f"UPDATE {tbl} SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()
    return get_entry(tbl, entry_id)


def delete_entry(table: str, entry_id: int) -> bool:
    tbl = _validate_table(table)
    with connect() as conn:
        cur = conn.execute(f"DELETE FROM {tbl} WHERE id = ?", (entry_id,))
        conn.commit()
    return cur.rowcount > 0


def promote_to_knowledge(short_term_id: int, kind: str) -> Optional[dict[str, Any]]:
    """Move a short_term entry into knowledge with a new kind. The short_term row is marked resolved."""
    _validate_kind("knowledge", kind)
    src = get_entry("short_term", short_term_id)
    if src is None:
        return None
    promoted = add_entry(
        "knowledge",
        kind=kind,
        title=src["title"],
        body=src["body"],
        tags=src.get("tags"),
        refs=src.get("refs"),
        status="active",
    )
    update_entry("short_term", short_term_id, status="resolved")
    return promoted