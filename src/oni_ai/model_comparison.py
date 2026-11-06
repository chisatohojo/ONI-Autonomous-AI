"""Comparison plan/report v2: offline model IPC smoke experiments, separate from v1/B2."""

import csv
import io
from dataclasses import asdict, replace
from pathlib import Path

from oni_ai.benchmarks import sample_fixture
from oni_ai.comparison import distribution, flatten_metrics, source_manifest, write_json
from oni_ai.contracts import strict_json
from oni_ai.episode_knowledge import database_snapshot, parse_queries, restore_snapshot
from oni_ai.episodes import MAX_LOG_BYTES, EpisodeConfig, EpisodeEngine, digest
from oni_ai.evaluation import _canonical
from oni_ai.inference_broker import BrokerLimits, verify_broker_records
from oni_ai.inference_contracts import InferenceError, context_from_dict, safe_json
from oni_ai.inference_ipc import BrokerPolicyHost, mock_model_limits
from oni_ai.model_adapter import ModelLimits
from oni_ai.policy_process import PolicyProcessError, ProcessBudget
from oni_ai.research import advance_event, replay_research, run_research_episode

V2_POLICIES = ["exploration", "lookahead", "model-mock"]
MOCK_GROUPS = {"mock-development": [4001, 4003], "mock-validation": [5003, 5009]}
B2_CONDITIONS = {
    "status": "DESIGN_ONLY_NEVER_EXECUTED_IN_B1",
    "development_seeds": [1103, 1201, 1301, 1409],
    "heldout_seeds": [2101, 2203, 2309, 2411, 2503, 2609, 2707, 2801],
    "development_conditions": "Single blockage, known research; observed water demand varied",
    "heldout_conditions": "Simultaneous water/research UNKNOWN, multiple blockages and new "
    "demand/research combinations; preregister exact ranges before B2",
}


def read_bounded(path):
    path = Path(path)
    if path.stat().st_size > MAX_LOG_BYTES:
        raise InferenceError("ARTIFACT_LIMIT")
    return strict_json(path.read_text("utf-8"))


def prepare_model_comparison(directory, db_path=None, *, max_steps=5):
    config = EpisodeConfig(max_steps=max_steps, memory_limit=2)
    plan = {
        "version": "comparison-plan/2",
        "model_key": "offline",
        "mode": "OFFLINE_MOCK_ONLY",
        "groups": MOCK_GROUPS,
        "policy_seeds": [0, 1],
        "policies": V2_POLICIES,
        "episode": asdict(config),
        "process": asdict(ProcessBudget(call_seconds=5)),
        "model": asdict(mock_model_limits()),
        "broker": asdict(BrokerLimits()),
        "run_budget": {"tokens": 10_000_000, "cost_microusd": 100_000_000},
        "snapshot": [asdict(e) for e in database_snapshot(db_path)],
        "sources": source_manifest(),
        "b2_conditions": B2_CONDITIONS,
    }
    plan["plan_digest"] = digest(plan)
    directory = Path(directory)
    directory.mkdir()
    write_json(directory / "plan.json", plan)
    return {"plan": str(directory / "plan.json"), "plan_digest": plan["plan_digest"]}


def read_model_plan(path, current=True):
    try:
        plan = read_bounded(path)
        if (
            plan["version"] != "comparison-plan/2"
            or plan["model_key"] != "offline"
            or plan["mode"] != "OFFLINE_MOCK_ONLY"
            or plan["plan_digest"] != digest({k: v for k, v in plan.items() if k != "plan_digest"})
            or plan["groups"] != MOCK_GROUPS
            or plan["policies"] != V2_POLICIES
            or plan["policy_seeds"] != [0, 1]
            or plan["b2_conditions"] != B2_CONDITIONS
        ):
            raise InferenceError("V2_PLAN_MISMATCH")
        EpisodeConfig(**plan["episode"])
        ProcessBudget(**plan["process"])
        ModelLimits(**plan["model"])
        BrokerLimits(**plan["broker"])
        restore_snapshot(plan["snapshot"])
        if set(plan["run_budget"]) != {"tokens", "cost_microusd"} or any(
            type(v) is not int or not 1 <= v <= 100_000_000 for v in plan["run_budget"].values()
        ):
            raise InferenceError("V2_RUN_BUDGET")
        if current and plan["sources"] != source_manifest():
            raise InferenceError("V2_SOURCE_FREEZE_CHANGED")
        return plan
    except (KeyError, TypeError, AttributeError) as error:
        raise InferenceError("INVALID_V2_PLAN") from error


