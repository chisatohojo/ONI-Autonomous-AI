import json

import pytest

from oni_ai import model_comparison as comparison
from oni_ai.cli import main
from oni_ai.episodes import digest
from oni_ai.evaluation import _canonical


@pytest.fixture
def tiny_v2(tmp_path, monkeypatch):
    monkeypatch.setattr(
        comparison,
        "MOCK_GROUPS",
        {
            "mock-development": [6001],
            "mock-validation": [6007],
        },
    )
    directory = tmp_path / "study-v2"
    comparison.prepare_model_comparison(directory, max_steps=2)
    return directory / "plan.json"


def test_v2_pairs_model_audit_freeze_csv_and_reserved_budget(tiny_v2):
    with pytest.raises(FileNotFoundError):
        comparison.run_model_comparison(tiny_v2, "mock-validation")
    development = comparison.run_model_comparison(tiny_v2, "mock-development")
    assert development["verified"] and development["episodes"] == 6
    assert development["mock_generations"] == 4
    comparison.freeze_model_comparison(tiny_v2)
    validation = comparison.run_model_comparison(tiny_v2, "mock-validation")
    assert validation["verified"] and validation["episodes"] == 6
    report_path = tiny_v2.parent / "mock-validation" / "report.json"
    report = json.loads(report_path.read_text("utf-8"))
    total = sum(
        r["inference"]["reserved_tokens"]
        for group in ["mock-development", "mock-validation"]
        for r in json.loads((tiny_v2.parent / group / "report.json").read_text("utf-8"))["rows"]
    )
    plan = comparison.read_model_plan(tiny_v2)
    assert report["budget_remaining"]["tokens"] == plan["run_budget"]["tokens"] - total
    assert set(report["aggregates"]) == {"exploration", "lookahead", "model-mock"}
    csv = report_path.parent / "metrics.csv"
    csv.write_bytes(csv.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="V2_CSV_MISMATCH"):
        comparison.verify_model_comparison(report_path)


def test_v2_real_model_not_exposed_and_b2_conditions_remain_design_only(tiny_v2):
    plan = comparison.read_model_plan(tiny_v2)
    assert plan["b2_conditions"]["status"] == "DESIGN_ONLY_NEVER_EXECUTED_IN_B1"
    used = {s for group in plan["groups"].values() for s in group}
    future = set(
        plan["b2_conditions"]["development_seeds"] + plan["b2_conditions"]["heldout_seeds"]
    )
    assert not used & future
    with pytest.raises(ValueError, match="B2_EXECUTION_NOT_AVAILABLE"):
        comparison.run_model_comparison(tiny_v2, "heldout")
    plan["model_key"] = "unconfigured-local"
    plan["plan_digest"] = digest({k: v for k, v in plan.items() if k != "plan_digest"})
    tiny_v2.write_text(_canonical(plan), "utf-8")
    with pytest.raises(ValueError, match="V2_PLAN_MISMATCH"):
        comparison.read_model_plan(tiny_v2)


def test_v2_source_freeze_and_reservation_budget_fail_closed(tiny_v2, monkeypatch):
    plan = json.loads(tiny_v2.read_text("utf-8"))
    plan["run_budget"]["tokens"] = 1
    plan["plan_digest"] = digest({k: v for k, v in plan.items() if k != "plan_digest"})
    tiny_v2.write_text(_canonical(plan), "utf-8")
    result = comparison.run_model_comparison(tiny_v2, "mock-development")
    assert result["mock_generations"] == 0
    report = json.loads((tiny_v2.parent / "mock-development" / "report.json").read_text("utf-8"))
    assert report["budget_remaining"]["tokens"] == 1
    assert any(
        row["policy"] == "model-mock" and row["stop_reason"] == "POLICY_EXCEPTION"
        for row in report["rows"]
    )
    monkeypatch.setattr(comparison, "source_manifest", lambda: {"changed": "digest"})
    with pytest.raises(ValueError, match="SOURCE_FREEZE"):
        comparison.read_model_plan(tiny_v2)


def test_v2_linked_sidecar_detects_model_result_tampering(tiny_v2):
    comparison.run_model_comparison(tiny_v2, "mock-development")
    directory = tiny_v2.parent / "mock-development"
    sidecar = directory / "6001-0-model-mock.audit.json"
    value = json.loads(sidecar.read_text("utf-8"))
    value["broker_records"][1]["count"] += 1
    value["content_digest"] = digest({k: v for k, v in value.items() if k != "content_digest"})
    sidecar.write_text(_canonical(value), "utf-8")
    with pytest.raises(ValueError, match="BROKER_AUDIT_COUNT"):
        comparison.verify_model_episode(directory / "6001-0-model-mock.jsonl", sidecar)


def test_v2_cli_prepare_run_verify_and_replay(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        comparison,
        "MOCK_GROUPS",
        {
            "mock-development": [6001],
            "mock-validation": [6007],
        },
    )
    directory = tmp_path / "cli-v2"
    assert main(["model-compare-prepare", str(directory), "--max-steps", "1"]) == 0
    capsys.readouterr()
    assert main(["model-compare", str(directory / "plan.json"), "--group", "mock-development"]) == 0
    assert json.loads(capsys.readouterr().out)["verified"]
    assert main(["model-compare-freeze", str(directory / "plan.json")]) == 0
    capsys.readouterr()
    report = directory / "mock-development" / "report.json"
    assert main(["model-compare-verify", str(report)]) == 0
    capsys.readouterr()
    receipt = report.parent / "6001-0-model-mock.jsonl"
    sidecar = report.parent / "6001-0-model-mock.audit.json"
    assert main(["model-episode-replay", str(receipt), str(sidecar)]) == 0
    assert json.loads(capsys.readouterr().out)["verified"]
