import json
from pathlib import Path

import pytest

from oni_ai import comparison
from oni_ai.cli import main
from oni_ai.episodes import EpisodeConfig
from oni_ai.evaluation import _canonical


@pytest.fixture
def tiny_study(tmp_path, monkeypatch):
    # Test-only seeds; production heldout outcomes are not inspected during implementation.
    monkeypatch.setattr(
        comparison,
        "GROUPS",
        {
            "development": [1000],
            "regression": [2000],
            "heldout": [3000],
        },
    )
    directory = tmp_path / "study"
    comparison.prepare_comparison(directory, config=EpisodeConfig(max_steps=2))
    return directory / "plan.json"


def test_fair_pairs_freeze_reports_and_replay(tiny_study):
    with pytest.raises(FileNotFoundError):
        comparison.run_comparison(tiny_study, "heldout")
    development = comparison.run_comparison(tiny_study, "development")
    assert development["episodes"] == 6 and development["all_replayed"]
    assert comparison.verify_comparison(development["report"])["verified"]
    frozen = comparison.freeze_comparison(tiny_study)
    assert frozen["plan_digest"] == comparison.read_plan(tiny_study)["plan_digest"]
    heldout = comparison.run_comparison(tiny_study, "heldout")
    assert heldout["episodes"] == 6
    directory = Path(heldout["report"]).parent
    assert (directory / "summary.md").exists() and (directory / "metrics.csv").exists()
    report = json.loads((directory / "report.json").read_text("utf-8"))
    assert report["rows"][0]["fixture_digest"] == report["rows"][1]["fixture_digest"]
    assert "paired_environment_mean_difference" in report["aggregates"]
    csv_path = directory / "metrics.csv"
    original_csv = csv_path.read_bytes()
    csv_path.write_bytes(original_csv + b"changed")
    with pytest.raises(ValueError, match="CSV report mismatch"):
        comparison.verify_comparison(directory / "report.json")
    csv_path.write_bytes(original_csv)
    with pytest.raises(FileExistsError):
        comparison.run_comparison(tiny_study, "heldout")
    report["rows"][0]["metrics"]["validity"]["attempts"] += 1
    (directory / "report.json").write_text(_canonical(report), "utf-8")
    with pytest.raises(ValueError, match="metrics/aggregates"):
        comparison.verify_comparison(directory / "report.json")


def test_freeze_rejects_source_and_development_changes(tiny_study, monkeypatch):
    comparison.run_comparison(tiny_study, "development")
    comparison.freeze_comparison(tiny_study)
    report = tiny_study.parent / "development" / "report.json"
    report.write_text(report.read_text("utf-8") + "\n", "utf-8")
    with pytest.raises(ValueError, match="freeze mismatch"):
        comparison.run_comparison(tiny_study, "regression")
    monkeypatch.setattr(comparison, "source_manifest", lambda: {"changed": "digest"})
    with pytest.raises(ValueError, match="Sources changed"):
        comparison.read_plan(tiny_study)


def test_plan_digest_validation_and_missing_values(tiny_study):
    plan = json.loads(tiny_study.read_text("utf-8"))
    plan["config"]["max_steps"] += 1
    tiny_study.write_text(_canonical(plan), "utf-8")
    with pytest.raises(ValueError, match="digest"):
        comparison.read_plan(tiny_study)
    assert comparison.distribution([None, 0, 2]) == {
        "n": 2,
        "missing": 1,
        "mean": 1,
        "std": 1,
        "min": 0,
        "max": 2,
    }
    assert comparison.distribution([None])["mean"] is None


def test_comparison_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        comparison,
        "GROUPS",
        {
            "development": [1000],
            "regression": [2000],
            "heldout": [3000],
        },
    )
    directory = tmp_path / "cli-study"
    assert main(["comparison-prepare", str(directory)]) == 0
    capsys.readouterr()
    plan = directory / "plan.json"
    assert main(["compare", str(plan), "--group", "development"]) == 0
    capsys.readouterr()
    assert main(["comparison-freeze", str(plan)]) == 0
    capsys.readouterr()
    assert main(["comparison-verify", str(directory / "development" / "report.json")]) == 0
    assert json.loads(capsys.readouterr().out)["verified"]
    receipt = directory / "development" / "1000-0-lookahead.jsonl"
    assert main(["research-replay", str(receipt)]) == 0
    assert json.loads(capsys.readouterr().out)["verified"]
