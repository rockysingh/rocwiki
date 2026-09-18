"""CLI entry point for RocWiki.

Usage:
    rocwiki [--project SLUG] mcp                       stdio MCP server
    rocwiki [--project SLUG] http [--port 8787]        HTTP + HTML dashboard
    rocwiki [--project SLUG] init                      create/upgrade schema in place
    rocwiki [--project SLUG] stats                     print counts to stdout
    rocwiki projects                                   list known project DBs

Project resolution order: --project > ROCWIKI_PROJECT env > git repo basename > cwd basename.
DB path: ~/.rocwiki/projects/<slug>/context.db (override full path via ROCWIKI_DB).
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import db


def _cmd_init(_: argparse.Namespace) -> int:
    db.init_schema()
    print(f"Schema initialised at {db.db_path()}", file=sys.stderr)
    return 0


def _cmd_stats(_: argparse.Namespace) -> int:
    db.init_schema()
    print(json.dumps(db.stats(), indent=2))
    return 0


def _cmd_projects(_: argparse.Namespace) -> int:
    print(json.dumps(db.list_projects(), indent=2))
    return 0


def _cmd_mcp(_: argparse.Namespace) -> int:
    from . import mcp_server
    mcp_server.run()
    return 0


def _cmd_http(args: argparse.Namespace) -> int:
    from . import http_server
    http_server.run(host=args.host, port=args.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rocwiki", description=__doc__)
    parser.add_argument(
        "--project",
        help="project slug (overrides ROCWIKI_PROJECT env var and auto-detect)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create/upgrade schema").set_defaults(func=_cmd_init)
    sub.add_parser("stats", help="print table/kind counts").set_defaults(func=_cmd_stats)
    sub.add_parser("projects", help="list known project DBs").set_defaults(func=_cmd_projects)
    sub.add_parser("mcp", help="run stdio MCP server").set_defaults(func=_cmd_mcp)

    http_p = sub.add_parser("http", help="run HTTP dashboard + REST API")
    http_p.add_argument("--host", default="127.0.0.1")
    http_p.add_argument("--port", type=int, default=8787)
    http_p.set_defaults(func=_cmd_http)

    args = parser.parse_args(argv)
    if args.project:
        os.environ["ROCWIKI_PROJECT"] = args.project
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())