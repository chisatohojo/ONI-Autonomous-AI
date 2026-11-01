import json

import pytest

from oni_ai.benchmarks import run_benchmark, sample_fixture
from oni_ai.cli import main
from oni_ai.episodes import EpisodeConfig, replay_episode


def test_development_and_evaluation_are_disjoint_and_deterministic():
    for seed in (0, 1, 2, 17, 101):
        development = sample_fixture("development", seed)
        evaluation = sample_fixture("evaluation", seed)
        assert development == sample_fixture("development", seed)
        assert evaluation == sample_fixture("evaluation", seed)
        assert development["resources"]["food"] >= 10
        assert evaluation["resources"]["food"] <= 7
        assert len(evaluation["processes"]) > len(development["processes"])
        assert any(value is None for value in evaluation["resources"].values())
    assert sample_fixture("evaluation", 1) != sample_fixture("evaluation", 2)


def test_multiple_evaluation_seeds_record_independent_metrics_and_replay(tmp_path):
    directory = tmp_path / "evaluation"
    report = run_benchmark("evaluation", [0, 1, 2], directory, config=EpisodeConfig(max_steps=4))
    assert len(report["results"]) == 3
    assert len({r["episode_id"] for r in report["results"]}) == 3
    for result in report["results"]:
        assert set(result["metrics"]) == {"survival", "resources", "progress", "validity"}
        assert result["replay_verified"]
        assert replay_episode(directory / result["receipt"])["verified"]
    with pytest.raises(FileExistsError):
        run_benchmark("evaluation", [0], directory, config=EpisodeConfig(max_steps=1))


@pytest.mark.parametrize(
    "split,seed", [("training_answers", 0), ("evaluation", -1), ("evaluation", True)]
)
def test_unknown_splits_and_invalid_seeds_rejected(split, seed):
    with pytest.raises(ValueError):
        sample_fixture(split, seed)


def test_cli_autonomous_run_inspect_replay_and_benchmark(tmp_path, capsys):
    log = tmp_path / "episode.jsonl"
    assert main(["episode", "--seed", "2", "--max-steps", "4", "--log", str(log)]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["attempts"] == 4
    assert main(["episode-result", str(log)]) == 0
    assert json.loads(capsys.readouterr().out)["verified"]
    assert main(["episode-replay", str(log)]) == 0
    assert json.loads(capsys.readouterr().out)["policy_reexecuted"] is False
    assert (
        main(
            [
                "benchmark",
                "--seeds",
                "1",
                "2",
                "--max-steps",
                "2",
                "--output-dir",
                str(tmp_path / "batch"),
            ]
        )
        == 0
    )
    assert len(json.loads(capsys.readouterr().out)["results"]) == 2
