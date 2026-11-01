"""Offline CLI. Every subcommand stays within local files or in-memory mocks."""

import argparse
import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from oni_ai.adapters import demo_adapter
from oni_ai.knowledge import KnowledgeRepository, create_database


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ONI AI Phase 0: offline knowledge and mock demo")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init-db", help="Create a new local evidence DB; never overwrite")
    init.add_argument("path", type=Path)
    search = commands.add_parser("search", help="Read an existing local DB")
    search.add_argument("path", type=Path)
    search.add_argument("query")
    search.add_argument("--game-version")
    search.add_argument("--dlc-scope")
    commands.add_parser("mock-demo", help="Read synthetic in-memory data; no connection")
    args = parser.parse_args(argv)
    try:
        if args.command == "init-db":
            create_database(args.path)
            print(f"Created local knowledge DB: {args.path}")
        elif args.command == "search":
            with KnowledgeRepository(args.path) as repository:
                result = repository.search(
                    args.query,
                    game_version=args.game_version,
                    dlc_scope=args.dlc_scope,
                )
                print(json.dumps([b.as_dict() for b in result], ensure_ascii=False, indent=2))
        else:
            observation = demo_adapter().read_resource("oni://colony/status")
            print(json.dumps(asdict(observation), ensure_ascii=False, indent=2))
    except (OSError, sqlite3.Error, ValueError) as error:
        parser.exit(2, f"error: {error}\n")
    return 0
