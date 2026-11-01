"""Validate original factual summaries, then explicitly import them into a local DB."""

import hashlib
import json
import math
import re
import sqlite3
from contextlib import closing
from datetime import date
from importlib.resources import files
from pathlib import Path

from oni_ai.contracts import strict_json
from oni_ai.knowledge import APPLICATION_ID, FIELDS, KnowledgeRepository

STATUSES = {"UNKNOWN", "SOURCE_REVIEWED", "GAME_VERIFIED", "CONFLICTED"}
DLC_SCOPES = {"UNKNOWN", "BASE_GAME", "SPACED_OUT", "ALL_DECLARED"}
DOMAINS = {"oxygen", "food", "power", "water", "research"}


def packaged_catalog() -> dict:
    return json.loads(files("oni_ai").joinpath("data/phase1_catalog.json").read_text("utf-8"))


def _text(value: object, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}: nonempty string required")


def _identifier(value: object) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", value):
        raise ValueError("Invalid resource/research/building identifier")


def _number(value: object, *, unknown: bool = False) -> None:
    if unknown and value is None:
        return
    if type(value) not in {int, float} or not math.isfinite(value) or value < 0:
        raise ValueError("Expected a finite nonnegative number; bool is not a number")


def _evidence(claim: dict, sources: dict) -> None:
    _text(claim.get("source_id"), "source_id")
    if claim.get("source_id") not in sources:
        raise ValueError("Unknown source_id")
    _text(claim.get("locator"), "locator")


def validate_fact(field: str, claim: dict, sources: dict, resource_ids: set[str]) -> None:
    try:
        _validate_fact(field, claim, sources, resource_ids)
    except (KeyError, TypeError, AttributeError, OverflowError) as error:
        raise ValueError("Malformed fact or array item") from error


def _validate_fact(field: str, claim: dict, sources: dict, resource_ids: set[str]) -> None:
    if field not in FIELDS or not isinstance(claim, dict) or claim.get("status") not in STATUSES:
        raise ValueError("Invalid fact field/status")
    value = claim.get("value")
    _text(claim.get("note"), "fact note")
    if claim["status"] == "UNKNOWN":
        if value is not None or claim.get("unit") is not None:
            raise ValueError("UNKNOWN must have null value/unit, never 0")
        return
    _evidence(claim, sources)
    if field in {"name", "purpose"}:
        _text(value, field)
        if claim.get("unit") is not None:
            raise ValueError("Text facts have no unit")
        return
    if field in {"power_consumption_w", "power_generation_w"}:
        _number(value)
        if claim.get("unit") != "W":
            raise ValueError("Power unit must be W")
        return
    if not isinstance(value, list) or claim.get("unit") is not None:
        raise ValueError("Structured facts require an array and no top-level unit")
    seen = set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("Array items must be objects")
        _evidence(item, sources)
        if field in {"inputs", "outputs"}:
            _identifier(item.get("material_id"))
            if item["material_id"] not in resource_ids or item["material_id"] in seen:
                raise ValueError("Unregistered or duplicate material_id")
            seen.add(item["material_id"])
            _number(item.get("amount"), unknown=True)
            if item.get("amount") is None:
                if item.get("unit") is not None:
                    raise ValueError("Unknown amount has no numeric unit")
            elif item.get("unit") not in {"kg/s", "kg/cycle", "kg/batch", "kcal/batch"}:
                raise ValueError("Unsupported flow unit")
            _text(item.get("condition"), "flow condition")
        elif field == "construction_materials":
            if type(item.get("slot")) is not int or item["slot"] < 0 or item["slot"] in seen:
                raise ValueError("Invalid/duplicate material slot")
            seen.add(item["slot"])
            _identifier(item.get("material_category"))
            _number(item.get("mass_kg"), unknown=True)
            candidates = item.get("candidates")
            if not isinstance(candidates, list) or len(candidates) != len(set(candidates)):
                raise ValueError("Material candidates must be a unique list")
            for candidate in candidates:
                _identifier(candidate)
                if candidate not in resource_ids:
                    raise ValueError("Unregistered construction material")
        elif field == "research":
            _identifier(item.get("research_id"))
            if item["research_id"] in seen:
                raise ValueError("Duplicate research prerequisite")
            seen.add(item["research_id"])
            if item.get("relation") not in {"ALL", "ANY"}:
                raise ValueError("Research relation must be ALL or ANY")
        elif field == "temperature_constraints":
            if item.get("kind") not in {
                "minimum_output",
                "operating_min",
                "operating_max",
                "overheat",
            }:
                raise ValueError("Unknown temperature constraint kind")
            # Celsius may be negative. Kelvin must not be negative.
            numeric = item.get("value")
            if type(numeric) not in {int, float} or not math.isfinite(numeric):
                raise ValueError("Temperature must be finite")
            if item.get("unit") not in {"K", "degC"} or (item["unit"] == "K" and numeric < 0):
                raise ValueError("Invalid temperature unit/value")
            _text(item.get("condition"), "temperature condition")
        else:
            _text(item.get("kind"), "environment kind")
            _text(item.get("condition"), "environment condition")
    if field == "temperature_constraints":
        bounds = {}
        for item in value:
            if item["kind"] in {"operating_min", "operating_max"}:
                key = (item["condition"], item["kind"])
                if key in bounds:
                    raise ValueError("Duplicate temperature bound")
                bounds[key] = item["value"] + (273.15 if item["unit"] == "degC" else 0)
        for (condition, kind), minimum in bounds.items():
            if kind == "operating_min" and minimum > bounds.get(
                (condition, "operating_max"), math.inf
            ):
                raise ValueError("Inverted operating temperature range")


