"""Versioned comparison receipts built around the unchanged Phase 2 EpisodeEngine."""

from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

from oni_ai.contracts import PROVENANCE, strict_json
from oni_ai.episode_knowledge import parse_queries, query_records, restore_snapshot
from oni_ai.episodes import MAX_LOG_BYTES, EpisodeConfig, EpisodeEngine, digest
from oni_ai.evaluation import _canonical
from oni_ai.policy_process import PolicyProcessError, ProcessBudget, ProcessPolicy
from oni_ai.research_boundary import validate_envelope
from oni_ai.research_policy import intent

RESEARCH_VERSION = "synthetic-policy-comparison/1"
ERROR_CODES = {
    "POLICY_TIMEOUT",
    "TIME_BUDGET",
    "CALL_BUDGET",
    "INPUT_BUDGET",
    "OUTPUT_BUDGET",
    "POLICY_EXCEPTION",
    "WORKER_PROTOCOL_ERROR",
    "WORKER_EXITED",
    "INVALID_QUERIES",
    "LOG_SIZE_LIMIT",
}


def advance_event(engine, queries, response, error=None, stage="propose", execution_fault=None):
    if error is not None and (error not in ERROR_CODES or stage not in {"queries", "propose"}):
        raise ValueError("Invalid recorded process event")
    before = engine.inputs()
    failures = []
    proposal = None
    if error:
        fault = {"stage": stage, "error_type": "RecordedPolicyError"}
        if error == "LOG_SIZE_LIMIT":
            fault = {"stage": "budget", "error_type": "ReceiptSizeLimit"}
        failures = [error]
    else:
        context = engine.context(queries)
        proposal, failures = validate_envelope(
            response, strict_json(before.observation_json), context.knowledge, engine.seen_ids
        )
        fault = execution_fault
        if fault is not None and fault.get("stage") != "execute":
            raise ValueError("Only execution faults can be replayed at the execution boundary")
    step = engine.advance(queries, proposal, fault)
    stop = error or engine.stop_reason
    return {
        "record_type": "research_step",
        "queries": query_records(queries),
        "response": response,
        "error": error,
        "stage": stage,
        "boundary_failures": failures,
        "step": step,
        "stop_reason": stop,
    }


def resource_consumption(fixture, steps):
    """Account actual synthetic process inputs + served demand; verify every recorded balance."""
    total = {key: 0 for key in fixture["resources"]}
    for step in steps:
        if step["status"] != "APPLIED":
            continue
        state = deepcopy(step["before"])
        action = step["decision"]["action"]
        if action["kind"] == "set_process":
            state["processes"][action["target"]]["enabled"] = action["enabled"]
        elif action["kind"] == "clear_blockage":
            state["processes"][action["target"]]["blocked"] = False
        for _ in range(action["ticks"]):
            resources = state["resources"]
            candidates = [
                p
                for p in state["processes"].values()
                if p["enabled"]
                and not p["blocked"]
                and (
                    not p["requires_research"]
                    or (
                        resources["research"] is not None
                        and resources["research"] >= p["requires_research"]
                    )
                )
                and all(resources[r] is not None for r in set(p["inputs"]) | set(p["outputs"]))
            ]
            scarce = {
                r
                for r in resources
                if resources[r] is not None
                and sum(p["inputs"].get(r, 0) for p in candidates) > resources[r]
            }
            active = [p for p in candidates if not scarce.intersection(p["inputs"])]
            for resource, value in resources.items():
                used = sum(p["inputs"].get(resource, 0) for p in active)
                produced = sum(p["outputs"].get(resource, 0) for p in active)
                demand = fixture["demand"].get(resource, 0)
                if value is None:
                    if demand:
                        total[resource] = None
                else:
                    available = value - used + produced
                    paid = min(available, demand)
                    if total[resource] is not None:
                        total[resource] += used + paid
                    resources[resource] = (
                        max(0, available - demand) if resource in fixture["demand"] else available
                    )
        if _canonical(state["resources"]) != _canonical(step["after"]["resources"]):
            raise ValueError("Resource consumption ledger does not balance")
    return total


