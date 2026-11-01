import json
import multiprocessing
import time
from dataclasses import asdict
from pathlib import Path

import pytest

from oni_ai.episode_knowledge import database_snapshot
from oni_ai.episodes import EpisodeConfig, EpisodeEngine
from oni_ai.evaluation import _canonical
from oni_ai.policy import SeededTestPolicy
from oni_ai.policy_process import PolicyProcessError, ProcessBudget, ProcessPolicy
from oni_ai.research import replay_research, run_research_episode
from oni_ai.research_boundary import pointer_value, validate_envelope
from oni_ai.research_policy import ResearchPolicy
from oni_ai.simulation import load_fixture


def context(db=None, fixture=None):
    engine = EpisodeEngine(
        fixture or load_fixture("normal"),
        "a" * 32,
        EpisodeConfig(),
        {"work": 100},
        database_snapshot(db),
    )
    policy = ResearchPolicy("lookahead")
    return engine, engine.context(policy.queries(engine.inputs()))


class FaultPolicy(ResearchPolicy):
    def propose(self, context):
        if self.name == "hang":
            while True:
                time.sleep(1)
        if self.name == "crash":
            raise RuntimeError("must not disclose this message")
        if self.name == "large":
            return "x" * 100000
        if self.name == "malformed":
            return '{"schema_version":1,"schema_version":2}'
        if self.name == "network":
            import socket

            socket.create_connection(("127.0.0.1", 1))
        return super().propose(context)

    def __init__(self, name, seed):
        super().__init__("exploration", seed)
        self.name = name


def fault_host(name, seed, budget):
    return ProcessPolicy(name, seed, budget, factory=FaultPolicy)


def test_baseline_uses_the_original_seeded_actions_and_common_information(knowledge_db):
    engine, ctx = context(knowledge_db)
    baseline = ResearchPolicy("exploration", 13)
    original = SeededTestPolicy(13)
    assert baseline.queries(engine.inputs()) == ResearchPolicy("lookahead").queries(engine.inputs())
    assert baseline.propose(ctx)["proposal"] == original.propose(ctx)
    envelope = ResearchPolicy("lookahead").propose(ctx)
    assert (
        validate_envelope(envelope, json.loads(ctx.inputs.observation_json), ctx.knowledge, set())[
            1
        ]
        == []
    )
    assert any(c["status"] == "UNKNOWN" for c in envelope["claims"])
    assert all(
        not ref.startswith("db:") for ref in envelope["proposal"]["decision"]["evidence_refs"]
    )


def test_lookahead_uses_state_and_preserves_unknown_without_fixture_labels():
    fixture = load_fixture("unknown_oxygen")
    fixture["fixture_id"] = "secret-answer"
    engine, ctx = context(fixture=fixture)
    payload = _canonical(asdict(ctx))
    assert "secret-answer" not in payload and "unknown_oxygen" not in payload
    envelope = ResearchPolicy("lookahead").propose(ctx)
    assert "obs:/resources/oxygen" in envelope["proposal"]["decision"]["unknowns"]
    assert not validate_envelope(
        envelope, json.loads(ctx.inputs.observation_json), ctx.knowledge, set()
    )[1]
    before = engine.environment.observe()
    assert before["resources"]["oxygen"] is None


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ("value", "CLAIM_VALUE_OR_STATUS_MISMATCH"),
        ("status", "CLAIM_VALUE_OR_STATUS_MISMATCH"),
        ("missing", "MISSING_STRUCTURED_CLAIM"),
        ("id", "CLAIM_NOT_RETRIEVED"),
        ("digest", "STALE_OBSERVATION_DIGEST"),
        ("context", "CONTEXT_MISMATCH"),
        ("tick", "STALE_OBSERVATION"),
        ("operation", "INVALID_DECISION"),
        ("unknown", "UNDECLARED_UNKNOWNS"),
    ],
)
def test_structured_guards_reject_unjustified_decisions(mutation, expected, knowledge_db):
    _, ctx = context(knowledge_db, load_fixture("unknown_oxygen"))
    envelope = ResearchPolicy("lookahead").propose(ctx)
    if mutation in {"value", "status"}:
        envelope["claims"][0][mutation] = 0 if mutation == "value" else "GAME_VERIFIED"
    elif mutation == "missing":
        envelope["claims"] = [c for c in envelope["claims"] if c["evidence_id"].startswith("db:")]
    elif mutation == "id":
        envelope["claims"][0]["evidence_id"] = "invented"
    elif mutation == "digest":
        envelope["proposal"]["observation_digest"] = "0" * 64
    elif mutation in {"context", "tick", "operation"}:
        key = {"context": "context_id", "tick": "expected_tick", "operation": "kind"}[mutation]
        envelope["proposal"]["decision"]["action"][key] = 999 if mutation == "tick" else "bad"
    else:
        envelope["proposal"]["decision"]["unknowns"] = []
    proposal, failures = validate_envelope(
        envelope, json.loads(ctx.inputs.observation_json), ctx.knowledge, set()
    )
    assert proposal is None and expected in failures