def validate_catalog(catalog: dict) -> None:
    try:
        _validate_catalog(catalog)
    except (KeyError, TypeError, AttributeError, OverflowError) as error:
        raise ValueError("Malformed catalog metadata or numeric value") from error


def _validate_catalog(catalog: dict) -> None:
    if (
        not isinstance(catalog, dict)
        or type(catalog.get("schema_version")) is not int
        or catalog["schema_version"] != 1
    ):
        raise ValueError("Unsupported catalog format")
    for field in ("sources", "buildings", "rules", "resource_ids"):
        if not isinstance(catalog.get(field), list):
            raise ValueError("Catalog collections must be lists")
    _text(catalog.get("catalog_id"), "catalog_id")
    sources = {}
    for source in catalog["sources"]:
        required = {
            "source_id",
            "kind",
            "url",
            "revision",
            "accessed_on",
            "content_sha256",
            "target_version",
            "locator",
            "redistribution",
            "rights_note",
            "hash_scope",
            "note",
        }
        if not isinstance(source, dict) or not required <= source.keys():
            raise ValueError("Missing source metadata")
        key = source["source_id"]
        _text(key, "source_id")
        if key in sources:
            raise ValueError("Duplicate source_id")
        sources[key] = source
        if source.get("kind") not in {"OFFICIAL", "UPSTREAM_CODE", "UPSTREAM_DOC", "RUNTIME"}:
            raise ValueError("Invalid source kind")
        if not source["url"].startswith("https://"):
            raise ValueError("Source URL must use https")
        date.fromisoformat(source["accessed_on"])
        if not re.fullmatch(r"[0-9a-f]{64}", source["content_sha256"]):
            raise ValueError("Invalid source digest")
        for field in ("revision", "target_version", "locator", "rights_note", "hash_scope", "note"):
            _text(source.get(field), field)
        if source.get("redistribution") not in {"UNKNOWN", "REFERENCE_ONLY", "LICENSED"}:
            raise ValueError("Invalid redistribution status")
        if source["redistribution"] == "REFERENCE_ONLY" and source.get("verbatim_body"):
            raise ValueError("Reference-only sources must not redistribute a body")
    for item in catalog["resource_ids"]:
        _identifier(item)
    resources = set(catalog["resource_ids"])
    if len(resources) != len(catalog["resource_ids"]):
        raise ValueError("Duplicate resource identifier")
    for item in resources:
        _identifier(item)
    seen = set()
    for building in catalog["buildings"]:
        required = {
            "variant_id",
            "building_id",
            "game_version",
            "dlc_scope",
            "identity_status",
            "identity_source_id",
            "identity_locator",
            "facts",
        }
        if (
            not isinstance(building, dict)
            or not required <= building.keys()
            or not isinstance(building["facts"], dict)
        ):
            raise ValueError("Invalid building structure")
        if building["variant_id"] in seen:
            raise ValueError("Duplicate variant_id")
        seen.add(building["variant_id"])
        _identifier(building["building_id"])
        _scope(building)
        if building["variant_id"] != (
            f"{building['building_id']}@{building['game_version']}@{building['dlc_scope']}"
        ):
            raise ValueError("Variant ID/scope mismatch")
        _evidence(
            {"source_id": building["identity_source_id"], "locator": building["identity_locator"]},
            sources,
        )
        if building["identity_status"] not in {"SOURCE_REVIEWED", "GAME_VERIFIED"}:
            raise ValueError("Invalid identity status")
        identity_source = sources[building["identity_source_id"]]
        if building["identity_status"] == "GAME_VERIFIED" and (
            identity_source["kind"] != "RUNTIME"
            or identity_source["target_version"] != building["game_version"]
        ):
            raise ValueError("GAME_VERIFIED identity requires version-matched runtime evidence")
        for field, claim in building["facts"].items():
            validate_fact(field, claim, sources, resources)
            if claim["status"] != "UNKNOWN":
                version = sources[claim["source_id"]]["target_version"]
                if version not in {"UNKNOWN", building["game_version"]}:
                    raise ValueError("Fact source version mismatch")
                if version == "UNKNOWN" and field != "name":
                    raise ValueError("A specification requires versioned evidence")
                if (
                    claim["status"] == "GAME_VERIFIED"
                    and sources[claim["source_id"]]["kind"] != "RUNTIME"
                ):
                    raise ValueError("GAME_VERIFIED requires runtime evidence")
    seen = set()
    for rule in catalog["rules"]:
        required = {
            "rule_id",
            "domain",
            "game_version",
            "dlc_scope",
            "statement",
            "parameters",
            "status",
            "source_id",
            "locator",
        }
        if (
            not isinstance(rule, dict)
            or not required <= rule.keys()
            or not isinstance(rule["parameters"], dict)
        ):
            raise ValueError("Invalid rule structure")
        if rule["rule_id"] in seen:
            raise ValueError("Duplicate rule_id")
        seen.add(rule["rule_id"])
        _scope(rule)
        _evidence(rule, sources)
        if rule["domain"] not in DOMAINS or rule["status"] != "SOURCE_REVIEWED":
            raise ValueError("Catalog rules require a domain and SOURCE_REVIEWED status")
        if sources[rule["source_id"]]["target_version"] != rule["game_version"]:
            raise ValueError("Rule source version mismatch")
        _text(rule["statement"], "rule statement")
        if rule.get("variant_id") is not None:
            linked = next(
                (b for b in catalog["buildings"] if b["variant_id"] == rule["variant_id"]), None
            )
            if (
                linked is None
                or linked["game_version"] != rule["game_version"]
                or linked["dlc_scope"] != rule["dlc_scope"]
            ):
                raise ValueError("Rule/building scope mismatch")
    # Reject NaN/Infinity anywhere, including nested optional metadata.
    json.dumps(catalog, allow_nan=False)