def research_metrics(engine, records):
    initial = engine.initial["resources"]
    final = engine.summary()["final_observation"]["resources"]
    applied = [r for r in records if r["step"]["status"] == "APPLIED"]
    steps = [r["step"] for r in records]
    consumption = resource_consumption(engine.fixture, steps)
    signatures = [intent(s["decision"]["action"]) if s["decision"] else None for s in steps]
    changes = sum(a != b for a, b in zip(signatures, signatures[1:], strict=False) if a and b)
    rejected_followups = [
        (old, new)
        for old, new in zip(steps, steps[1:], strict=False)
        if old["status"] == "REJECTED"
    ]
    failure_followups = [
        (old, new) for old, new in zip(steps, steps[1:], strict=False) if old["failures"]
    ]
    flow = {}
    for resource in sorted(initial):
        known = initial[resource] is not None and final[resource] is not None
        drawdowns = [
            max(
                0,
                r["step"]["before"]["resources"][resource]
                - r["step"]["after"]["resources"][resource],
            )
            for r in applied
            if r["step"]["before"]["resources"][resource] is not None
            and r["step"]["after"]["resources"][resource] is not None
        ]
        flow[resource] = {
            "initial": initial[resource],
            "final": final[resource],
            "net_change": final[resource] - initial[resource] if known else None,
            "synthetic_consumption": consumption[resource],
            "observed_drawdown_proxy": sum(drawdowns) if known else None,
            "demand_requested": engine.fixture["demand"].get(resource, 0)
            * engine.environment.observe()["tick"],
        }
    return {
        **engine.metrics(),
        "resource_balance": flow,
        "execution": {
            "ticks": engine.environment.observe()["tick"],
            "stalled_applied_steps": sum(
                s["before"]["resources"]["work"] is not None
                and s["after"]["resources"]["work"] == s["before"]["resources"]["work"]
                for s in steps
                if s["status"] == "APPLIED"
            ),
            "failure_steps": sum(bool(s["failures"]) for s in steps),
        },
        "adaptation": {
            "failure_followups": len(failure_followups),
            "fewer_failure_reasons_next_step": sum(
                len(new["failures"]) < len(old["failures"]) for old, new in failure_followups
            ),
            "work_gains_after_failure": sum(
                new["before"]["resources"]["work"] is not None
                and new["after"]["resources"]["work"] is not None
                and new["after"]["resources"]["work"] > new["before"]["resources"]["work"]
                for _, new in failure_followups
            ),
            "intent_changes": changes,
            "rejected_followups": len(rejected_followups),
            "accepted_after_rejection": sum(
                b["status"] == "APPLIED" for _, b in rejected_followups
            ),
            "changed_after_rejection": sum(
                a["decision"] is not None
                and b["decision"] is not None
                and intent(a["decision"]["action"]) != intent(b["decision"]["action"])
                for a, b in rejected_followups
            ),
        },
        "uncertainty": {
            "initial_unknown_resources": sum(v is None for v in initial.values()),
            "final_unknown_resources": sum(v is None for v in final.values()),
            "undeclared_unknown_rejections": sum(
                "UNDECLARED_UNKNOWNS" in r["boundary_failures"] for r in records
            ),
            "claim_rejections": sum(
                any("CLAIM" in f for f in r["boundary_failures"]) for r in records
            ),
            "unknown_resource_attempts": sum(
                any(f.startswith("UNKNOWN_RESOURCE:") for f in s["failures"]) for s in steps
            ),
        },
    }


def _summary(engine, records, cleanup_verified):
    return {
        "record_type": "research_summary",
        "episode_id": engine.episode_id,
        "stop_reason": records[-1]["stop_reason"] if records else engine.stop_reason,
        "metrics": research_metrics(engine, records),
        "cleanup_verified": cleanup_verified,
        "scope": PROVENANCE,
    }