def v2_aggregate(rows):
    output = {}
    for policy in V2_POLICIES:
        subset = [r for r in rows if r["policy"] == policy]
        metrics = [flatten_metrics(r["metrics"]) for r in subset]
        keys = sorted({k for m in metrics for k in m})
        output[policy] = {
            "episodes": len(subset),
            "distributions": {k: distribution([m[k] for m in metrics]) for k in keys},
            "inference": {
                k: sum(r["inference"][k] for r in subset)
                for k in (
                    "reserved_tokens",
                    "reserved_cost_microusd",
                    "generations",
                    "usage_unknown_requests",
                )
            },
            "stop_reasons": {
                reason: sum(r["stop_reason"] == reason for r in subset)
                for reason in sorted({r["stop_reason"] for r in subset})
            },
        }
    return output


def v2_markdown(report):
    lines = [
        "# 比較v2：offline mock接続検証",
        "",
        f"group: {report['group']}",
        f"plan: `{report['plan_digest']}`",
        "",
        "モデル推論の実測や判断性能比較ではありません。"
        "model-mockは探索Policyを返すtest doubleです。",
        "",
        "| Policy | episodes | 生成要求 | 予約mock tokens | usage未検証 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name, row in report["aggregates"].items():
        stats = row["inference"]
        lines.append(
            f"| {name} | {row['episodes']} | {stats['generations']} | "
            f"{stats['reserved_tokens']} | {stats['usage_unknown_requests']} |"
        )
    return "\n".join(lines) + "\n"


def v2_csv(report):
    rows = [
        {
            "policy": r["policy"],
            "seed": r["environment_seed"],
            "policy_seed": r["policy_seed"],
            "stop_reason": r["stop_reason"],
            **flatten_metrics(r["metrics"]),
            **{f"inference.{k}": v for k, v in r["inference"].items() if k != "verified"},
        }
        for r in report["rows"]
    ]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=sorted(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def opening_budget(plan, parent, group):
    tokens, cost = plan["run_budget"]["tokens"], plan["run_budget"]["cost_microusd"]
    if group == "mock-validation":
        previous = parent / "mock-development" / "report.json"
        verify_model_comparison(previous)
        if read_bounded(parent / "freeze.json") != {
            "plan_digest": plan["plan_digest"],
            "development_digest": digest(read_bounded(previous)),
        }:
            raise InferenceError("V2_DEVELOPMENT_FREEZE_MISMATCH")
        for row in read_bounded(previous)["rows"]:
            tokens -= row["inference"]["reserved_tokens"]
            cost -= row["inference"]["reserved_cost_microusd"]
    return tokens, cost


def run_model_comparison(plan_path, group):
    path = Path(plan_path)
    plan = read_model_plan(path)
    if group not in MOCK_GROUPS:
        raise InferenceError("B2_EXECUTION_NOT_AVAILABLE")
    if group == "mock-validation":
        frozen = read_bounded(path.parent / "freeze.json")
        if frozen != {
            "plan_digest": plan["plan_digest"],
            "development_digest": digest(
                read_bounded(path.parent / "mock-development" / "report.json")
            ),
        }:
            raise InferenceError("V2_DEVELOPMENT_FREEZE_MISMATCH")
    directory = path.parent / group
    directory.mkdir()
    remaining_tokens, remaining_cost = opening_budget(plan, path.parent, group)
    rows = []
    for seed in plan["groups"][group]:
        fixture = sample_fixture(
            "development" if group == "mock-development" else "evaluation", seed
        )
        for policy_seed in plan["policy_seeds"]:
            episode_id = digest({"fixture": fixture, "policy_seed": policy_seed, "version": 2})[:32]
            for policy in plan["policies"]:
                hosts = []

                def factory(
                    name,
                    selected_seed,
                    process,
                    tokens=remaining_tokens,
                    cost=remaining_cost,
                    created=hosts,
                ):
                    if name == "model-mock" and (tokens < 1 or cost < 1):
                        raise PolicyProcessError("CALL_BUDGET")
                    limits = BrokerLimits(**plan["broker"])
                    if name == "model-mock":
                        limits = replace(
                            limits,
                            total_tokens=min(limits.total_tokens, tokens),
                            cost_microusd=min(limits.cost_microusd, cost),
                        )
                    host = BrokerPolicyHost(
                        name,
                        selected_seed,
                        process,
                        broker_limits=limits,
                        model_limits=ModelLimits(**plan["model"]),
                    )
                    created.append(host)
                    return host

                stem = f"{seed}-{policy_seed}-{policy}"
                receipt = directory / f"{stem}.jsonl"
                summary = run_research_episode(
                    fixture,
                    policy,
                    policy_seed,
                    receipt,
                    episode_id=episode_id,
                    config=EpisodeConfig(**plan["episode"]),
                    budget=ProcessBudget(**plan["process"]),
                    snapshot=restore_snapshot(plan["snapshot"]),
                    factory=factory,
                    metadata={
                        "plan_digest": plan["plan_digest"],
                        "group": group,
                        "environment_seed": seed,
                        "policy_seed": policy_seed,
                    },
                )
                sidecar = {
                    "version": "model-audit/1",
                    "receipt_digest": digest(receipt.read_text("utf-8")),
                    "model_limits": plan["model"],
                    "broker_records": hosts[0].audit if hosts else [],
                    "host_errors": hosts[0].errors if hosts else ["RUN_BUDGET_EXHAUSTED"],
                    "cleanup_verified": not hosts or hosts[0].cleanup_verified,
                }
                safe_json(sidecar)
                sidecar["content_digest"] = digest(sidecar)
                write_json(directory / f"{stem}.audit.json", sidecar)
                stats = verify_model_episode(receipt, directory / f"{stem}.audit.json")
                remaining_tokens -= stats["reserved_tokens"]
                remaining_cost -= stats["reserved_cost_microusd"]
                rows.append(
                    {
                        "policy": policy,
                        "environment_seed": seed,
                        "policy_seed": policy_seed,
                        "receipt": receipt.name,
                        "stop_reason": summary["stop_reason"],
                        "metrics": summary["metrics"],
                        "inference": stats,
                    }
                )
    report = {
        "version": "comparison-report/2",
        "mode": "OFFLINE_MOCK_ONLY",
        "group": group,
        "plan_digest": plan["plan_digest"],
        "rows": rows,
        "aggregates": v2_aggregate(rows),
        "budget_remaining": {"tokens": remaining_tokens, "cost_microusd": remaining_cost},
    }
    write_json(directory / "report.json", report)
    with (directory / "summary.md").open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(v2_markdown(report))
    with (directory / "metrics.csv").open("x", encoding="utf-8", newline="") as stream:
        stream.write(v2_csv(report))
    return verify_model_comparison(directory / "report.json")


def verify_model_episode(receipt_path, audit_path):
    summary = replay_research(receipt_path)
    sidecar = read_bounded(audit_path)
    if (
        sidecar["version"] != "model-audit/1"
        or sidecar["cleanup_verified"] is not True
        or sidecar["content_digest"]
        != digest({k: v for k, v in sidecar.items() if k != "content_digest"})
        or sidecar["receipt_digest"] != digest(Path(receipt_path).read_text("utf-8"))
    ):
        raise InferenceError("MODEL_SIDECAR_MISMATCH")
    records = [strict_json(line) for line in Path(receipt_path).read_text("utf-8").splitlines()]
    header = records[0]
    model_records = sidecar["broker_records"]
    limits = ModelLimits(**sidecar["model_limits"])
    if header["policy"]["name"] != "model-mock":
        if model_records:
            raise InferenceError("UNEXPECTED_MODEL_AUDIT")
        return {
            "verified": True,
            "reserved_tokens": 0,
            "reserved_cost_microusd": 0,
            "generations": 0,
            "usage_unknown_requests": 0,
            "incomplete_requests": 0,
            "verified_input_tokens": 0,
            "verified_output_tokens": 0,
            "verified_cost_microusd": 0,
        }
    if not model_records:
        if sidecar["host_errors"] != ["RUN_BUDGET_EXHAUSTED"]:
            raise InferenceError("MISSING_MODEL_AUDIT")
        return {
            "verified": True,
            "reserved_tokens": 0,
            "reserved_cost_microusd": 0,
            "generations": 0,
            "usage_unknown_requests": 0,
            "incomplete_requests": 0,
            "verified_input_tokens": 0,
            "verified_output_tokens": 0,
            "verified_cost_microusd": 0,
        }
    stats = verify_broker_records(model_records)
    if (
        stats["reserved_tokens"] > limits.total_tokens
        or stats["reserved_cost_microusd"] > limits.cost_microusd
    ):
        raise InferenceError("MODEL_ADAPTER_AUDIT_BUDGET")
    engine = EpisodeEngine(
        header["fixture"],
        header["episode_id"],
        EpisodeConfig(**header["config"]),
        {"work": header["fixture"]["work_target"]},
        restore_snapshot(header["snapshot"]),
    )
    contexts = {}
    for step in records[1:-1]:
        queries = parse_queries(step["queries"]) if step["queries"] else ()
        if queries:
            ctx = engine.context(queries)
            contexts[digest(asdict(ctx))] = step
        fault = step["step"]["fault"]
        advance_event(
            engine,
            queries,
            step["response"],
            step["error"],
            step["stage"],
            fault if fault and fault["stage"] == "execute" else None,
        )
    tickets = {}
    attempts = {}
    used_steps = set()
    for record in model_records[1:]:
        if record["kind"] == "count":
            raw = strict_json(record["payload"])
            ctx = context_from_dict(raw["context"])
            key = digest(asdict(ctx))
            if key not in contexts:
                raise InferenceError("MODEL_CONTEXT_LINK_MISMATCH")
            attempts[key] = attempts.get(key, 0) + 1
            if attempts[key] > limits.attempts or record["count"] > limits.input_tokens:
                raise InferenceError("MODEL_ADAPTER_AUDIT_BUDGET")
            tickets[record["id"]] = key
        elif record["kind"] == "reserve":
            if record["max_output_tokens"] > limits.output_tokens:
                raise InferenceError("MODEL_ADAPTER_AUDIT_BUDGET")
            tickets[record["id"]] = tickets[record["ticket"]]
        elif record["kind"] == "result" and record["reply"]:
            step = contexts[tickets[record["id"]]]
            if step["response"] is not None:
                if _canonical(strict_json(record["reply"]["text"])) != _canonical(step["response"]):
                    raise InferenceError("MODEL_RESULT_LINK_MISMATCH")
                used_steps.add(step["step"]["attempt"])
            elif not step["error"]:
                raise InferenceError("UNUSED_MODEL_RESULT")
    if len(used_steps) != sum(step["response"] is not None for step in records[1:-1]):
        raise InferenceError("MISSING_LINKED_MODEL_RESULT")
    if not summary["verified"]:
        raise InferenceError("MODEL_REPLAY_FAILED")
    return stats


def freeze_model_comparison(plan_path):
    path = Path(plan_path)
    plan = read_model_plan(path)
    verify_model_comparison(path.parent / "mock-development" / "report.json")
    value = {
        "plan_digest": plan["plan_digest"],
        "development_digest": digest(
            read_bounded(path.parent / "mock-development" / "report.json")
        ),
    }
    write_json(path.parent / "freeze.json", value)
    return value


def verify_model_comparison(report_path):
    try:
        return _verify_model_comparison(Path(report_path))
    except (KeyError, TypeError, AttributeError, IndexError) as error:
        raise InferenceError("INVALID_MODEL_COMPARISON") from error


def _verify_model_comparison(path):
    report = read_bounded(path)
    plan = read_model_plan(path.parent.parent / "plan.json", current=False)
    group = report["group"]
    if (
        report["version"] != "comparison-report/2"
        or report["mode"] != "OFFLINE_MOCK_ONLY"
        or group not in MOCK_GROUPS
        or report["plan_digest"] != plan["plan_digest"]
    ):
        raise InferenceError("V2_REPORT_MISMATCH")
    expected_pairs = [
        (s, p, policy)
        for s in plan["groups"][group]
        for p in plan["policy_seeds"]
        for policy in plan["policies"]
    ]
    if len(report["rows"]) != len(expected_pairs):
        raise InferenceError("V2_REPORT_PAIR_MISMATCH")
    tokens, cost = opening_budget(plan, path.parent.parent, group)
    for row, (seed, policy_seed, policy) in zip(report["rows"], expected_pairs, strict=True):
        if (row["policy"], row["environment_seed"], row["policy_seed"]) != (
            policy,
            seed,
            policy_seed,
        ):
            raise InferenceError("V2_REPORT_PAIR_MISMATCH")
        stem = f"{seed}-{policy_seed}-{policy}"
        if row["receipt"] != stem + ".jsonl":
            raise InferenceError("V2_RECEIPT_PATH")
        receipt = path.parent / row["receipt"]
        stats = verify_model_episode(receipt, path.parent / f"{stem}.audit.json")
        header = strict_json(receipt.read_text("utf-8").splitlines()[0])
        fixture = sample_fixture(
            "development" if group == "mock-development" else "evaluation", seed
        )
        if (
            header["fixture"] != fixture
            or header["config"] != plan["episode"]
            or header["budget"] != plan["process"]
            or header["snapshot"] != plan["snapshot"]
            or header["policy"] != {"name": policy, "seed": policy_seed}
            or header["episode_id"]
            != digest({"fixture": fixture, "policy_seed": policy_seed, "version": 2})[:32]
            or header["metadata"]
            != {
                "plan_digest": plan["plan_digest"],
                "group": group,
                "environment_seed": seed,
                "policy_seed": policy_seed,
            }
        ):
            raise InferenceError("V2_CONDITIONS_MISMATCH")
        summary = replay_research(receipt)
        if (
            stats != row["inference"]
            or summary["metrics"] != row["metrics"]
            or summary["stop_reason"] != row["stop_reason"]
        ):
            raise InferenceError("V2_METRICS_MISMATCH")
        sidecar = read_bounded(path.parent / f"{stem}.audit.json")
        if sidecar["model_limits"] != plan["model"]:
            raise InferenceError("V2_MODEL_LIMIT_MISMATCH")
        if policy == "model-mock" and not sidecar["broker_records"] and min(tokens, cost) > 0:
            raise InferenceError("UNJUSTIFIED_MODEL_SKIP")
        if sidecar["broker_records"]:
            if sidecar["broker_records"][0]["model_key"] != plan["model_key"]:
                raise InferenceError("V2_MODEL_KEY_MISMATCH")
            expected_limits = {
                **plan["broker"],
                "total_tokens": min(plan["broker"]["total_tokens"], tokens),
                "cost_microusd": min(plan["broker"]["cost_microusd"], cost),
            }
            if sidecar["broker_records"][0]["limits"] != expected_limits:
                raise InferenceError("V2_BROKER_LIMIT_MISMATCH")
        tokens -= stats["reserved_tokens"]
        cost -= stats["reserved_cost_microusd"]
        if min(tokens, cost) < 0:
            raise InferenceError("V2_RUN_BUDGET")
    if (
        report["aggregates"] != v2_aggregate(report["rows"])
        or report["budget_remaining"] != {"tokens": tokens, "cost_microusd": cost}
        or (path.parent / "summary.md").read_text("utf-8") != v2_markdown(report)
    ):
        raise InferenceError("V2_AGGREGATE_MISMATCH")
    with (path.parent / "metrics.csv").open(encoding="utf-8", newline="") as stream:
        if stream.read() != v2_csv(report):
            raise InferenceError("V2_CSV_MISMATCH")
    return {
        "verified": True,
        "version": 2,
        "episodes": len(expected_pairs),
        "mock_generations": sum(r["inference"]["generations"] for r in report["rows"]),
        "reserved_tokens": plan["run_budget"]["tokens"] - tokens,
        "scope": "MOCK_ONLY_NO_MODEL_PERFORMANCE_CLAIM",
    }
