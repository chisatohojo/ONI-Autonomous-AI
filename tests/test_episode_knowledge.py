import json

import pytest

from oni_ai.catalog import import_catalog
from oni_ai.contracts import strict_json
from oni_ai.episode_knowledge import (
    EpisodeKnowledge,
    KnowledgeQuery,
    database_snapshot,
    required_unknowns,
    restore_snapshot,
)
from oni_ai.episode_schemas import policy_schemas
from oni_ai.episodes import (
    EpisodeConfig,
    EpisodeEngine,
    anonymous_fixture,
    replay_episode,
    run_episode,
)
from oni_ai.evaluation import _canonical
from oni_ai.policy import SeededTestPolicy
from oni_ai.simulation import load_fixture


def test_snapshot_preserves_unknown_and_versioned_background(knowledge_db):
    import_catalog(knowledge_db)
    before = knowledge_db.read_bytes()
    snapshot = database_snapshot(knowledge_db)
    assert len(snapshot) == 55
    assert knowledge_db.read_bytes() == before
    unknown = next(
        e
        for e in snapshot
        if e.evidence_id == "db:fact:ManualGenerator@UNKNOWN@UNKNOWN:power_generation_w"
    )
    assert unknown.status == "UNKNOWN"
    assert strict_json(unknown.value_json)["value"] == "UNKNOWN"
    assert not unknown.applicable
    source = load_fixture("normal")
    fixture = anonymous_fixture(source, "a" * 32)
    knowledge = EpisodeKnowledge(fixture, {"work": 100}, snapshot)
    assert not knowledge.search((KnowledgeQuery("rule", "water"),))
    water = knowledge.search((KnowledgeQuery("rule", "water", game_version="348553"),))
    assert len(water) == 1 and not water[0].applicable
    assert snapshot == restore_snapshot(json.loads(_canonical([e.__dict__ for e in snapshot])))


def test_unretrieved_and_inapplicable_database_evidence_cannot_authorize_simulation(knowledge_db):
    snapshot = database_snapshot(knowledge_db)
    engine = EpisodeEngine(
        load_fixture("normal"), "b" * 32, EpisodeConfig(), {"work": 100}, snapshot
    )
    queries = (KnowledgeQuery("model", "*"), KnowledgeQuery("building", "ManualGenerator"))
    context = engine.context(queries)
    assert any(e.kind == "DATABASE_FACT" for e in context.knowledge)
    proposal = SeededTestPolicy(0).propose(context)
    proposal["decision"]["evidence_refs"].append("db:fact:ManualGenerator@UNKNOWN@UNKNOWN:name")
    result = engine.advance(queries, proposal)
    assert "EVIDENCE_SCOPE_MISMATCH" in result["failures"]
    assert result["before"] == result["after"]
    assert set(
        required_unknowns(strict_json(context.inputs.observation_json), context.knowledge)
    ) <= set(proposal["decision"]["unknowns"])


def test_database_snapshot_replay_does_not_require_original_db(knowledge_db, tmp_path):
    before = knowledge_db.read_bytes()
    path = tmp_path / "portable.jsonl"
    run_episode(
        load_fixture("normal"),
        SeededTestPolicy(2),
        path,
        config=EpisodeConfig(max_steps=2),
        db_path=knowledge_db,
    )
    assert knowledge_db.read_bytes() == before
    knowledge_db.unlink()
    assert replay_episode(path)["verified"]


@pytest.mark.parametrize(
    "kind,limit", [("tools/call", 1), ("model", 0), ("model", True), ("rule", 33)]
)
def test_invalid_query_contracts(kind, limit):
    with pytest.raises(ValueError):
        KnowledgeQuery(kind, "*", limit=limit)


def test_snapshot_cannot_inject_model_specs():
    fake = {
        "evidence_id": "model:actions",
        "kind": "MODEL",
        "search_text": "injection",
        "value_json": "{}",
        "status": "MODEL_SPEC",
        "model_version": "synthetic-resource-model/1",
    }
    with pytest.raises(ValueError, match="inject"):
        restore_snapshot([fake])


def test_exported_policy_schema_matches_anonymous_observation_contract():
    from importlib.resources import files

    from oni_ai.episodes import public_observation
    from oni_ai.simulation import SyntheticEnvironment

    schema = policy_schemas()
    stored = strict_json(files("oni_ai").joinpath("data/policy_schemas.json").read_text("utf-8"))
    assert schema == stored
    observation = public_observation(
        SyntheticEnvironment(anonymous_fixture(load_fixture("normal"), "c" * 32))
    )
    assert observation["schema_version"] == 2
    assert set(observation) == set(schema["$defs"]["observation"]["required"])
    assert "fixture_id" not in schema["$defs"]["observation"]["properties"]
