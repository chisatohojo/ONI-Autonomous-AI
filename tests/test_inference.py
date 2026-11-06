import json
import time
from dataclasses import asdict
from pathlib import Path

import pytest

from oni_ai.episodes import EpisodeConfig, EpisodeEngine
from oni_ai.evaluation import _canonical
from oni_ai.inference_broker import BrokerLimits, InferenceBroker, verify_broker_records
from oni_ai.inference_contracts import (
    CounterBinding,
    InferenceError,
    check_schema,
    envelope_schema,
    safe_json,
    validate_schema,
)
from oni_ai.inference_ipc import BrokerPolicyHost, mock_model_limits
from oni_ai.local_model import MockChatTransport, OllamaStructuredModel, profile_for
from oni_ai.model_adapter import BudgetedModelAdapter
from oni_ai.policy_process import PolicyProcessError, ProcessBudget
from oni_ai.research import replay_research, run_research_episode
from oni_ai.research_policy import ResearchPolicy
from oni_ai.simulation import load_fixture


def inputs(unknown=False):
    engine = EpisodeEngine(
        load_fixture("unknown_oxygen" if unknown else "normal"),
        "a" * 32,
        EpisodeConfig(),
        {"work": 100},
    )
    query = ResearchPolicy("exploration").queries(engine.inputs())
    return engine, engine.context(query)


def payload(context):
    return _canonical(
        {
            "schema_version": 1,
            "context": asdict(context),
            "response_contract": "research envelope: proposal, exact source claims, UNKNOWN",
            "previous_error": None,
        }
    )


def test_local_adapter_exact_mock_roundtrip_and_not_an_llm_token_estimate():
    _, context = inputs(True)
    transport = MockChatTransport(0)
    model = OllamaStructuredModel(profile_for("offline"), transport)
    adapter = BudgetedModelAdapter(model, mock_model_limits())
    result = adapter.propose(context)
    validate_schema(result, envelope_schema(context))
    assert "obs:/resources/oxygen" in result["proposal"]["decision"]["unknowns"]
    assert adapter.calls == 1 and transport.calls == 1
    assert model.count_tokens(payload(context)) > len(payload(context).encode("utf-8"))
    assert (
        CounterBinding("offline-byte-model/v1", "mock-utf8-byte/1", "mock-chat/1").count("日") == 3
    )


def test_unconfigured_real_model_never_generates():
    _, context = inputs()
    transport = MockChatTransport()
    model = OllamaStructuredModel(profile_for("unconfigured-local"), transport)
    with pytest.raises(InferenceError, match="EXACT_COUNTER_UNAVAILABLE"):
        BudgetedModelAdapter(model, mock_model_limits()).propose(context)
    assert transport.calls == 0


@pytest.mark.parametrize(
    "mode,code",
    [
        ("invalid_json", "INVALID_JSON"),
        ("partial", "PARTIAL_MODEL_OUTPUT"),
        ("oversize_usage", "USAGE_MISMATCH"),
        ("missing_usage", "INVALID_MODEL_RESPONSE"),
        ("stale", "EVIDENCE_OR_OBSERVATION_MISMATCH"),
        ("invented_evidence", "EVIDENCE_OR_OBSERVATION_MISMATCH"),
        ("promote_unknown", "EVIDENCE_OR_OBSERVATION_MISMATCH"),
        ("bad_schema", "SCHEMA_OUTPUT_MISMATCH"),
        ("secret", "SECRET_OR_PRIVATE_DATA"),
    ],
)
def test_model_rejects_anomalies(mode, code):
    _, context = inputs(True)
    model = OllamaStructuredModel(profile_for("offline"), MockChatTransport(mode=mode))
    with pytest.raises(InferenceError, match=code):
        model.complete(payload(context), max_output_tokens=65536, timeout_seconds=1)


def test_retry_is_bounded_and_failed_attempt_reservations_are_kept():
    _, context = inputs()
    transport = MockChatTransport(mode="invalid_then_valid")
    model = OllamaStructuredModel(profile_for("offline"), transport)
    adapter = BudgetedModelAdapter(model, mock_model_limits())
    assert adapter.propose(context)["proposal"]
    assert transport.calls == adapter.calls == 2
    assert adapter.reserved_tokens > 2 * 65536
    transport = MockChatTransport(mode="invalid_json")
    adapter = BudgetedModelAdapter(
        OllamaStructuredModel(profile_for("offline"), transport), mock_model_limits()
    )
    with pytest.raises(ValueError, match="ATTEMPTS_EXHAUSTED"):
        adapter.propose(context)
    assert transport.calls == 2


@pytest.mark.parametrize(
    "schema",
    [
        {"$ref": "https://invalid.example/schema"},
        {"type": "object", "properties": {}, "required": [], "additionalProperties": True},
        {"type": "string", "pattern": "(a+)+"},
        {"type": "string", "minimum": 0},
        {"type": "array", "items": {"type": "string"}, "maxItems": 0.5},
        {"type": "string", "minLength": 2, "maxLength": 1},
        {"anyOf": []},
    ],
)
def test_unsupported_schema_stops_before_transport(schema):
    with pytest.raises(InferenceError):
        check_schema(schema)