def _scope(record: dict) -> None:
    if not re.fullmatch(r"[0-9]{6}", record["game_version"]):
        raise ValueError("New knowledge requires an explicit six-digit source build")
    if record["dlc_scope"] not in DLC_SCOPES:
        raise ValueError("Unreviewed DLC scope")


def _write_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=rw", uri=True)
    if (
        connection.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID
        or connection.execute("PRAGMA user_version").fetchone()[0] != 2
    ):
        connection.close()
        raise ValueError("A Schema 2 knowledge DB is required; use migrate-db first")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def import_catalog(path: Path, catalog: dict | None = None) -> dict:
    catalog = packaged_catalog() if catalog is None else catalog
    validate_catalog(catalog)
    digest = hashlib.sha256(json.dumps(catalog, sort_keys=True).encode()).hexdigest()
    with closing(_write_connection(path)) as connection, connection:
        existing = connection.execute(
            "SELECT content_sha256 FROM catalog_import WHERE catalog_id=?", (catalog["catalog_id"],)
        ).fetchone()
        if existing:
            if existing[0] != digest:
                raise ValueError("Catalog ID already imported with a different digest")
            return {"imported": False, "buildings": 0, "rules": 0}
        for source in catalog["sources"]:
            values = tuple(
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
            )
            previous = connection.execute(
                "SELECT * FROM source WHERE source_id=?", (source["source_id"],)
            ).fetchone()
            if previous and previous != values:
                raise ValueError("Source ID collision")
            if not previous:
                connection.execute("INSERT INTO source VALUES (?,?,?,?,?,?,?)", values)
                connection.execute(
                    "INSERT INTO source_review VALUES (?,?,?,?,?,?)",
                    tuple(
                        source[k]
                        for k in (
                            "source_id",
                            "target_version",
                            "locator",
                            "redistribution",
                            "rights_note",
                            "hash_scope",
                        )
                    ),
                )
        for resource in catalog["resource_ids"]:
            connection.execute("INSERT OR IGNORE INTO resource_identifier VALUES (?)", (resource,))
        for building in catalog["buildings"]:
            connection.execute(
                "INSERT INTO building_variant VALUES (?,?,?,?,?,?,?)",
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
                claim = building["facts"].get(field, {})
                known = claim.get("status", "UNKNOWN") != "UNKNOWN"
                connection.execute(
                    "INSERT INTO fact VALUES (?,?,?,?,?,?,?,?)",
                    (
                        building["variant_id"],
                        field,
                        json.dumps(claim["value"], ensure_ascii=False, allow_nan=False)
                        if known
                        else None,
                        claim.get("unit"),
                        claim.get("status", "UNKNOWN"),
                        claim.get("source_id"),
                        claim.get("locator"),
                        claim.get("note", "No evidence collected; UNKNOWN."),
                    ),
                )
        for rule in catalog["rules"]:
            connection.execute(
                "INSERT INTO game_rule VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    rule["rule_id"],
                    rule["domain"],
                    rule["game_version"],
                    rule["dlc_scope"],
                    rule["statement"],
                    json.dumps(rule["parameters"], ensure_ascii=False),
                    rule["status"],
                    rule["source_id"],
                    rule["locator"],
                ),
            )
            if rule.get("variant_id"):
                connection.execute(
                    "INSERT INTO rule_binding VALUES (?,?)", (rule["variant_id"], rule["rule_id"])
                )
        connection.execute(
            "INSERT INTO catalog_import VALUES (?,?)", (catalog["catalog_id"], digest)
        )
    return {
        "imported": True,
        "buildings": len(catalog["buildings"]),
        "rules": len(catalog["rules"]),
    }


