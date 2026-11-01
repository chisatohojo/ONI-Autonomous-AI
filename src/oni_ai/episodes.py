"""Autonomous synthetic episodes: retrieval, proposal checks, execution, metrics and memory."""

import hashlib
import re
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from uuid import uuid4

from oni_ai.contracts import PROVENANCE, Decision, finite_nonnegative, strict_json
from oni_ai.episode_knowledge import (
    EpisodeKnowledge,
    Evidence,
    KnowledgeQuery,
    database_snapshot,
    parse_queries,
    query_records,
    required_unknowns,
    restore_snapshot,
)
from oni_ai.evaluation import _canonical
from oni_ai.policy import MemoryEntry, Policy, PolicyContext, PolicyInput
from oni_ai.simulation import SyntheticEnvironment, validate_fixture

ENGINE_VERSION = "synthetic-episode-engine/1"
MAX_LOG_BYTES = 20_000_000


def digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EpisodeConfig:
    max_steps: int = 30
    no_progress_limit: int = 12
    repeat_limit: int = 6
    error_limit: int = 4
    memory_limit: int = 16

    def __post_init__(self):
        for value in asdict(self).values():
            if type(value) is not int or not 1 <= value <= 200:
                raise ValueError("Episode limits must be integers in 1..200")


def anonymous_fixture(source: dict, episode_id: str) -> dict:
    validate_fixture(source)
    if not isinstance(episode_id, str) or not re.fullmatch(r"[0-9a-f]{32}", episode_id):
        raise ValueError("episode_id must be an opaque 32-character hex ID")
    fixture = deepcopy(source)
    fixture["fixture_id"] = episode_id
    fixture["description"] = "Anonymous synthetic episode"
    fixture["processes"] = {
        f"p{index:04d}": value
        for index, (_, value) in enumerate(sorted(fixture["processes"].items()))
    }
    return fixture


def public_observation(environment: SyntheticEnvironment) -> dict:
    observation = environment.observe()
    del observation["fixture_id"]
    observation["schema_version"] = 2
    observation["observation_digest"] = digest(observation)
    return observation


def _goal_state(observation: dict, objective: dict) -> bool | None:
    unknown = False
    for resource, target in objective.items():
        value = observation["resources"][resource]
        if value is None:
            unknown = True
        elif value < target:
            return False
    return None if unknown else True


def _observation_reference(reference: str, observation: dict) -> bool:
    if not reference.startswith("obs:/"):
        return False
    current = observation
    try:
        for part in reference[5:].split("/"):
            current = current[part.replace("~1", "/").replace("~0", "~")]
    except (KeyError, TypeError):
        return False
    return current is not None and not isinstance(current, (dict, list))


def validate_proposal(
    proposal: object, observation: dict, evidence: tuple[Evidence, ...], seen_ids: set[str]
) -> tuple[Decision | None, list[str]]:
    try:
        raw = strict_json(proposal) if isinstance(proposal, str) else proposal
        if (
            not isinstance(raw, dict)
            or set(raw) != {"schema_version", "observation_digest", "decision"}
            or type(raw["schema_version"]) is not int
            or raw["schema_version"] != 1
        ):
            raise ValueError("Unsupported proposal schema")
        decision = Decision.from_dict(raw["decision"])
    except (TypeError, KeyError, ValueError, OverflowError):
        return None, ["INVALID_DECISION"]
    failures = []
    action = decision.action
    if raw["observation_digest"] != observation["observation_digest"]:
        failures.append("STALE_OBSERVATION_DIGEST")
    if action.context_id != observation["context_id"]:
        failures.append("CONTEXT_MISMATCH")
    if action.expected_tick != observation["tick"]:
        failures.append("STALE_OBSERVATION")
    if action.action_id in seen_ids:
        failures.append("DUPLICATE_DECISION_ID")
    if action.dry_run:
        failures.append("PREVIEW_ONLY_ACTION")
    if action.kind != "wait" and action.target not in observation["processes"]:
        failures.append("UNKNOWN_TARGET")
    available = {item.evidence_id: item for item in evidence}
    required = {"model:actions"}
    if action.target in observation["processes"]:
        required.add(f"model:process:{action.target}")
    if not required <= set(decision.evidence_refs):
        failures.append("MISSING_ACTION_EVIDENCE")
    for reference in decision.evidence_refs:
        if reference.startswith("obs:"):
            if not _observation_reference(reference, observation):
                failures.append("MISSING_OR_UNKNOWN_OBSERVATION_EVIDENCE")
        elif reference not in available:
            failures.append("EVIDENCE_NOT_RETRIEVED")
        elif not available[reference].applicable:
            failures.append("EVIDENCE_SCOPE_MISMATCH")
    if not set(required_unknowns(observation, evidence)) <= set(decision.unknowns):
        failures.append("UNDECLARED_UNKNOWNS")
    return decision, sorted(set(failures))