def test_schema_cycle_type_strictness_and_unknown():
    cyclic = {"type": "array"}
    cyclic["items"] = cyclic
    with pytest.raises(InferenceError, match="SCHEMA_LIMIT"):
        check_schema(cyclic)
    for value, schema in [
        (True, {"type": "integer"}),
        (0, {"type": "null"}),
        (0, {"type": "string", "enum": ["UNKNOWN"]}),
    ]:
        with pytest.raises(InferenceError, match="SCHEMA_OUTPUT"):
            validate_schema(value, schema)


def test_broker_reserves_once_for_duplicate_generation_and_conflicts():
    _, context = inputs()
    broker = InferenceBroker()
    count_request = {"id": "count1", "op": "count", "payload": payload(context)}
    assert broker.handle(count_request)["ok"]
    request = {
        "id": "generate1",
        "op": "generate",
        "ticket": "count1",
        "payload": payload(context),
        "max_output_tokens": 65536,
    }
    first = broker.handle(request)
    assert first["ok"] and broker.handle(request) == first
    assert broker.model.transport.calls == 1 and broker.generations == 1
    assert broker.handle({**request, "max_output_tokens": 200})["error"] == "REQUEST_ID_CONFLICT"
    assert broker.handle({**request, "id": "generate2"})["error"] == "COUNT_TICKET_USED"
    stats = verify_broker_records(broker.records)
    assert stats["generations"] == 1 and stats["reserved_tokens"] == broker.tokens


@pytest.mark.parametrize(
    "limits,code",
    [
        (BrokerLimits(input_tokens=1), "BROKER_INPUT_LIMIT"),
        (BrokerLimits(output_tokens=1), "BROKER_OUTPUT_LIMIT"),
        (BrokerLimits(total_tokens=1), "BROKER_TOTAL_LIMIT"),
        (BrokerLimits(cost_microusd=1), "BROKER_TOTAL_LIMIT"),
    ],
)
def test_broker_budget_prevents_generation(limits, code):
    _, context = inputs()
    broker = InferenceBroker(limits=limits)
    count = broker.handle({"id": "c", "op": "count", "payload": payload(context)})
    response = (
        count
        if not count["ok"]
        else broker.handle(
            {
                "id": "g",
                "op": "generate",
                "ticket": "c",
                "payload": payload(context),
                "max_output_tokens": 65536,
            }
        )
    )
    assert response["error"] == code
    assert broker.model.transport.calls == 0 and broker.tokens == 0
    assert verify_broker_records(broker.records)["generations"] == 0


@pytest.mark.parametrize(
    "rpc_request",
    [
        {"id": "x", "op": "http", "url": "https://invalid.example"},
        {"id": "x", "op": "exec", "command": "must-not-run"},
        {"id": "x", "op": "count", "payload": "{}", "url": "http://127.0.0.1"},
    ],
)
def test_broker_has_no_arbitrary_url_or_command_rpc(rpc_request):
    broker = InferenceBroker()
    assert broker.handle(rpc_request)["error"] == "RPC_NOT_ALLOWED"
    assert broker.model.transport.calls == 0


def test_parent_environment_not_inherited_and_worker_socket_is_blocked(monkeypatch):
    monkeypatch.setenv("ONI_PRIVATE_TEST_CANARY", "not-a-real-secret")
    engine, _ = inputs()
    with BrokerPolicyHost("exploration", policy_fault="environment") as host:
        names = host.request("queries", engine.inputs())
        assert "ONI_PRIVATE_TEST_CANARY" not in names
        assert set(names) <= {
            "SYSTEMROOT",
            "WINDIR",
            "SYSTEMDRIVE",
            "TEMP",
            "TMP",
            "PATH",
            "LC_CTYPE",
        }
    with BrokerPolicyHost("exploration", policy_fault="network") as host:
        with pytest.raises(PolicyProcessError):
            host.queries(engine.inputs())
        assert host.errors == ["SOCKET_BLOCKED"]
        assert host.cleanup_verified


@pytest.mark.parametrize("mode", ["hang", "exit", "secret", "oversize_usage"])
def test_ipc_failures_close_both_workers_and_journal_unknown_usage(mode):
    engine, context = inputs()
    host = BrokerPolicyHost(mode=mode, budget=ProcessBudget(call_seconds=0.3))
    directory = Path(host.directory.name)
    processes = [w.process for w in host.workers]
    with pytest.raises(PolicyProcessError):
        host.propose(context)
    assert host.cleanup_verified and not directory.exists()
    assert all(p.poll() is not None for p in processes)
    stats = verify_broker_records(host.audit)
    assert stats["generations"] == 1 and stats["usage_unknown_requests"] == 1
    assert "x" * 40 not in json.dumps(host.audit)


def test_ipc_roundtrip_and_existing_research_receipt(tmp_path):
    path = tmp_path / "episode.jsonl"
    hosts = []

    def factory(*args):
        host = BrokerPolicyHost(*args)
        hosts.append(host)
        return host

    summary = run_research_episode(
        load_fixture("normal"),
        "model-mock",
        0,
        path,
        episode_id="b" * 32,
        config=EpisodeConfig(max_steps=3),
        budget=ProcessBudget(call_seconds=5),
        factory=factory,
    )
    assert summary["metrics"]["validity"]["attempts"] == 3
    assert replay_research(path)["verified"]
    assert verify_broker_records(hosts[0].audit)["generations"] == 3