def test_database_unknown_claim_cannot_be_promoted_and_scalar_zero_is_exact(knowledge_db):
    _, ctx = context(knowledge_db)
    envelope = ResearchPolicy("lookahead").propose(ctx)
    claim = next(c for c in envelope["claims"] if c["status"] == "UNKNOWN")
    claim["status"] = "GAME_VERIFIED"
    assert (
        "CLAIM_VALUE_OR_STATUS_MISMATCH"
        in validate_envelope(
            envelope, json.loads(ctx.inputs.observation_json), ctx.knowledge, set()
        )[1]
    )
    assert pointer_value({"a/b": [0, None]}, "/a~1b/0") == 0
    assert pointer_value({"x": None}, "/x") is None
    for pointer in ("x", "/bad", "/a~2b", "/a~1b/01"):
        with pytest.raises((ValueError, KeyError)):
            pointer_value({"a/b": [0]}, pointer)


def test_process_roundtrip_isolated_worker_and_cleanup():
    _, ctx = context()
    with ProcessPolicy("lookahead") as host:
        directory = Path(host.directory.name)
        pid = host.pid
        assert host.queries(ctx.inputs)
        assert host.propose(ctx)["proposal"]["decision"]["rationale"]
    assert host.cleanup_verified and not directory.exists()
    assert pid not in {p.pid for p in multiprocessing.active_children()}


@pytest.mark.parametrize(
    "name,code",
    [("hang", "POLICY_TIMEOUT"), ("crash", "POLICY_EXCEPTION"), ("large", "OUTPUT_BUDGET")],
)
def test_worker_faults_terminate_and_remove_mailbox(name, code):
    _, ctx = context()
    host = ProcessPolicy(name, budget=ProcessBudget(call_seconds=0.1), factory=FaultPolicy)
    directory, pid = Path(host.directory.name), host.pid
    started = time.monotonic()
    with pytest.raises(PolicyProcessError, match=code):
        host.propose(ctx)
    assert time.monotonic() - started < 5
    assert host.cleanup_verified and not directory.exists()
    assert pid not in {p.pid for p in multiprocessing.active_children()}


def test_total_deadline_and_child_network_blocking():
    _, ctx = context()
    with ProcessPolicy("exploration") as host:
        host.started -= host.budget.total_seconds + 1
        with pytest.raises(PolicyProcessError, match="TIME_BUDGET"):
            host.queries(ctx.inputs)
        assert host.cleanup_verified
    with ProcessPolicy("network", factory=FaultPolicy) as host:
        with pytest.raises(PolicyProcessError, match="POLICY_EXCEPTION"):
            host.propose(ctx)
        assert host.cleanup_verified


def test_worker_startup_failure_has_no_remaining_child():
    previous = {p.pid for p in multiprocessing.active_children()}
    with pytest.raises(PolicyProcessError, match="WORKER_EXITED"):
        ProcessPolicy("unsupported")
    assert {p.pid for p in multiprocessing.active_children()} == previous


def test_execution_error_receipt_replays_as_fault_event(tmp_path, monkeypatch):
    from oni_ai.simulation import SyntheticEnvironment

    path = tmp_path / "execute-error.jsonl"

    def broken(*args, **kwargs):
        raise RuntimeError("do not log this")

    with monkeypatch.context() as scoped:
        scoped.setattr(SyntheticEnvironment, "step", broken)
        result = run_research_episode(
            load_fixture("normal"), "exploration", 0, path, episode_id="f" * 32
        )
    assert result["stop_reason"] == "EXECUTION_ERROR"
    assert result["metrics"]["execution"]["ticks"] == 0
    assert replay_research(path)["verified"]
    assert "do not log this" not in path.read_text("utf-8")


def test_ledger_unknowns_remain_unknown(tmp_path):
    path = tmp_path / "unknown.jsonl"
    result = run_research_episode(
        load_fixture("unknown_oxygen"),
        "lookahead",
        0,
        path,
        episode_id="1" * 32,
        config=EpisodeConfig(max_steps=2),
    )
    assert result["metrics"]["resource_balance"]["oxygen"]["final"] is None
    assert result["metrics"]["resource_balance"]["oxygen"]["synthetic_consumption"] is None
    assert replay_research(path)["verified"]


