"""Exclusive JSONL receipts and deterministic replay of explicitly synthetic experiments."""

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from oni_ai.contracts import MODEL_VERSION, PROVENANCE, Decision, strict_json
from oni_ai.simulation import SyntheticEnvironment, validate_fixture


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def run_experiment(fixture: dict, decisions: list[Decision], log_path: Path) -> dict:
    if not isinstance(decisions, list) or not 1 <= len(decisions) <= 100:
        raise ValueError("Provide 1..100 explicit decisions; no policy is selected automatically")
    if not all(isinstance(decision, Decision) for decision in decisions):
        raise ValueError("Validated decisions required")
    validate_fixture(fixture)
    environment = SyntheticEnvironment(fixture)
    header = {
        "record_type": "header",
        "schema_version": 1,
        "provenance": PROVENANCE,
        "model_version": MODEL_VERSION,
        "fixture": fixture,
        "fixture_sha256": hashlib.sha256(_canonical(fixture).encode()).hexdigest(),
        "initial_observation": environment.observe(),
        "evidence_policy": "Caller-provided references; not automatically verified citations",
    }
    # No overwriting previous evidence. No network, implicit DB reads, or real game data.
    with log_path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(_canonical(header) + "\n")
        for sequence, decision in enumerate(decisions):
            result = environment.step(decision.action)
            record = {
                "record_type": "step",
                "sequence": sequence,
                "decision": asdict(decision),
                "result": result,
            }
            stream.write(_canonical(record) + "\n")
            stream.flush()
        summary = {
            "record_type": "summary",
            "steps": len(decisions),
            "final_observation": environment.observe(),
        }
        stream.write(_canonical(summary) + "\n")
    return summary


def replay_log(path: Path) -> dict:
    # Logs are local input, bounded before parsing; never execute code from a receipt.
    if path.stat().st_size > 20_000_000:
        raise ValueError("Experiment log is too large")
    records = [strict_json(line) for line in path.read_text("utf-8").splitlines()]
    if not 3 <= len(records) <= 102:
        raise ValueError("Incomplete or oversized receipt")
    if not all(isinstance(record, dict) for record in records):
        raise ValueError("Receipt records must be objects")
    header, summary = records[0], records[-1]
    if (
        header.get("record_type") != "header"
        or type(header.get("schema_version")) is not int
        or header["schema_version"] != 1
        or header.get("provenance") != PROVENANCE
        or header.get("model_version") != MODEL_VERSION
    ):
        raise ValueError("Unknown experiment header")
    if not {"fixture", "fixture_sha256", "initial_observation"} <= header.keys():
        raise ValueError("Incomplete experiment header")
    fixture = header["fixture"]
    if hashlib.sha256(_canonical(fixture).encode()).hexdigest() != header["fixture_sha256"]:
        raise ValueError("Fixture digest mismatch")
    environment = SyntheticEnvironment(fixture)
    if environment.observe() != header["initial_observation"]:
        raise ValueError("Initial observation mismatch")
    for sequence, record in enumerate(records[1:-1]):
        if (
            record.get("record_type") != "step"
            or type(record.get("sequence")) is not int
            or record["sequence"] != sequence
            or not {"decision", "result"} <= record.keys()
        ):
            raise ValueError("Step sequence mismatch")
        decision = Decision.from_dict(record["decision"])
        if environment.step(decision.action) != record["result"]:
            raise ValueError(f"Replay result mismatch at step {sequence}")
    expected = {
        "record_type": "summary",
        "steps": len(records) - 2,
        "final_observation": environment.observe(),
    }
    if summary != expected:
        raise ValueError("Missing or mismatched experiment summary")
    return {"verified": True, **expected}
