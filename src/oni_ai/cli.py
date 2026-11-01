"""Offline CLI. Every subcommand stays within local files or in-memory mocks."""

import argparse
import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from oni_ai.adapters import demo_adapter
from oni_ai.catalog import audit_database, import_catalog, migrate_database, read_rules
from oni_ai.contracts import Decision, strict_json
from oni_ai.evaluation import replay_log, run_experiment
from oni_ai.knowledge import KnowledgeRepository, create_database
from oni_ai.protocol import operation_catalog
from oni_ai.simulation import fixture_names, load_fixture


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="ONI AI: offline knowledge and synthetic experiments"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init-db", help="Create a new local evidence DB; never overwrite")
    init.add_argument("path", type=Path)
    search = commands.add_parser("search", help="Read an existing local DB")
    search.add_argument("path", type=Path)
    search.add_argument("query")
    search.add_argument("--game-version")
    search.add_argument("--dlc-scope")
    commands.add_parser("mock-demo", help="Read synthetic in-memory data; no connection")
    migrate = commands.add_parser("migrate-db", help="Copy a Schema 1/2 DB into a new Schema 2 DB")
    migrate.add_argument("source", type=Path)
    migrate.add_argument("destination", type=Path)
    for name, help_text in (
        ("import-catalog", "Import reviewed historical knowledge into a Schema 2 DB"),
        ("audit-db", "Check local DB integrity, facts, evidence and UNKNOWN"),
    ):
        commands.add_parser(name, help=help_text).add_argument("path", type=Path)
    rules = commands.add_parser("rules", help="Read version-scoped game rules")
    rules.add_argument("path", type=Path)
    rules.add_argument("--domain")
    rules.add_argument("--game-version")
    rules.add_argument("--dlc-scope")
    commands.add_parser("fixtures", help="List synthetic fixtures; no action selection")
    commands.add_parser("operations", help="Read static OniMcp operation evidence")
    simulate = commands.add_parser("simulate", help="Apply caller decisions to a synthetic model")
    simulate.add_argument("fixture", choices=fixture_names())
    simulate.add_argument("--decisions", type=Path, required=True)
    simulate.add_argument("--log", type=Path, required=True)
    replay = commands.add_parser("replay", help="Verify a synthetic experiment receipt")
    replay.add_argument("log", type=Path)
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
        elif args.command == "mock-demo":
            observation = demo_adapter().read_resource("oni://colony/status")
            print(json.dumps(asdict(observation), ensure_ascii=False, indent=2))
        else:
            if args.command == "migrate-db":
                migrate_database(args.source, args.destination)
                result = {"created": str(args.destination), "original_unchanged": True}
            elif args.command == "import-catalog":
                result = import_catalog(args.path)
            elif args.command == "audit-db":
                result = audit_database(args.path)
            elif args.command == "rules":
                result = read_rules(
                    args.path,
                    domain=args.domain,
                    game_version=args.game_version,
                    dlc_scope=args.dlc_scope,
                )
            elif args.command == "fixtures":
                result = fixture_names()
            elif args.command == "operations":
                result = operation_catalog()
            elif args.command == "simulate":
                raw = strict_json(args.decisions.read_text("utf-8"))
                if not isinstance(raw, list) or not 1 <= len(raw) <= 100:
                    raise ValueError("Expected 1..100 explicit decisions")
                result = run_experiment(
                    load_fixture(args.fixture), [Decision.from_dict(item) for item in raw], args.log
                )
            else:
                result = replay_log(args.log)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            if args.command == "audit-db" and not result["valid"]:
                return 1
    except (OSError, sqlite3.Error, ValueError) as error:
        parser.exit(2, f"error: {error}\n")
    return 0