def run_research_episode(
    fixture,
    policy_name,
    seed,
    path,
    *,
    episode_id,
    config=None,
    budget=None,
    snapshot=(),
    metadata=None,
    factory=ProcessPolicy,
):
    config, budget = config or EpisodeConfig(), budget or ProcessBudget()
    engine = EpisodeEngine(fixture, episode_id, config, {"work": fixture["work_target"]}, snapshot)
    header = {
        "record_type": "research_header",
        "version": RESEARCH_VERSION,
        "provenance": PROVENANCE,
        "episode_id": episode_id,
        "fixture": fixture,
        "config": asdict(config),
        "budget": asdict(budget),
        "policy": {"name": policy_name, "seed": seed},
        "snapshot": [asdict(item) for item in snapshot],
        "metadata": metadata or {},
    }
    header["content_digest"] = digest(header)
    header_text = _canonical(header)
    if len(header_text.encode("utf-8")) > MAX_LOG_BYTES // 2:
        raise ValueError("Research header exceeds log budget")
    records, host = [], None
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(header_text + "\n")
        try:
            while not engine.stop_reason:
                queries, response, error, stage = (), None, None, "queries"
                try:
                    if host is None:
                        host = factory(policy_name, seed, budget)
                    queries = host.queries(engine.inputs())
                    context = engine.context(queries)
                    stage = "propose"
                    response = host.propose(context)
                except PolicyProcessError as failure:
                    error = failure.code
                except (TypeError, ValueError):
                    queries, error = (), "INVALID_QUERIES"
                candidate = deepcopy(engine)
                record = advance_event(candidate, queries, response, error, stage)
                encoded = _canonical(record)
                if stream.tell() + len(encoded.encode("utf-8")) > MAX_LOG_BYTES * 3 // 4:
                    record = advance_event(engine, (), None, "LOG_SIZE_LIMIT", "queries")
                    encoded = _canonical(record)
                else:
                    engine = candidate
                stream.write(encoded + "\n")
                stream.flush()
                records.append(record)
                if record["stop_reason"]:
                    break
        finally:
            if host is not None:
                host.close()
        summary = _summary(engine, records, host is None or host.cleanup_verified)
        stream.write(_canonical(summary) + "\n")
    return summary


def replay_research(path):
    path = Path(path)
    if path.stat().st_size > MAX_LOG_BYTES:
        raise ValueError("Research receipt exceeds log budget")
    records = [strict_json(line) for line in path.read_text("utf-8").splitlines()]
    if not 2 <= len(records) <= 202 or not all(isinstance(r, dict) for r in records):
        raise ValueError("Incomplete research receipt")
    try:
        header = dict(records[0])
        content_digest = header.pop("content_digest")
        if (
            digest(header) != content_digest
            or header["version"] != RESEARCH_VERSION
            or (header["record_type"] != "research_header" or header["provenance"] != PROVENANCE)
        ):
            raise ValueError("Research header mismatch")
        ProcessBudget(**header["budget"])
        engine = EpisodeEngine(
            header["fixture"],
            header["episode_id"],
            EpisodeConfig(**header["config"]),
            {"work": header["fixture"]["work_target"]},
            restore_snapshot(header["snapshot"]),
        )
        replayed = []
        for record in records[1:-1]:
            if replayed and replayed[-1]["stop_reason"]:
                raise ValueError("Unexpected record after termination")
            queries = parse_queries(record["queries"]) if record["queries"] else ()
            fault = record["step"]["fault"]
            expected = advance_event(
                engine,
                queries,
                record["response"],
                record["error"],
                record["stage"],
                fault if fault and fault["stage"] == "execute" else None,
            )
            if _canonical(expected) != _canonical(record):
                raise ValueError("Research step mismatch")
            replayed.append(expected)
        expected = _summary(engine, replayed, True)
        if not expected["stop_reason"] or _canonical(expected) != _canonical(records[-1]):
            raise ValueError("Research summary mismatch or incomplete log")
    except (KeyError, TypeError, AttributeError, IndexError, OverflowError) as error:
        raise ValueError("Malformed research receipt") from error
    return {
        "verified": True,
        "policy_reexecuted": False,
        "cleanup_is_recorded_attestation": True,
        **expected,
    }
