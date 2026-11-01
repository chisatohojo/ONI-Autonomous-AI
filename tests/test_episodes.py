import json
from copy import deepcopy
from dataclasses import FrozenInstanceError, asdict

import pytest

from oni_ai.contracts import Decision, SyntheticAction, strict_json
from oni_ai.episode_knowledge import KnowledgeQuery
from oni_ai.episodes import EpisodeConfig, replay_episode, run_episode
from oni_ai.policy import SeededTestPolicy
from oni_ai.simulation import SyntheticEnvironment, load_fixture


def envelope(context, *, kind="wait", target=None, enabled=None, action_id=None):
    observation = strict_json(context.inputs.observation_json)
    refs = ["model:actions"] + ([f"model:process:{target}"] if target is not None else [])
    decision = Decision(
        SyntheticAction(
            action_id or f"a-{observation['tick']}-{len(context.inputs.memory)}",
            observation["context_id"],
            observation["tick"],
            kind,
            target,
            enabled,
        ),
        "Explicit unit-test proposal, not a shipped strategy",
        tuple(refs),
        context.unknowns,
    )
    return {
        "schema_version": 1,
        "observation_digest": observation["observation_digest"],
        "decision": json.loads(json.dumps(decision.as_dict())),
    }


class CallbackPolicy:
    name = "callback-test-double"

    def __init__(self, callback=envelope, queries=None):
        self.callback = callback
        self.requested_queries = queries or (KnowledgeQuery("model", "*"),)
        self.contexts = []

    def queries(self, inputs):
        return self.requested_queries

    def propose(self, context):
        self.contexts.append(context)
        return self.callback(context)


def long_limits(**overrides):
    config = dict(
        max_steps=4, no_progress_limit=200, repeat_limit=200, error_limit=200, memory_limit=2
    )
    config.update(overrides)
    return EpisodeConfig(**config)


def records(path):
    return [json.loads(line) for line in path.read_text("utf-8").splitlines()]


def test_multistep_loop_memory_and_episode_unique_observation_contexts(tmp_path):
    fixture = load_fixture("normal")
    original = deepcopy(fixture)
    policy = CallbackPolicy()
    path = tmp_path / "episode.jsonl"
    summary = run_episode(fixture, policy, path, config=long_limits(), objective={"work": 1000})
    assert fixture == original
    assert summary["stop_reason"] == "MAX_STEPS"
    assert summary["attempts"] == 4
    assert summary["metrics"]["progress"]["work_delta"] == 4
    assert summary["metrics"]["validity"]["invalid_action_rate"] == 0
    assert [len(c.inputs.memory) for c in policy.contexts] == [0, 1, 2, 2]
    assert policy.contexts[1].inputs.memory[0].decision_json is not None
    assert all(c.knowledge for c in policy.contexts)
    assert replay_episode(path)["verified"]
    another = run_episode(
        fixture, CallbackPolicy(), tmp_path / "another.jsonl", config=long_limits()
    )
    assert summary["final_observation"]["context_id"] != another["final_observation"]["context_id"]
    with pytest.raises(FileExistsError):
        run_episode(fixture, CallbackPolicy(), path)


def test_policy_inputs_do_not_leak_fixture_labels_or_original_process_names(tmp_path):
    fixture = load_fixture("work_stalled")
    fixture["description"] = "SECRET_EVALUATION_LABEL"
    policy = CallbackPolicy()
    run_episode(fixture, policy, tmp_path / "episode.jsonl", config=long_limits())
    for context in policy.contexts:
        serialized = json.dumps(asdict(context))
        for secret in ("work_stalled", "SECRET_EVALUATION_LABEL", *fixture["processes"]):
            assert secret not in serialized
        observation = strict_json(context.inputs.observation_json)
        assert "fixture_id" not in observation
        assert all(name.startswith("p") for name in observation["processes"])
    with pytest.raises(FrozenInstanceError):
        policy.contexts[0].unknowns = ()


def test_replacement_policy_can_use_failure_memory_to_revise_proposals(tmp_path):
    def revise(context):
        proposal = envelope(context)
        if not context.inputs.memory:
            proposal["decision"]["evidence_refs"] = ["invented:proof"]
        else:
            assert context.inputs.memory[0].failures
            proposal["decision"]["rationale"] = (
                "Use the recorded failure to correct the references."
            )
        return proposal

    path = tmp_path / "feedback.jsonl"
    summary = run_episode(
        load_fixture("normal"),
        CallbackPolicy(revise),
        path,
        config=long_limits(max_steps=3),
        objective={"work": 1000},
    )
    assert summary["metrics"]["validity"]["rejected"] == 1
    assert summary["metrics"]["validity"]["applied"] == 2
    assert replay_episode(path)["verified"]


