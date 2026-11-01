import json
import sqlite3
from contextlib import closing
from copy import deepcopy
from importlib.resources import files

import pytest

from oni_ai.catalog import (
    audit_database,
    import_catalog,
    migrate_database,
    packaged_catalog,
    read_rules,
    validate_catalog,
    validate_fact,
)
from oni_ai.knowledge import KnowledgeRepository


@pytest.fixture
def legacy_db(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript(files("oni_ai").joinpath("data/schema.sql").read_text("utf-8"))
        db.execute(
            "INSERT INTO source VALUES (?,?,?,?,?,?,?)",
            (
                "legacy",
                "UPSTREAM_DOC",
                "https://example.org/test",
                "synthetic-test",
                "2026-11-01",
                "0" * 64,
                "Synthetic migration test only",
            ),
        )
        db.execute(
            "INSERT INTO building_variant VALUES (?,?,?,?,?,?,?)",
            (
                "Legacy@UNKNOWN@UNKNOWN",
                "Legacy",
                "UNKNOWN",
                "UNKNOWN",
                "SOURCE_REVIEWED",
                "legacy",
                "Test fixture",
            ),
        )
        db.execute(
            "INSERT INTO fact VALUES (?,?,?,?,?,?,?,?)",
            (
                "Legacy@UNKNOWN@UNKNOWN",
                "name",
                '"Preserve custom label"',
                None,
                "SOURCE_REVIEWED",
                "legacy",
                "Test fixture",
                "Synthetic test only",
            ),
        )
        db.execute(
            "INSERT INTO fact VALUES (?,?,?,?,?,?,?,?)",
            (
                "Legacy@UNKNOWN@UNKNOWN",
                "inputs",
                None,
                None,
                "UNKNOWN",
                None,
                None,
                "Preserve custom unknown note",
            ),
        )
    return path


def test_additive_copy_migration_preserves_all_original_rows(legacy_db, tmp_path):
    before = legacy_db.read_bytes()
    destination = tmp_path / "migrated.sqlite3"
    migrate_database(legacy_db, destination)
    assert legacy_db.read_bytes() == before
    with closing(sqlite3.connect(legacy_db)) as old, closing(sqlite3.connect(destination)) as new:
        assert old.execute("PRAGMA user_version").fetchone()[0] == 1
        assert new.execute("PRAGMA user_version").fetchone()[0] == 2
        for table in ("source", "building_variant", "fact"):
            assert (
                old.execute(f"SELECT * FROM {table}").fetchall()
                == new.execute(f"SELECT * FROM {table}").fetchall()
            )
    with KnowledgeRepository(legacy_db) as reader:
        assert reader.search("Legacy")[0].facts[1].value == "Preserve custom label"
    assert read_rules(legacy_db) == []
    assert audit_database(legacy_db)["valid"]
    with pytest.raises(ValueError, match="Schema 2"):
        import_catalog(legacy_db)
    with pytest.raises(FileExistsError):
        migrate_database(legacy_db, destination)
    assert legacy_db.read_bytes() == before


def test_reviewed_import_idempotence_scope_and_metadata(knowledge_db):
    assert import_catalog(knowledge_db) == {"imported": True, "buildings": 2, "rules": 5}
    before = knowledge_db.read_bytes()
    assert not import_catalog(knowledge_db)["imported"]
    assert knowledge_db.read_bytes() == before
    assert audit_database(knowledge_db)["valid"]
    with KnowledgeRepository(knowledge_db) as reader:
        assert len(reader.search("PlanterBox")) == 2
        reviewed = reader.search("Battery", game_version="326232", dlc_scope="UNKNOWN")[0]
        claim = reviewed.as_dict()["facts"]["name"]
        assert claim["source_accessed_on"] == "2026-11-01"
        assert claim["source_target_version"] == "326232"
        assert claim["redistribution"] == "REFERENCE_ONLY"
        assert reviewed.as_dict()["facts"]["power_generation_w"]["value"] == "UNKNOWN"
        assert reader.search("Battery", game_version="659901") == ()
    rules = read_rules(knowledge_db)
    assert {r["domain"] for r in rules} == {"oxygen", "food", "power", "water", "research"}
    water = read_rules(knowledge_db, domain="water", game_version="348553")[0]
    assert json.loads(water["parameters_json"])["minimum_output_temperature"] == 40
    assert read_rules(knowledge_db, game_version="999999") == []
    assert read_rules(knowledge_db, dlc_scope="BASE_GAME") == []


def test_import_rolls_back_every_write_on_collision(knowledge_db):
    catalog = deepcopy(packaged_catalog())
    catalog["buildings"][0]["variant_id"] = "Tile@UNKNOWN@UNKNOWN"
    catalog["buildings"][0]["building_id"] = "Tile"
    # Validation rejects inconsistent scopes before any SQL write.
    before = knowledge_db.read_bytes()
    with pytest.raises(ValueError):
        import_catalog(knowledge_db, catalog)
    assert knowledge_db.read_bytes() == before
    # A late SQL collision after inserting new source/variant rows must roll everything back.
    import_catalog(knowledge_db)
    catalog = deepcopy(packaged_catalog())
    catalog["catalog_id"] = "different-id-same-existing-variants"
    extra_source = deepcopy(catalog["sources"][0])
    extra_source["source_id"] = "new_source"
    catalog["sources"].append(extra_source)
    with pytest.raises(sqlite3.IntegrityError):
        import_catalog(knowledge_db, catalog)
    with closing(sqlite3.connect(knowledge_db)) as db:
        assert not db.execute("SELECT * FROM source WHERE source_id='new_source'").fetchall()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c["sources"][0].pop("rights_note"),
        lambda c: c["sources"][0].update(accessed_on="not-a-date"),
        lambda c: c["sources"][0].update(redistribution="FREE_ASSUMED"),
        lambda c: c["rules"][0].update(game_version="659901"),
        lambda c: c["buildings"][0].update(dlc_scope="ASSUMED_DLC"),
        lambda c: c["buildings"][0]["facts"]["name"].update(status="GAME_VERIFIED"),
        lambda c: c["buildings"][0].update(identity_status="GAME_VERIFIED"),
        lambda c: c["sources"][0].update(verbatim_body="Unlicensed article body"),
    ],
)
def test_catalog_rejects_unverified_or_inconsistent_metadata(mutate):
    catalog = deepcopy(packaged_catalog())
    mutate(catalog)
    with pytest.raises(ValueError):
        validate_catalog(catalog)