@pytest.mark.parametrize(
    "value",
    [
        {"api_key": "UNKNOWN"},
        {"nested": {"password": "no"}},
        {"value": "sk-proj-" + "x" * 40},
        {"value": "C:" + chr(92) + chr(92).join(["Users", "test-only", "file"])},
        {"value": "https://name:password@example.invalid"},
    ],
)
def test_sensitive_frames_are_rejected(value):
    with pytest.raises(InferenceError, match="SECRET_OR_PRIVATE_DATA"):
        safe_json(value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("prompt_eval_count", True),
        ("eval_count", -1),
        ("model", "different-model"),
    ],
)
def test_usage_and_model_identity_are_not_coerced(field, value):
    _, context = inputs()
    model = OllamaStructuredModel(profile_for("offline"), MockChatTransport())
    body = payload(context)
    raw = model.transport(model.request(body, 65536), 1)
    raw[field] = value
    with pytest.raises(InferenceError):
        model.parse_response(body, raw, 65536)


@pytest.mark.parametrize("seconds", [0, -1, float("nan"), True])
def test_invalid_adapter_deadline_does_not_invoke_transport(seconds):
    _, context = inputs()
    transport = MockChatTransport()
    with pytest.raises(InferenceError, match="MODEL_DEADLINE"):
        OllamaStructuredModel(profile_for("offline"), transport).complete(
            payload(context), max_output_tokens=65536, timeout_seconds=seconds
        )
    assert transport.calls == 0


@pytest.mark.parametrize("mutation", ["reservation", "usage", "reply"])
def test_broker_audit_rejects_usage_budget_and_reply_tampering(mutation):
    _, context = inputs()
    broker = InferenceBroker()
    broker.handle({"id": "c", "op": "count", "payload": payload(context)})
    broker.handle(
        {
            "id": "g",
            "op": "generate",
            "ticket": "c",
            "payload": payload(context),
            "max_output_tokens": 65536,
        }
    )
    records = json.loads(json.dumps(broker.records))
    if mutation == "reservation":
        records[2]["cost_microusd"] -= 1
    elif mutation == "usage":
        records[3]["raw"]["eval_count"] += 1
    else:
        records[3]["reply"]["text"] = "{}"
    with pytest.raises(InferenceError):
        verify_broker_records(records)


def test_ipc_connection_failure_retries_are_reserved_and_unknown_counter_stops():
    _, context = inputs()
    with BrokerPolicyHost(mode="disconnect") as host, pytest.raises(PolicyProcessError):
        host.propose(context)
    stats = verify_broker_records(host.audit)
    assert stats["generations"] == stats["usage_unknown_requests"] == 2
    assert stats["reserved_tokens"] > 0 and stats["verified_output_tokens"] == 0
    with (
        BrokerPolicyHost(model_key="unconfigured-local") as host,
        pytest.raises(PolicyProcessError),
    ):
        host.propose(context)
    assert host.errors == ["EXACT_COUNTER_UNAVAILABLE"]
    assert verify_broker_records(host.audit)["generations"] == 0


@pytest.mark.parametrize("fault", ["exit", "hang"])
def test_policy_worker_abnormal_exit_stops_the_broker_without_generation(fault):
    engine, _ = inputs()
    host = BrokerPolicyHost(policy_fault=fault, budget=ProcessBudget(call_seconds=0.3))
    processes = [w.process for w in host.workers]
    with pytest.raises(PolicyProcessError):
        host.queries(engine.inputs())
    assert host.cleanup_verified and all(p.poll() is not None for p in processes)
    assert verify_broker_records(host.audit)["generations"] == 0


def test_transient_windows_sharing_failure_is_retried_within_deadline(tmp_path, monkeypatch):
    import oni_ai.inference_ipc as ipc
    from oni_ai.inference_ipc import atomic_json, read_frame, retry_permission

    target = tmp_path / "frame.json"
    original_replace = ipc.os.replace
    calls = []

    def temporarily_locked(*args):
        calls.append(1)
        if len(calls) == 1:
            raise PermissionError("synthetic lock")
        return original_replace(*args)

    monkeypatch.setattr(ipc.os, "replace", temporarily_locked)
    atomic_json(target, {"ok": True})
    assert len(calls) == 2 and read_frame(target) == {"ok": True}
    original_read = Path.read_text
    reads = []

    def temporarily_unreadable(path, *args, **kwargs):
        reads.append(1)
        if len(reads) < 3:
            raise PermissionError("synthetic lock")
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", temporarily_unreadable)
    assert read_frame(target) == {"ok": True} and len(reads) == 3

    def permanently_locked():
        raise PermissionError("sensitive error text is not exposed")

    with pytest.raises(InferenceError, match="IPC_IO_FAILURE"):
        retry_permission(permanently_locked, time.monotonic() + 0.02)