class EpisodeEngine:
    """Policy-independent state machine shared by execution and replay."""

    def __init__(
        self,
        source: dict,
        episode_id: str,
        config: EpisodeConfig,
        objective: dict,
        snapshot: tuple[Evidence, ...] = (),
    ):
        self.fixture = anonymous_fixture(source, episode_id)
        if (
            not isinstance(objective, dict)
            or not objective
            or set(objective) - source["resources"].keys()
        ):
            raise ValueError("Objective must contain known synthetic resource targets")
        for target in objective.values():
            finite_nonnegative(target)
        self.objective, self.config, self.episode_id = deepcopy(objective), config, episode_id
        self.environment = SyntheticEnvironment(self.fixture)
        self.knowledge = EpisodeKnowledge(self.fixture, self.objective, snapshot)
        self.initial = public_observation(self.environment)
        self.best = {key: self.initial["resources"][key] for key in objective}
        self.memory: list[MemoryEntry] = []
        self.seen_ids: set[str] = set()
        self.applied = self.rejected = self.error_streak = self.no_progress = 0
        self.repeat_count = 0
        self.last_intent: str | None = None
        self.unmet_critical = self.unknown_critical = self.known_critical = 0
        goal = _goal_state(self.initial, self.objective)
        self.stop_reason = (
            "GOAL_ALREADY_MET" if goal is True else ("UNKNOWN_GOAL" if goal is None else None)
        )

    def inputs(self) -> PolicyInput:
        return PolicyInput(
            _canonical(public_observation(self.environment)),
            _canonical(self.objective),
            tuple(self.memory[-self.config.memory_limit :]),
        )

    def context(self, queries: tuple[KnowledgeQuery, ...]) -> PolicyContext:
        inputs = self.inputs()
        evidence = self.knowledge.search(queries)
        return PolicyContext(
            inputs, evidence, required_unknowns(strict_json(inputs.observation_json), evidence)
        )

    def advance(
        self, queries: tuple[KnowledgeQuery, ...], proposal: object, fault: dict | None = None
    ) -> dict:
        if self.stop_reason:
            raise ValueError("Episode is already terminated")
        if fault is not None and (
            not isinstance(fault, dict)
            or set(fault) != {"stage", "error_type"}
            or fault["stage"] not in {"queries", "propose", "serialize", "execute", "budget"}
            or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", fault["error_type"])
        ):
            raise ValueError("Invalid recorded fault event")
        before = public_observation(self.environment)
        evidence = (
            ()
            if fault and fault["stage"] in {"queries", "budget"}
            else self.knowledge.search(queries)
        )
        decision = None
        failures = []
        repeated = False
        result = None
        if fault and fault["stage"] != "execute":
            failures = ["LOG_SIZE_LIMIT"] if fault["stage"] == "budget" else ["POLICY_ERROR"]
        else:
            decision, failures = validate_proposal(proposal, before, evidence, self.seen_ids)
            if decision is not None:
                self.seen_ids.add(decision.action.action_id)
                action = decision.action
                intent = _canonical(
                    {
                        k: v
                        for k, v in asdict(action).items()
                        if k not in {"action_id", "context_id", "expected_tick"}
                    }
                )
                self.repeat_count = self.repeat_count + 1 if intent == self.last_intent else 1
                self.last_intent = intent
                repeated = self.repeat_count >= self.config.repeat_limit
                if repeated:
                    failures.append("REPEATED_ACTION_LIMIT")
                if not failures:
                    try:
                        preview = deepcopy(self.environment).step(replace(action, dry_run=True))
                    except Exception as error:
                        fault = {"stage": "execute", "error_type": type(error).__name__}
                        failures = ["EXECUTION_ERROR"]
                        preview = None
                    if preview is not None and preview["failures"] == ["MODEL_NUMERIC_LIMIT"]:
                        failures.append("MODEL_NUMERIC_LIMIT")
                    elif preview is not None and action.target is not None:
                        active = preview.get("preview", before)["processes"][action.target][
                            "enabled"
                        ]
                        if active:
                            failures.extend(
                                reason
                                for reason in preview["failures"]
                                if reason.endswith(f":{action.target}")
                            )
                if not failures:
                    if fault:
                        failures = ["EXECUTION_ERROR"]
                    else:
                        candidate = deepcopy(self.environment)
                        try:
                            result = candidate.step(action)
                        except Exception as error:
                            fault = {"stage": "execute", "error_type": type(error).__name__}
                            failures = ["EXECUTION_ERROR"]
                        else:
                            if result["status"] != "APPLIED":
                                failures = list(result["failures"]) or ["EXECUTION_REJECTED"]
                            else:
                                self.environment = candidate
        after = public_observation(self.environment)
        if failures:
            self.rejected += 1
            self.error_streak += 1
            status = "REJECTED"
        else:
            self.applied += 1
            self.error_streak = 0
            status = "APPLIED"
            critical = {r for r in ("oxygen", "food") if self.fixture["demand"].get(r, 0) > 0}
            outcomes = result["failures"]
            self.unmet_critical += int(any(f"UNMET_DEMAND:{r}" in outcomes for r in critical))
            unknown = any(after["resources"][r] is None for r in critical)
            self.unknown_critical += int(unknown)
            self.known_critical += int(not unknown)
        progress = False
        for resource in self.objective:
            value, best = after["resources"][resource], self.best[resource]
            if value is not None and (best is None or value > best):
                self.best[resource] = value
                progress = True
        self.no_progress = 0 if progress else self.no_progress + 1
        combined = sorted(set(failures if failures else result["failures"]))
        metrics = self.metrics()
        record = {
            "record_type": "episode_step",
            "attempt": len(self.memory),
            "queries": query_records(queries),
            "knowledge": [asdict(item) for item in evidence],
            "proposal": proposal,
            "decision": decision.as_dict() if decision else None,
            "fault": fault,
            "status": status,
            "failures": combined,
            "before": before,
            "after": after,
            "metrics": metrics,
        }
        self.memory.append(
            MemoryEntry(
                len(self.memory),
                _canonical(record["decision"]) if decision else None,
                _canonical(before),
                _canonical(after),
                tuple(combined),
                _canonical(metrics),
            )
        )
        if fault and fault["stage"] == "budget":
            self.stop_reason = "LOG_SIZE_LIMIT"
        elif fault and fault["stage"] == "execute":
            self.stop_reason = "EXECUTION_ERROR"
        elif repeated:
            self.stop_reason = "REPEATED_ACTION"
        elif _goal_state(after, self.objective) is True:
            self.stop_reason = "GOAL_REACHED"
        elif self.error_streak >= self.config.error_limit:
            self.stop_reason = "ERROR_LIMIT"
        elif self.no_progress >= self.config.no_progress_limit:
            self.stop_reason = "NO_PROGRESS"
        elif len(self.memory) >= self.config.max_steps:
            self.stop_reason = "MAX_STEPS"
        record["stop_reason"] = self.stop_reason
        return record

    def metrics(self) -> dict:
        observation = public_observation(self.environment)
        attempts = self.applied + self.rejected
        survival = (
            False
            if self.unmet_critical
            else (None if self.unknown_critical or not self.applied else True)
        )
        progress = {}
        for resource in ("work", "research"):
            old, new = self.initial["resources"][resource], observation["resources"][resource]
            progress[f"{resource}_delta"] = None if old is None or new is None else new - old
        return {
            "survival": {
                "synthetic_demand_proxy": survival,
                "attempts_with_unmet_critical_demand": self.unmet_critical,
                "attempts_with_unknown_critical_demand": self.unknown_critical,
            },
            "resources": observation["resources"],
            "progress": {**progress, "goal_met": _goal_state(observation, self.objective)},
            "validity": {
                "attempts": attempts,
                "applied": self.applied,
                "rejected": self.rejected,
                "invalid_action_rate": self.rejected / attempts if attempts else None,
            },
        }

    def summary(self) -> dict:
        return {
            "record_type": "episode_summary",
            "episode_id": self.episode_id,
            "stop_reason": self.stop_reason,
            "attempts": len(self.memory),
            "final_observation": public_observation(self.environment),
            "metrics": self.metrics(),
        }