@pytest.mark.parametrize(
    "value,unit", [(True, "W"), (float("nan"), "W"), (float("inf"), "W"), (-1, "W"), (0, None)]
)
def test_numeric_fact_validation(value, unit):
    sources = {"test": {}}
    claim = dict(
        value=value,
        unit=unit,
        status="SOURCE_REVIEWED",
        source_id="test",
        locator="Synthetic test",
        note="Not game data",
    )
    with pytest.raises(ValueError):
        validate_fact("power_consumption_w", claim, sources, set())
    claim.update(value=0, unit="W")
    validate_fact("power_consumption_w", claim, sources, set())
    claim.update(status="UNKNOWN", value=0, unit=None)
    with pytest.raises(ValueError, match="UNKNOWN"):
        validate_fact("power_consumption_w", claim, sources, set())


def test_nested_array_validation_and_temperature_bounds():
    evidence = dict(source_id="test", locator="Synthetic test")
    claim = dict(
        value=[dict(material_id="Water", amount=0, unit="kg/s", condition="Test", **evidence)],
        status="SOURCE_REVIEWED",
        note="Synthetic only",
        **evidence,
    )
    validate_fact("inputs", claim, {"test": {}}, {"Water"})
    with pytest.raises(ValueError, match="Unregistered"):
        validate_fact("inputs", claim, {"test": {}}, set())
    claim["value"][0]["amount"] = None
    with pytest.raises(ValueError, match="Unknown amount"):
        validate_fact("inputs", claim, {"test": {}}, {"Water"})
    claim["value"][0]["unit"] = None
    validate_fact("inputs", claim, {"test": {}}, {"Water"})
    claim["value"][0].pop("locator")
    with pytest.raises(ValueError, match="locator"):
        validate_fact("inputs", claim, {"test": {}}, {"Water"})
    claim["value"] = [
        dict(kind="operating_min", value=40, unit="degC", condition="test", **evidence),
        dict(kind="operating_max", value=300, unit="K", condition="test", **evidence),
    ]
    with pytest.raises(ValueError, match="Inverted"):
        validate_fact("temperature_constraints", claim, {"test": {}}, set())


def test_audit_detects_source_version_corruption(knowledge_db):
    import_catalog(knowledge_db)
    with closing(sqlite3.connect(knowledge_db)) as db, db:
        db.execute("UPDATE source_review SET target_version='000000' WHERE source_id='klei_326232'")
    assert not audit_database(knowledge_db)["valid"]


@pytest.mark.parametrize(
    "field,item",
    [
        (
            "construction_materials",
            {"slot": 0, "material_category": "RawMineral", "mass_kg": 0, "candidates": [[]]},
        ),
        ("research", {"research_id": "TestResearch", "relation": "ASSUMED"}),
        (
            "temperature_constraints",
            {"kind": "overheat", "value": -1, "unit": "K", "condition": "test"},
        ),
    ],
)
def test_nested_material_research_environment_fail_closed(field, item):
    item.update(source_id="test", locator="Synthetic test only")
    claim = dict(
        value=[item],
        status="SOURCE_REVIEWED",
        source_id="test",
        locator="Synthetic test only",
        note="Not game specifications",
    )
    with pytest.raises(ValueError):
        validate_fact(field, claim, {"test": {}}, set())