@pytest.mark.parametrize(
    "mutate,expected",
    [
        (lambda p: p.update(observation_digest="0" * 64), "STALE_OBSERVATION_DIGEST"),
        (lambda p: p["decision"]["action"].update(expected_tick=99), "STALE_OBSERVATION"),
        (lambda p: p["decision"]["action"].update(context_id="different"), "CONTEXT_MISMATCH"),
        (
            lambda p: p["decision"].update(evidence_refs=["model:actions", "invented:proof"]),
            "EVIDENCE_NOT_RETRIEVED",
        ),
        (lambda p: p["decision"].update(evidence_refs=[]), "MISSING_ACTION_EVIDENCE"),
        (lambda p: p["decision"]["action"].update(kind="tools/call"), "INVALID_DECISION"),
        (lambda p: p["decision"]["action"].update(dry_run=True), "PREVIEW_ONLY_ACTION"),
    ],
)
def test_invalid_proposals_are_logged_and_rejected_without_execution(tmp_path, mutate, expected):
    def invalid(context):
        proposal = envelope(context)
        mutate(proposal)
        return proposal

    path = tmp_path / "rejected.jsonl"
    summary = run_episode(
        load_fixture("normal"), CallbackPolicy(invalid), path, config=long_limits(error_limit=1)
    )
    step = records(path)[1]
    assert expected in step["failures"]
    assert step["status"] == "REJECTED"
    assert step["before"] == step["after"]
    assert summary["stop_reason"] == "ERROR_LIMIT"
    assert summary["metrics"]["validity"]["invalid_action_rate"] == 1
    assert replay_episode(path)["verified"]


@pytest.mark.parametrize(
    "condition,prefix",
    [
        ("resource", "INSUFFICIENT_INPUT:"),
        ("unknown", "UNKNOWN_RESOURCE:"),
        ("research", "RESEARCH_UNAVAILABLE:"),
        ("blockage", "BLOCKED:"),
    ],
)
def test_resource_and_environment_preconditions_are_checked_before_execution(
    tmp_path, condition, prefix
):
    fixture = load_fixture("normal")
    if condition == "resource":
        fixture["resources"]["energy"] = 0
    elif condition == "unknown":
        fixture["resources"]["water"] = None
    elif condition == "research":
        fixture["processes"]["food_unit"]["requires_research"] = 1
    else:
        fixture["processes"]["food_unit"]["blocked"] = True

    def propose(context):
        observation = strict_json(context.inputs.observation_json)
        target = next(key for key, p in observation["processes"].items() if "food" in p["outputs"])
        return envelope(context, kind="set_process", target=target, enabled=True)

    path = tmp_path / "precondition.jsonl"
    run_episode(fixture, CallbackPolicy(propose), path, config=long_limits(error_limit=1))
    step = records(path)[1]
    assert any(f.startswith(prefix) for f in step["failures"])
    assert step["after"] == step["before"]
    assert replay_episode(path)["verified"]


def test_unknown_is_not_imputed_and_must_be_declared(tmp_path):
    def omit(context):
        proposal = envelope(context)
        proposal["decision"]["unknowns"] = []
        return proposal

    path = tmp_path / "unknown.jsonl"
    summary = run_episode(
        load_fixture("unknown_oxygen"),
        CallbackPolicy(omit),
        path,
        config=long_limits(error_limit=1),
    )
    assert "UNDECLARED_UNKNOWNS" in records(path)[1]["failures"]
    assert summary["final_observation"]["resources"]["oxygen"] is None
    assert summary["metrics"]["survival"]["synthetic_demand_proxy"] is None


@pytest.mark.parametrize(
    "mode,reason",
    [
        ("goal", "GOAL_REACHED"),
        ("repeat", "REPEATED_ACTION"),
        ("stall", "NO_PROGRESS"),
        ("budget", "MAX_STEPS"),
    ],
)
def test_goal_and_bounded_termination_modes(tmp_path, mode, reason):
    fixture = load_fixture("normal")
    config = long_limits(max_steps=3)
    target = 1000
    if mode == "goal":
        target = 2
    elif mode == "repeat":
        config = long_limits(repeat_limit=3)
    elif mode == "stall":
        fixture["processes"]["work_unit"]["enabled"] = False
        config = long_limits(no_progress_limit=2)
    path = tmp_path / "stop.jsonl"
    summary = run_episode(
        fixture, CallbackPolicy(), path, config=config, objective={"work": target}
    )
    assert summary["stop_reason"] == reason
    assert replay_episode(path)["verified"]