def migrate_database(source: Path, destination: Path) -> None:
    """Copy migration only: never modify the original DB, never overwrite destination."""
    with KnowledgeRepository(source):
        pass
    with destination.open("xb"):
        pass
    try:
        with (
            closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as old,
            closing(sqlite3.connect(destination)) as new,
        ):
            old.backup(new)
            new.execute("PRAGMA foreign_keys=ON")
            if new.execute("PRAGMA user_version").fetchone()[0] == 1:
                sql = files("oni_ai").joinpath("data/schema_v2.sql").read_text("utf-8")
                new.executescript("BEGIN IMMEDIATE;\n" + sql + "\nCOMMIT;")
            if new.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Migrated DB failed integrity check")
            if new.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("Migrated DB has foreign key violations")
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def read_rules(
    path: Path,
    *,
    domain: str | None = None,
    game_version: str | None = None,
    dlc_scope: str | None = None,
) -> list[dict]:
    with KnowledgeRepository(path) as repository:
        connection = repository._connection
        if connection.execute("PRAGMA user_version").fetchone()[0] == 1:
            return []
        rows = connection.execute(
            """
            SELECT r.*, s.url, s.revision, s.accessed_on, v.redistribution
            FROM game_rule r JOIN source s USING(source_id) JOIN source_review v USING(source_id)
            WHERE (? IS NULL OR r.domain=?) AND (? IS NULL OR r.game_version=?)
              AND (? IS NULL OR r.dlc_scope=?) ORDER BY r.rule_id
        """,
            (domain, domain, game_version, game_version, dlc_scope, dlc_scope),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["parameters"] = strict_json(row["parameters_json"])
            item["variant_ids"] = [
                link[0]
                for link in connection.execute(
                    "SELECT variant_id FROM rule_binding WHERE rule_id=? ORDER BY variant_id",
                    (row["rule_id"],),
                )
            ]
            result.append(item)
        return result


def audit_database(path: Path) -> dict:
    errors, warnings = [], []
    with KnowledgeRepository(path) as repository:
        connection = repository._connection
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            errors.append("integrity_check failed")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            errors.append("foreign_key_check failed")
        sources = {r["source_id"]: dict(r) for r in connection.execute("SELECT * FROM source")}
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        resource_ids = (
            {r[0] for r in connection.execute("SELECT material_id FROM resource_identifier")}
            if version == 2
            else set()
        )
        reviews = (
            {r["source_id"]: dict(r) for r in connection.execute("SELECT * FROM source_review")}
            if version == 2
            else {}
        )
        for key, source in sources.items():
            try:
                if not source["url"].startswith("https://"):
                    raise ValueError("Non-HTTPS source")
                date.fromisoformat(source["accessed_on"])
                if not re.fullmatch(r"[0-9a-f]{64}", source["content_sha256"]):
                    raise ValueError("Invalid source hash")
                if version == 2:
                    review = reviews.get(key)
                    if not review:
                        raise ValueError("Missing source review")
                    for field in ("target_version", "locator", "rights_note", "hash_scope"):
                        _text(review[field], field)
            except ValueError as error:
                errors.append(f"source {key}: {error}")
        for row in connection.execute("SELECT * FROM fact"):
            claim = {
                "value": json.loads(row["value_json"]) if row["value_json"] else None,
                "unit": row["unit"],
                "status": row["status"],
                "source_id": row["source_id"],
                "locator": row["locator"],
                "note": row["note"],
            }
            try:
                validate_fact(row["field"], claim, sources, resource_ids)
                if version == 2 and row["status"] != "UNKNOWN":
                    review = reviews.get(row["source_id"])
                    if review is None:
                        raise ValueError("Missing source review")
                    target = connection.execute(
                        "SELECT game_version FROM building_variant WHERE variant_id=?",
                        (row["variant_id"],),
                    ).fetchone()[0]
                    if review["target_version"] not in {"UNKNOWN", target}:
                        raise ValueError("Fact/source version mismatch")
                    if review["target_version"] == "UNKNOWN" and row["field"] != "name":
                        raise ValueError("Unversioned specification evidence")
            except ValueError as error:
                errors.append(f"{row['variant_id']}/{row['field']}: {error}")
        unknown = connection.execute("SELECT COUNT(*) FROM fact WHERE status='UNKNOWN'").fetchone()[
            0
        ]
        if unknown:
            warnings.append(f"{unknown} fact values remain UNKNOWN")
        if version == 1:
            warnings.append(
                "Schema 1: source reviews/rules not available; source DB left untouched"
            )
        else:
            for rule in connection.execute("SELECT * FROM game_rule"):
                try:
                    _scope(dict(rule))
                    _text(rule["statement"], "rule statement")
                    _text(rule["locator"], "rule locator")
                    parameters = strict_json(rule["parameters_json"])
                    if not isinstance(parameters, dict):
                        raise ValueError("Rule parameters must be an object")
                except ValueError as error:
                    errors.append(f"rule {rule['rule_id']}: {error}")
            for row in connection.execute("""
                SELECT r.rule_id FROM game_rule r JOIN source_review s USING(source_id)
                WHERE r.game_version <> s.target_version
            """):
                errors.append(f"Rule source version mismatch: {row[0]}")
            for row in connection.execute("""
                SELECT l.rule_id FROM rule_binding l JOIN game_rule r USING(rule_id)
                JOIN building_variant b USING(variant_id)
                WHERE r.game_version<>b.game_version OR r.dlc_scope<>b.dlc_scope
            """):
                errors.append(f"Rule/building scope mismatch: {row[0]}")
    return {"valid": not errors, "errors": errors, "warnings": warnings}
