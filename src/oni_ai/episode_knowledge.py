"""Portable, read-only evidence snapshots and bounded episode knowledge retrieval."""

from dataclasses import asdict, dataclass
from pathlib import Path

from oni_ai.contracts import MODEL_VERSION, nonempty, strict_json
from oni_ai.evaluation import _canonical
from oni_ai.knowledge import KnowledgeRepository


@dataclass(frozen=True)
class KnowledgeQuery:
    kind: str
    query: str
    game_version: str = "UNKNOWN"
    dlc_scope: str = "UNKNOWN"
    limit: int = 32

    def __post_init__(self):
        if self.kind not in {"model", "building", "rule"}:
            raise ValueError("Unsupported query kind")
        for value in (self.query, self.game_version, self.dlc_scope):
            nonempty(value)
        if type(self.limit) is not int or not 1 <= self.limit <= 32:
            raise ValueError("Query limit must be 1..32")


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    kind: str
    search_text: str
    value_json: str
    status: str
    game_version: str = "UNKNOWN"
    dlc_scope: str = "UNKNOWN"
    model_version: str | None = None

    def __post_init__(self):
        for value in (self.evidence_id, self.search_text):
            nonempty(value)
        strict_json(self.value_json)
        if self.kind not in {"MODEL", "DATABASE_FACT", "DATABASE_RULE"}:
            raise ValueError("Invalid evidence kind")
        if self.kind == "MODEL":
            if (
                not self.evidence_id.startswith("model:")
                or self.status != "MODEL_SPEC"
                or self.model_version != MODEL_VERSION
            ):
                raise ValueError("Invalid synthetic model evidence")
        elif (
            not self.evidence_id.startswith("db:")
            or self.model_version is not None
            or self.status not in {"UNKNOWN", "CONFLICTED", "SOURCE_REVIEWED", "GAME_VERIFIED"}
        ):
            raise ValueError("Invalid database evidence")

    @property
    def applicable(self) -> bool:
        # Actual ONI facts never authorize a transition in this unrelated synthetic model.
        return self.kind == "MODEL" and self.model_version == MODEL_VERSION


def database_snapshot(path: Path | None) -> tuple[Evidence, ...]:
    if path is None:
        return ()
    items = []
    with KnowledgeRepository(path) as repository:
        connection = repository._connection
        connection.execute("BEGIN")
        rows = connection.execute("""
            SELECT b.*, s.url AS identity_source_url, s.revision AS identity_source_revision
            FROM building_variant b JOIN source s ON s.source_id=b.identity_source_id
            ORDER BY b.variant_id
        """).fetchall()
        for row in rows:
            building = repository._building(row)
            for fact in building.facts:
                items.append(
                    Evidence(
                        f"db:fact:{building.variant_id}:{fact.field}",
                        "DATABASE_FACT",
                        f"{building.building_id} {fact.field}",
                        _canonical(fact.as_dict()),
                        fact.status,
                        building.game_version,
                        building.dlc_scope,
                    )
                )
        if connection.execute("PRAGMA user_version").fetchone()[0] == 2:
            for row in connection.execute("""
                SELECT r.*, s.url, s.revision, s.accessed_on, s.content_sha256,
                       v.redistribution, v.target_version
                FROM game_rule r JOIN source s USING(source_id)
                JOIN source_review v USING(source_id) ORDER BY rule_id
            """):
                record = dict(row)
                items.append(
                    Evidence(
                        f"db:rule:{row['rule_id']}",
                        "DATABASE_RULE",
                        f"{row['domain']} {row['statement']}",
                        _canonical(record),
                        row["status"],
                        row["game_version"],
                        row["dlc_scope"],
                    )
                )
    if len(items) > 512:
        raise ValueError("Database snapshot exceeds the offline episode limit (512 items)")
    return tuple(items)


def restore_snapshot(records: list[dict]) -> tuple[Evidence, ...]:
    if not isinstance(records, list) or len(records) > 512:
        raise ValueError("Invalid snapshot size")
    try:
        items = tuple(Evidence(**record) for record in records)
    except (TypeError, KeyError) as error:
        raise ValueError("Invalid evidence snapshot") from error
    if any(item.kind == "MODEL" for item in items):
        raise ValueError("Database snapshot cannot inject model evidence")
    if len({item.evidence_id for item in items}) != len(items):
        raise ValueError("Duplicate snapshot evidence IDs")
    return items


class EpisodeKnowledge:
    def __init__(self, fixture: dict, objective: dict, snapshot: tuple[Evidence, ...] = ()):
        specifications = {
            "model:actions": {
                "wait": "Advance 1..10 ticks without configuring a process",
                "set_process": "Set enabled boolean on a process and advance one tick",
                "clear_blockage": "Clear a process blockage and advance one tick",
            },
            "model:transition": {
                "semantics": "Processes use simultaneous inputs before outputs; contested inputs "
                "block competing processes. Demand is applied after production.",
                "demand": fixture["demand"],
                "thresholds": fixture["thresholds"],
                "unknown": "null is unknown, never zero; do not infer missing resources",
            },
            "model:objective": objective,
            **{
                f"model:process:{key}": {
                    field: process[field] for field in ("inputs", "outputs", "requires_research")
                }
                for key, process in fixture["processes"].items()
            },
        }
        self._items = (
            tuple(
                Evidence(
                    key, "MODEL", key, _canonical(value), "MODEL_SPEC", model_version=MODEL_VERSION
                )
                for key, value in sorted(specifications.items())
            )
            + snapshot
        )

    def search(self, queries: tuple[KnowledgeQuery, ...]) -> tuple[Evidence, ...]:
        if (
            not isinstance(queries, tuple)
            or not 1 <= len(queries) <= 8
            or not all(isinstance(q, KnowledgeQuery) for q in queries)
        ):
            raise ValueError("Provide 1..8 typed knowledge queries")
        found = {}
        kinds = {"model": "MODEL", "building": "DATABASE_FACT", "rule": "DATABASE_RULE"}
        for query in queries:
            matches = [
                item
                for item in self._items
                if item.kind == kinds[query.kind]
                and (query.query == "*" or query.query.casefold() in item.search_text.casefold())
                and (
                    item.kind == "MODEL"
                    or (
                        item.game_version == query.game_version
                        and item.dlc_scope == query.dlc_scope
                    )
                )
            ]
            for item in matches[: query.limit]:
                found[item.evidence_id] = item
        if len(found) > 64:
            raise ValueError("Retrieved evidence exceeds 64 items")
        return tuple(found[key] for key in sorted(found))


def query_records(queries: tuple[KnowledgeQuery, ...]) -> list[dict]:
    return [asdict(query) for query in queries]


def parse_queries(records: list[dict]) -> tuple[KnowledgeQuery, ...]:
    if not isinstance(records, list) or not 1 <= len(records) <= 8:
        raise ValueError("Invalid query records")
    try:
        return tuple(KnowledgeQuery(**record) for record in records)
    except (TypeError, KeyError) as error:
        raise ValueError("Invalid query record") from error


def required_unknowns(observation: dict, evidence: tuple[Evidence, ...]) -> tuple[str, ...]:
    missing = {
        f"obs:/resources/{key}" for key, value in observation["resources"].items() if value is None
    }
    missing.update(
        item.evidence_id
        for item in evidence
        if not item.applicable or item.status in {"UNKNOWN", "CONFLICTED"}
    )
    return tuple(sorted(missing))