def run_episode(
    fixture: dict,
    policy: Policy,
    log_path: Path,
    *,
    config: EpisodeConfig | None = None,
    objective: dict | None = None,
    db_path: Path | None = None,
    metadata: dict | None = None,
    episode_id: str | None = None,
) -> dict:
    config = EpisodeConfig() if config is None else config
    if not isinstance(config, EpisodeConfig):
        raise ValueError("Validated EpisodeConfig required")
    episode_id = uuid4().hex if episode_id is None else episode_id
    objective = {"work": fixture["work_target"]} if objective is None else objective
    snapshot = database_snapshot(db_path)
    engine = EpisodeEngine(fixture, episode_id, config, objective, snapshot)
    snapshot_records = [asdict(item) for item in snapshot]
    header = {
        "record_type": "episode_header",
        "schema_version": 1,
        "engine_version": ENGINE_VERSION,
        "provenance": PROVENANCE,
        "episode_id": episode_id,
        "source_fixture": fixture,
        "fixture_sha256": digest(fixture),
        "config": asdict(config),
        "objective": objective,
        "knowledge_snapshot": snapshot_records,
        "knowledge_sha256": digest(snapshot_records),
        "policy_name": policy.name,
        "metadata": metadata or {},
        "initial_observation": engine.initial,
    }
    header_text = _canonical(header)
    if len(header_text.encode("utf-8")) > MAX_LOG_BYTES // 2:
        raise ValueError("Episode header exceeds the receipt budget")
    with log_path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(header_text + "\n")
        while not engine.stop_reason:
            queries, proposal, fault = (), None, None
            try:
                queries = policy.queries(engine.inputs())
                context = engine.context(queries)
            except Exception as error:
                queries = ()
                fault = {"stage": "queries", "error_type": type(error).__name__}
            if fault is None:
                try:
                    proposal = policy.propose(context)
                except Exception as error:
                    fault = {"stage": "propose", "error_type": type(error).__name__}
                else:
                    try:
                        encoded = _canonical(proposal)
                        if len(encoded) > 65_536:
                            raise ValueError("Proposal exceeds 64K characters")
                        proposal = strict_json(encoded)
                    except (ValueError, TypeError, OverflowError, RecursionError) as error:
                        proposal = None
                        fault = {"stage": "serialize", "error_type": type(error).__name__}
            candidate = deepcopy(engine)
            record = candidate.advance(queries, proposal, fault)
            record_text = _canonical(record)
            if stream.tell() + len(record_text.encode("utf-8")) > MAX_LOG_BYTES * 3 // 4:
                record = engine.advance(
                    (), None, {"stage": "budget", "error_type": "ReceiptSizeLimit"}
                )
                record_text = _canonical(record)
            else:
                engine = candidate
            stream.write(record_text + "\n")
            stream.flush()
        summary = engine.summary()
        stream.write(_canonical(summary) + "\n")
    return summary


