import json

import pytest

from oni_ai.cli import main
from oni_ai.contracts import Decision, SyntheticAction
from oni_ai.evaluation import replay_log, run_experiment
from oni_ai.simulation import load_fixture


def decisions(name="work_stalled"):
    context = f"synthetic:{name}"
    return [
        Decision(
            SyntheticAction("a", context, 0, "wait"), "Observe baseline", (), ("Synthetic only",)
        ),
        Decision(
            SyntheticAction("b", context, 1, "clear_blockage", target="work_unit"),
            "Test the effect of one explicit action",
            ("fixture:work_unit.blocked",),
        ),
    ]


def test_logs_replay_rationale_outcomes_and_failures(tmp_path):
    path = tmp_path / "run.jsonl"
    summary = run_experiment(load_fixture("work_stalled"), decisions(), path)
    records = [json.loads(line) for line in path.read_text("utf-8").splitlines()]
    assert records[1]["decision"]["rationale"] == "Observe baseline"
    assert records[1]["result"]["metrics"]["stalled"]
    assert "BLOCKED:work_unit" in records[1]["result"]["failures"]
    assert not records[2]["result"]["metrics"]["stalled"]
    assert replay_log(path)["final_observation"] == summary["final_observation"]
    with pytest.raises(FileExistsError):
        run_experiment(load_fixture("work_stalled"), decisions(), path)


@pytest.mark.parametrize("change", ["result", "sequence", "digest", "truncate"])
def test_replay_detects_incomplete_or_inconsistent_receipts(tmp_path, change):
    path = tmp_path / "run.jsonl"
    run_experiment(load_fixture("work_stalled"), decisions(), path)
    records = [json.loads(line) for line in path.read_text("utf-8").splitlines()]
    if change == "result":
        records[1]["result"]["after"]["resources"]["work"] = 123
    elif change == "sequence":
        records[1]["sequence"] = 99
    elif change == "digest":
        records[0]["fixture"]["resources"]["water"] = 999
    else:
        records.pop()
    path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
    with pytest.raises(ValueError):
        replay_log(path)


def test_cli_full_offline_experiment_and_db_workflow(tmp_path, capsys):
    db = tmp_path / "kb.sqlite3"
    assert main(["init-db", str(db)]) == 0
    capsys.readouterr()
    assert main(["import-catalog", str(db)]) == 0
    assert json.loads(capsys.readouterr().out)["rules"] == 5
    assert main(["audit-db", str(db)]) == 0
    assert json.loads(capsys.readouterr().out)["valid"]
    assert main(["rules", str(db), "--domain", "water"]) == 0
    assert len(json.loads(capsys.readouterr().out)) == 1
    actions = tmp_path / "decisions.json"
    actions.write_text(json.dumps([d.as_dict() for d in decisions()]), encoding="utf-8")
    log = tmp_path / "receipt.jsonl"
    assert main(["simulate", "work_stalled", "--decisions", str(actions), "--log", str(log)]) == 0
    capsys.readouterr()
    assert main(["replay", str(log)]) == 0
    assert json.loads(capsys.readouterr().out)["verified"]


def test_rejected_action_is_preserved_in_receipt(tmp_path):
    path = tmp_path / "failed.jsonl"
    decision = Decision(
        SyntheticAction("stale", "synthetic:normal", 99, "wait"), "Synthetic stale observation test"
    )
    run_experiment(load_fixture("normal"), [decision], path)
    record = json.loads(path.read_text("utf-8").splitlines()[1])
    assert record["result"]["status"] == "REJECTED"
    assert record["result"]["failures"] == ["STALE_OBSERVATION"]
    assert replay_log(path)["verified"]


def test_replay_multiple_alerts_is_independent_of_object_key_order(tmp_path):
    fixture = load_fixture("normal")
    fixture["resources"].update(oxygen=0, food=0)
    fixture["processes"]["oxygen_unit"]["enabled"] = False
    fixture["processes"]["food_unit"]["enabled"] = False
    decision = Decision(
        SyntheticAction("a", "synthetic:normal", 0, "wait"), "Test simultaneous synthetic shortages"
    )
    path = tmp_path / "multi.jsonl"
    run_experiment(fixture, [decision], path)
    assert replay_log(path)["verified"]


@pytest.mark.parametrize("records", [[None, None, None], [{}, {}, {}]])
def test_malformed_receipts_fail_with_validation_errors(tmp_path, records):
    path = tmp_path / "malformed.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
    with pytest.raises(ValueError):
        replay_log(path)
