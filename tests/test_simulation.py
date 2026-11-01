from copy import deepcopy

import pytest

from oni_ai.contracts import PROVENANCE, Decision, SyntheticAction, strict_json
from oni_ai.simulation import SyntheticEnvironment, fixture_names, load_fixture


def action(env, kind="wait", **kwargs):
    observation = env.observe()
    return SyntheticAction(
        f"step-{observation['tick']}",
        observation["context_id"],
        observation["tick"],
        kind,
        **kwargs,
    )


@pytest.mark.parametrize(
    "name,signal",
    [
        ("normal", None),
        ("oxygen_shortage", "LOW:oxygen"),
        ("food_shortage", "LOW:food"),
        ("power_shortage", "LOW:energy"),
        ("water_shortage", "LOW:water"),
        ("unknown_oxygen", "UNKNOWN:oxygen"),
    ],
)
def test_synthetic_fixture_outcomes_and_unknown_preservation(name, signal):
    fixture = load_fixture(name)
    before = deepcopy(fixture)
    env = SyntheticEnvironment(fixture)
    result = env.step(action(env))
    assert fixture == before
    assert result["status"] == "APPLIED"
    assert result["after"]["provenance"] == PROVENANCE
    if signal:
        assert signal in result["metrics"]["alerts"]
    else:
        assert result["metrics"]["alerts"] == []
    if name == "unknown_oxygen":
        assert result["after"]["resources"]["oxygen"] is None
    if name == "oxygen_shortage":
        assert result["after"]["resources"]["oxygen"] == 0
        assert "oxygen" in result["metrics"]["unmet_demand"]


def test_enabling_process_changes_result_without_chosen_strategy():
    idle = SyntheticEnvironment(load_fixture("oxygen_shortage"))
    changed = SyntheticEnvironment(load_fixture("oxygen_shortage"))
    baseline = idle.step(action(idle))
    result = changed.step(action(changed, "set_process", target="oxygen_unit", enabled=True))
    assert baseline["after"]["resources"]["oxygen"] == 0
    assert result["after"]["resources"]["oxygen"] == 2
    assert result["metrics"]["unmet_demand"] == []


def test_work_stall_and_research_prerequisite_transitions():
    env = SyntheticEnvironment(load_fixture("work_stalled"))
    assert env.step(action(env))["metrics"]["stalled"]
    assert not env.step(action(env, "clear_blockage", target="work_unit"))["metrics"]["stalled"]
    env = SyntheticEnvironment(load_fixture("research_locked"))
    blocked = env.step(action(env))
    assert "RESEARCH_UNAVAILABLE:work_unit" in blocked["failures"]
    env.step(action(env, "set_process", target="research_unit", enabled=True))
    result = env.step(action(env))
    assert result["metrics"]["work_delta"] == 1


def test_stale_duplicate_context_and_target_rejection_do_not_mutate_state():
    env = SyntheticEnvironment(load_fixture("normal"))
    first = action(env)
    env.step(first)
    before = env.observe()
    assert env.step(first)["failures"] == ["DUPLICATE_ACTION"]
    for invalid, reason in [
        (SyntheticAction("stale", before["context_id"], 0, "wait"), "STALE_OBSERVATION"),
        (SyntheticAction("context", "another-context", 1, "wait"), "CONTEXT_MISMATCH"),
        (
            SyntheticAction("target", before["context_id"], 1, "clear_blockage", target="missing"),
            "UNKNOWN_TARGET",
        ),
    ]:
        assert env.step(invalid)["failures"] == [reason]
        assert env.observe() == before


def test_dry_run_is_a_preview_and_does_not_consume_action_id():
    env = SyntheticEnvironment(load_fixture("work_stalled"))
    before = env.observe()
    preview = env.step(action(env, "clear_blockage", target="work_unit", dry_run=True))
    assert preview["status"] == "PREVIEW"
    assert preview["after"] == before == env.observe()
    assert preview["preview"]["resources"]["work"] == 1
    actual = env.step(action(env, "clear_blockage", target="work_unit"))
    assert actual["status"] == "APPLIED"
    assert actual["after"] == preview["preview"]


def test_resource_contention_does_not_silently_choose_a_process():
    fixture = load_fixture("normal")
    fixture["resources"]["energy"] = 1
    env = SyntheticEnvironment(fixture)
    result = env.step(action(env))
    assert "INSUFFICIENT_INPUT:work_unit" in result["failures"]
    assert "INSUFFICIENT_INPUT:food_unit" in result["failures"]
    assert result["after"]["resources"]["work"] == 0
    assert result["after"]["resources"]["energy"] == 6


@pytest.mark.parametrize(
    "change",
    [
        {"kind": "tools/call"},
        {"ticks": 0},
        {"ticks": 11},
        {"expected_tick": True},
        {"schema_version": True},
        {"target": "oxygen_unit"},
        {"dry_run": "true"},
        {"kind": "set_process", "target": "oxygen_unit", "enabled": 1},
        {"api_key": "forbidden"},
    ],
)
def test_invalid_actions_fail_closed(change):
    raw = dict(action_id="a", context_id="synthetic:normal", expected_tick=0, kind="wait")
    raw.update(change)
    with pytest.raises(ValueError):
        SyntheticAction.from_dict(raw)


@pytest.mark.parametrize("raw", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}'])
def test_strict_json_rejects_ambiguous_or_nonfinite_input(raw):
    with pytest.raises(ValueError):
        strict_json(raw)


def test_fixture_copies_and_rejects_actual_game_provenance():
    assert len(fixture_names()) == 8
    fixture = load_fixture("normal")
    env = SyntheticEnvironment(fixture)
    fixture["resources"]["oxygen"] = 0
    assert env.observe()["resources"]["oxygen"] == 10
    observation = env.observe()
    observation["resources"]["oxygen"] = 0
    assert env.observe()["resources"]["oxygen"] == 10
    fixture["provenance"] = "GAME_VERIFIED"
    with pytest.raises(ValueError):
        SyntheticEnvironment(fixture)
    with pytest.raises(ValueError):
        Decision.from_dict({"rationale": "Missing action"})


def test_float_overflow_cannot_corrupt_environment():
    fixture = load_fixture("normal")
    fixture["resources"]["energy"] = 1e308
    fixture["processes"]["power_unit"]["outputs"]["energy"] = 1e308
    env = SyntheticEnvironment(fixture)
    before = env.observe()
    result = env.step(action(env, "set_process", target="research_unit", enabled=True))
    assert result["status"] == "REJECTED"
    assert result["failures"] == ["MODEL_NUMERIC_LIMIT"]
    assert env.observe() == before
    with pytest.raises(ValueError, match="overflow"):
        strict_json('{"value":1e999}')
