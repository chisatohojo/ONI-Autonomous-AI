import json
import sqlite3
from contextlib import closing

import pytest

from oni_ai.knowledge import FIELDS, KnowledgeRepository, create_database


def test_seed_is_sourced_but_game_specs_stay_unknown(knowledge_db):
    with KnowledgeRepository(knowledge_db) as repository:
        building = repository.search("manual generator")[0]
    assert building.building_id == "ManualGenerator"
    assert building.game_version == building.dlc_scope == "UNKNOWN"
    assert building.identity_status == "SOURCE_REVIEWED"
    claims = building.as_dict()["facts"]
    assert set(claims) == set(FIELDS)
    assert claims["name"]["value"] == "Manual Generator"
    assert claims["name"]["source_revision"] == "14c08591cbd0bf66cd0f53b37bfb498bdef4abf6"
    assert len(claims["name"]["source_sha256"]) == 64
    for field in set(FIELDS) - {"name"}:
        assert claims[field]["value"] == "UNKNOWN"
        assert claims[field]["status"] == "UNKNOWN"


def test_literal_search_and_injection(knowledge_db):
    with KnowledgeRepository(knowledge_db) as repository:
        assert len(repository.search("tile")) == 1
        for query in ("%", "_", "' OR 1=1 --", "\\", "UNKNOWN"):
            assert repository.search(query) == ()
        assert repository.search("missing") == ()


def test_exact_scope_does_not_treat_unknown_as_compatible(knowledge_db):
    with KnowledgeRepository(knowledge_db) as repository:
        assert repository.search("Tile", game_version="525812") == ()
        assert repository.search("Tile", dlc_scope="BASE_GAME") == ()
        assert len(repository.search("Tile", game_version="UNKNOWN", dlc_scope="UNKNOWN")) == 1


@pytest.mark.parametrize("query,limit", [(" ", 20), ("tile", 0), ("tile", 101)])
def test_invalid_search_arguments(knowledge_db, query, limit):
    with KnowledgeRepository(knowledge_db) as repository, pytest.raises(ValueError):
        repository.search(query, limit=limit)


def test_read_only_query_does_not_change_bytes(knowledge_db):
    before = knowledge_db.read_bytes()
    with KnowledgeRepository(knowledge_db) as repository:
        repository.search("tile")
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            repository._connection.execute("DELETE FROM fact")
    assert knowledge_db.read_bytes() == before


def test_init_refuses_overwrite(knowledge_db):
    before = knowledge_db.read_bytes()
    with pytest.raises(FileExistsError):
        create_database(knowledge_db)
    assert knowledge_db.read_bytes() == before


def test_missing_db_is_not_implicitly_created(tmp_path):
    path = tmp_path / "absent.sqlite3"
    with pytest.raises(sqlite3.OperationalError):
        KnowledgeRepository(path)
    assert not path.exists()


def test_wrong_schema_rejected(knowledge_db):
    with closing(sqlite3.connect(knowledge_db)) as connection:
        connection.execute("PRAGMA user_version = 999")
    with pytest.raises(ValueError, match="schema"):
        KnowledgeRepository(knowledge_db)


@pytest.mark.parametrize(
    "value,unit,status,source",
    [
        (None, "W", "UNKNOWN", None),
        ("0", "W", "UNKNOWN", "aliases"),
        ("0", "W", "SOURCE_REVIEWED", None),
        ('"UNKNOWN"', "W", "SOURCE_REVIEWED", "aliases"),
        ("-1", "W", "SOURCE_REVIEWED", "aliases"),
        ("1", None, "SOURCE_REVIEWED", "aliases"),
        ("1", "kg", "SOURCE_REVIEWED", "aliases"),
        ("true", "W", "SOURCE_REVIEWED", "aliases"),
    ],
)
def test_schema_rejects_invalid_numeric_claims(knowledge_db, value, unit, status, source):
    with closing(sqlite3.connect(knowledge_db)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """UPDATE fact SET value_json=?, unit=?, status=?, source_id=?, locator='test'
                   WHERE field='power_consumption_w'""",
                (value, unit, status, source),
            )


def test_zero_power_is_distinct_from_unknown(knowledge_db):
    # Synthetic DB validation only: no claim about actual building power.
    with closing(sqlite3.connect(knowledge_db)) as connection, connection:
        connection.execute(
            """UPDATE fact SET value_json='0', unit='W', status='SOURCE_REVIEWED',
               source_id='aliases', locator='synthetic test', note='SYNTHETIC TEST ONLY'
               WHERE field='power_consumption_w'"""
        )
    with KnowledgeRepository(knowledge_db) as repository:
        claim = repository.search("Tile")[0].as_dict()["facts"]["power_consumption_w"]
    assert claim["value"] == 0
    assert claim["value"] != "UNKNOWN"


def test_foreign_keys_and_integrity(knowledge_db):
    with closing(sqlite3.connect(knowledge_db)) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("SELECT COUNT(*) FROM building_variant").fetchone()[0] == 3
        known = connection.execute("SELECT value_json FROM fact WHERE status<>'UNKNOWN'").fetchall()
        assert len(known) == 3
        assert all(isinstance(json.loads(value[0]), str) for value in known)