def test_consumption_ledger_balances_fractional_and_multitick_actions():
    from oni_ai.research import advance_event, research_metrics
    from oni_ai.research_policy import claimed

    fixture = load_fixture("normal")
    fixture["resources"]["food"] = 0.5
    fixture["demand"]["food"] = 0.75
    engine, ctx = context(fixture=fixture)
    proposal = SeededTestPolicy(1).propose(ctx)
    proposal["decision"]["action"].update(kind="wait", target=None, enabled=None, ticks=3)
    record = advance_event(
        engine, ResearchPolicy("exploration").queries(engine.inputs()), claimed(proposal, ctx)
    )
    assert record["step"]["status"] == "APPLIED"
    metrics = research_metrics(engine, [record])
    assert metrics["execution"]["ticks"] == 3
    assert metrics["resource_balance"]["food"]["synthetic_consumption"] >= 0.5


def test_log_size_stop_is_complete_and_replayable(tmp_path, monkeypatch):
    import oni_ai.research as research

    monkeypatch.setattr(research, "MAX_LOG_BYTES", 14000)
    path = tmp_path / "budget.jsonl"
    result = run_research_episode(load_fixture("normal"), "lookahead", 0, path, episode_id="2" * 32)
    assert result["stop_reason"] == "LOG_SIZE_LIMIT"
    assert path.stat().st_size <= research.MAX_LOG_BYTES
    assert replay_research(path)["verified"]


@pytest.mark.parametrize(
    "kwargs,code", [({"max_calls": 1}, "CALL_BUDGET"), ({"max_input_bytes": 1}, "INPUT_BUDGET")]
)
def test_worker_request_budgets(kwargs, code):
    _, ctx = context()
    with ProcessPolicy("exploration", budget=ProcessBudget(**kwargs)) as host:
        if code == "CALL_BUDGET":
            host.queries(ctx.inputs)
        with pytest.raises(PolicyProcessError, match=code):
            host.propose(ctx)
        assert host.cleanup_verified


@pytest.mark.parametrize(
    "kwargs",
    [
        {"call_seconds": 0},
        {"total_seconds": float("nan")},
        {"max_calls": True},
        {"max_output_bytes": 1000001},
    ],
)
def test_invalid_worker_budgets(kwargs):
    with pytest.raises(ValueError):
        ProcessBudget(**kwargs)


def test_research_episode_claims_ledger_metrics_and_replay(tmp_path, knowledge_db):
    path = tmp_path / "research.jsonl"
    before = knowledge_db.read_bytes()
    result = run_research_episode(
        load_fixture("normal"),
        "lookahead",
        0,
        path,
        episode_id="b" * 32,
        config=EpisodeConfig(max_steps=5),
        snapshot=database_snapshot(knowledge_db),
    )
    assert result["metrics"]["validity"]["attempts"] == 5
    assert result["cleanup_verified"]
    assert knowledge_db.read_bytes() == before
    assert replay_research(path)["metrics"] == result["metrics"]
    assert result["metrics"]["resource_balance"]["water"]["synthetic_consumption"] >= 0
    assert result["metrics"]["uncertainty"]["claim_rejections"] == 0
    with pytest.raises(FileExistsError):
        run_research_episode(load_fixture("normal"), "lookahead", 0, path, episode_id="b" * 32)


@pytest.mark.parametrize("name", ["hang", "malformed", "crash"])
def test_abnormal_episode_is_recorded_and_replayable(tmp_path, name):
    path = tmp_path / f"{name}.jsonl"
    result = run_research_episode(
        load_fixture("normal"),
        name,
        0,
        path,
        episode_id="c" * 32,
        config=EpisodeConfig(max_steps=3),
        budget=ProcessBudget(call_seconds=0.1),
        factory=fault_host,
    )
    assert result["cleanup_verified"]
    assert result["metrics"]["validity"]["rejected"] > 0
    assert replay_research(path)["verified"]
    assert "must not disclose" not in path.read_text("utf-8")


@pytest.mark.parametrize("mutation", ["claim", "state", "summary", "incomplete"])
def test_research_replay_rejects_tampered_or_partial_logs(tmp_path, mutation):
    path = tmp_path / "receipt.jsonl"
    run_research_episode(
        load_fixture("normal"),
        "exploration",
        0,
        path,
        episode_id="d" * 32,
        config=EpisodeConfig(max_steps=2),
    )
    records = [json.loads(line) for line in path.read_text("utf-8").splitlines()]
    if mutation == "claim":
        records[1]["response"]["claims"][0]["value"] = "invented"
    elif mutation == "state":
        records[1]["step"]["after"]["resources"]["food"] += 1
    elif mutation == "summary":
        records[-1]["metrics"]["validity"]["attempts"] += 1
    else:
        records.pop()
    path.write_text("\n".join(_canonical(r) for r in records) + "\n", "utf-8")
    with pytest.raises(ValueError):
        replay_research(path)