def test_duplicate_ids_are_rejected_even_when_tick_is_fresh(tmp_path):
    policy = CallbackPolicy(lambda context: envelope(context, action_id="same-id"))
    path = tmp_path / "duplicate.jsonl"
    run_episode(load_fixture("normal"), policy, path, config=long_limits(error_limit=1))
    steps = records(path)[1:-1]
    assert steps[0]["status"] == "APPLIED"
    assert "DUPLICATE_DECISION_ID" in steps[1]["failures"]


@pytest.mark.parametrize("stage", ["queries", "propose", "serialize"])
def test_policy_errors_produce_complete_replayable_receipts(tmp_path, stage):
    class BrokenPolicy(CallbackPolicy):
        def queries(self, inputs):
            if stage == "queries":
                raise RuntimeError("Deliberate test fault")
            return super().queries(inputs)

        def propose(self, context):
            if stage == "propose":
                raise RuntimeError("Deliberate test fault")
            return object()

    path = tmp_path / "policy-error.jsonl"
    summary = run_episode(
        load_fixture("normal"), BrokenPolicy(), path, config=long_limits(error_limit=2)
    )
    assert summary["stop_reason"] == "ERROR_LIMIT"
    assert records(path)[1]["fault"]["stage"] == stage
    assert replay_episode(path)["recorded_fault_events"] == 2


def test_execution_fault_cannot_partially_mutate_state(tmp_path, monkeypatch):
    def broken(self, action):
        self._resources["water"] = 999
        raise RuntimeError("Injected preflight/execution failure")

    path = tmp_path / "execution-error.jsonl"
    with monkeypatch.context() as patch:
        patch.setattr(SyntheticEnvironment, "step", broken)
        summary = run_episode(load_fixture("normal"), CallbackPolicy(), path, config=long_limits())
    assert summary["stop_reason"] == "EXECUTION_ERROR"
    assert summary["final_observation"]["resources"]["water"] == 30
    assert replay_episode(path)["recorded_fault_events"] == 1


def test_initial_goal_and_unknown_goal_do_not_call_policy(tmp_path):
    for unknown in (False, True):
        fixture = load_fixture("normal")
        fixture["resources"]["work"] = None if unknown else 10
        policy = CallbackPolicy()
        path = tmp_path / f"initial-{unknown}.jsonl"
        summary = run_episode(fixture, policy, path, objective={"work": 2})
        assert summary["stop_reason"] == ("UNKNOWN_GOAL" if unknown else "GOAL_ALREADY_MET")
        assert not policy.contexts
        assert summary["metrics"]["validity"]["invalid_action_rate"] is None
        assert replay_episode(path)["verified"]


@pytest.mark.parametrize(
    "change", ["proposal", "knowledge", "state", "metrics", "stop", "truncate"]
)
def test_episode_replay_detects_inconsistency(tmp_path, change):
    path = tmp_path / "tamper.jsonl"
    run_episode(load_fixture("normal"), SeededTestPolicy(1), path, config=long_limits(max_steps=2))
    data = records(path)
    if change == "proposal":
        data[1]["proposal"]["observation_digest"] = "0" * 64
    elif change == "knowledge":
        data[1]["knowledge"][0]["value_json"] = '"altered"'
    elif change == "state":
        data[1]["after"]["resources"]["water"] = 777
    elif change == "metrics":
        data[-1]["metrics"]["validity"]["applied"] = 999
    elif change == "stop":
        data[-1]["stop_reason"] = "GUESS"
    else:
        data.pop()
    path.write_text("\n".join(json.dumps(r) for r in data), encoding="utf-8")
    with pytest.raises(ValueError):
        replay_episode(path)


@pytest.mark.parametrize("limit", [-1, 0, True, 201])
def test_invalid_limits_cannot_disable_episode_bounds(limit):
    with pytest.raises(ValueError):
        EpisodeConfig(max_steps=limit)


def test_log_budget_rolls_back_unwritten_step_and_keeps_receipt_replayable(tmp_path, monkeypatch):
    import oni_ai.episodes as episode_module

    monkeypatch.setattr(episode_module, "MAX_LOG_BYTES", 60000)

    def verbose(context):
        proposal = envelope(context)
        proposal["decision"]["rationale"] = "r" * 4000
        return proposal

    path = tmp_path / "bounded.jsonl"
    summary = run_episode(
        load_fixture("normal"),
        CallbackPolicy(verbose),
        path,
        config=long_limits(max_steps=30),
        objective={"work": 1000},
    )
    assert summary["stop_reason"] == "LOG_SIZE_LIMIT"
    assert path.stat().st_size < 60000
    final_step = records(path)[-2]
    assert final_step["before"] == final_step["after"]
    assert replay_episode(path)["verified"]