def replay_episode(path: Path) -> dict:
    if path.stat().st_size > MAX_LOG_BYTES:
        raise ValueError("Episode log exceeds 20MB")
    records = [strict_json(line) for line in path.read_text("utf-8").splitlines()]
    if not 2 <= len(records) <= 202 or not all(isinstance(r, dict) for r in records):
        raise ValueError("Incomplete or invalid episode receipt")
    try:
        header = records[0]
        if (
            header["record_type"] != "episode_header"
            or type(header["schema_version"]) is not int
            or header["schema_version"] != 1
            or header["engine_version"] != ENGINE_VERSION
            or header.get("provenance") != PROVENANCE
        ):
            raise ValueError("Unknown episode header")
        if (
            digest(header["source_fixture"]) != header["fixture_sha256"]
            or digest(header["knowledge_snapshot"]) != header["knowledge_sha256"]
        ):
            raise ValueError("Episode fixture/knowledge digest mismatch")
        engine = EpisodeEngine(
            header["source_fixture"],
            header["episode_id"],
            EpisodeConfig(**header["config"]),
            header["objective"],
            restore_snapshot(header["knowledge_snapshot"]),
        )
        if _canonical(engine.initial) != _canonical(header["initial_observation"]):
            raise ValueError("Initial episode observation mismatch")
        faults = 0
        for record in records[1:-1]:
            fault = record["fault"]
            queries = (
                ()
                if fault and fault["stage"] in {"queries", "budget"}
                else parse_queries(record["queries"])
            )
            expected = engine.advance(queries, record["proposal"], fault)
            if _canonical(expected) != _canonical(record):
                raise ValueError("Episode step failed replay validation")
            faults += int(fault is not None)
        if not engine.stop_reason or _canonical(engine.summary()) != _canonical(records[-1]):
            raise ValueError("Missing or mismatched episode termination")
    except (KeyError, TypeError, AttributeError, OverflowError) as error:
        raise ValueError("Malformed episode receipt") from error
    return {
        "verified": True,
        "policy_reexecuted": False,
        "recorded_fault_events": faults,
        **engine.summary(),
    }
