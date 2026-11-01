"""Evidence-preserving SQLite queries; no game paths, network or inferred defaults."""

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

FIELDS = (
    "name",
    "purpose",
    "construction_materials",
    "power_consumption_w",
    "power_generation_w",
    "inputs",
    "outputs",
    "temperature_constraints",
    "environment_constraints",
    "research",
)
APPLICATION_ID = 1330530625
SCHEMA_VERSION = 2


@dataclass(frozen=True)
class Fact:
    field: str
    value: Any
    unit: str | None
    status: str
    source_url: str | None
    source_revision: str | None
    source_sha256: str | None
    locator: str | None
    note: str
    source_accessed_on: str | None = None
    source_target_version: str | None = None
    redistribution: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "value": "UNKNOWN" if self.status == "UNKNOWN" else self.value,
            "unit": self.unit,
            "status": self.status,
            "source_url": self.source_url,
            "source_revision": self.source_revision,
            "source_sha256": self.source_sha256,
            "locator": self.locator,
            "note": self.note,
            "source_accessed_on": self.source_accessed_on,
            "source_target_version": self.source_target_version,
            "redistribution": self.redistribution,
        }


@dataclass(frozen=True)
class BuildingKnowledge:
    variant_id: str
    building_id: str
    game_version: str
    dlc_scope: str
    identity_status: str
    identity_source_url: str
    identity_source_revision: str
    identity_locator: str
    facts: tuple[Fact, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "building_id": self.building_id,
            "game_version": self.game_version,
            "dlc_scope": self.dlc_scope,
            "identity_status": self.identity_status,
            "identity_source_url": self.identity_source_url,
            "identity_source_revision": self.identity_source_revision,
            "identity_locator": self.identity_locator,
            "facts": {fact.field: fact.as_dict() for fact in self.facts},
        }


def create_database(path: Path) -> None:
    """Explicit local initialization. Refuse to overwrite any existing file."""
    seed = json.loads(files("oni_ai").joinpath("data/seed.json").read_text(encoding="utf-8"))
    schema = files("oni_ai").joinpath("data/schema.sql").read_text(encoding="utf-8")
    # Exclusive creation prevents concurrent initialization from clobbering another DB.
    with path.open("xb"):
        pass
    try:
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.executescript(schema)
            with connection:
                for source in seed["sources"]:
                    connection.execute(
                        "INSERT INTO source VALUES (?, ?, ?, ?, ?, ?, ?)",
                        tuple(
                            source[k]
                            for k in (
                                "source_id",
                                "kind",
                                "url",
                                "revision",
                                "accessed_on",
                                "content_sha256",
                                "note",
                            )
                        ),
                    )
                for building in seed["buildings"]:
                    connection.execute(
                        "INSERT INTO building_variant VALUES (?, ?, ?, ?, ?, ?, ?)",
                        tuple(
                            building[k]
                            for k in (
                                "variant_id",
                                "building_id",
                                "game_version",
                                "dlc_scope",
                                "identity_status",
                                "identity_source_id",
                                "identity_locator",
                            )
                        ),
                    )
                    for field in FIELDS:
                        claim = building["facts"].get(field)
                        connection.execute(
                            "INSERT INTO fact VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (
                                building["variant_id"],
                                field,
                                json.dumps(claim["value"], ensure_ascii=False) if claim else None,
                                claim.get("unit") if claim else None,
                                claim["status"] if claim else "UNKNOWN",
                                claim["source_id"] if claim else None,
                                claim["locator"] if claim else None,
                                claim["note"]
                                if claim
                                else "No verified evidence collected in Phase 0.",
                            ),
                        )
            connection.executescript(
                files("oni_ai").joinpath("data/schema_v2.sql").read_text(encoding="utf-8")
            )
    except BaseException:
        path.unlink(missing_ok=True)
        raise


class KnowledgeRepository:
    """Open an existing database with SQLite mode=ro and parameterized queries."""

    def __init__(self, path: Path):
        self._connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA query_only = ON")
        version = self._connection.execute("PRAGMA user_version").fetchone()[0]
        self._schema_version = version
        app_id = self._connection.execute("PRAGMA application_id").fetchone()[0]
        if version not in {1, SCHEMA_VERSION} or app_id != APPLICATION_ID:
            self.close()
            raise ValueError("Unsupported knowledge database identity/schema version")

    def __enter__(self) -> "KnowledgeRepository":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._connection.close()

    def search(
        self,
        query: str,
        *,
        game_version: str | None = None,
        dlc_scope: str | None = None,
        limit: int = 20,
    ) -> tuple[BuildingKnowledge, ...]:
        """Literal substring search on ID/name/purpose. Scope filters are exact."""
        if not query.strip():
            raise ValueError("query must not be blank")
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        escaped = query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        rows = self._connection.execute(
            """
            SELECT b.*, s.url AS identity_source_url, s.revision AS identity_source_revision
            FROM building_variant AS b
            JOIN source AS s ON s.source_id = b.identity_source_id
            WHERE (b.building_id LIKE ? ESCAPE '\\' OR EXISTS (
                SELECT 1 FROM fact AS f WHERE f.variant_id = b.variant_id
                AND f.field IN ('name', 'purpose')
                AND json_extract(f.value_json, '$') LIKE ? ESCAPE '\\'
            )) AND (? IS NULL OR b.game_version = ?)
               AND (? IS NULL OR b.dlc_scope = ?)
            ORDER BY b.building_id, b.variant_id LIMIT ?
            """,
            (pattern, pattern, game_version, game_version, dlc_scope, dlc_scope, limit),
        ).fetchall()
        return tuple(self._building(row) for row in rows)

    def _building(self, row: sqlite3.Row) -> BuildingKnowledge:
        review_fields = (
            "v.target_version, v.redistribution"
            if self._schema_version == 2
            else "NULL AS target_version, NULL AS redistribution"
        )
        review_join = (
            "LEFT JOIN source_review v ON v.source_id=f.source_id"
            if self._schema_version == 2
            else ""
        )
        claims = self._connection.execute(
            f"""
            SELECT f.*, s.url, s.revision, s.content_sha256, s.accessed_on, {review_fields}
            FROM fact AS f
            LEFT JOIN source AS s ON s.source_id = f.source_id
            {review_join}
            WHERE f.variant_id = ? ORDER BY f.field
            """,
            (row["variant_id"],),
        ).fetchall()
        return BuildingKnowledge(
            variant_id=row["variant_id"],
            building_id=row["building_id"],
            game_version=row["game_version"],
            dlc_scope=row["dlc_scope"],
            identity_status=row["identity_status"],
            identity_source_url=row["identity_source_url"],
            identity_source_revision=row["identity_source_revision"],
            identity_locator=row["identity_locator"],
            facts=tuple(
                Fact(
                    field=claim["field"],
                    value=json.loads(claim["value_json"])
                    if claim["value_json"] is not None
                    else None,
                    unit=claim["unit"],
                    status=claim["status"],
                    source_url=claim["url"],
                    source_revision=claim["revision"],
                    source_sha256=claim["content_sha256"],
                    locator=claim["locator"],
                    note=claim["note"],
                    source_accessed_on=claim["accessed_on"],
                    source_target_version=claim["target_version"],
                    redistribution=claim["redistribution"],
                )
                for claim in claims
            ),
        )
