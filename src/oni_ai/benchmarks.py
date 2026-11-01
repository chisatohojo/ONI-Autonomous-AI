"""Disjoint parameter distributions for synthetic development and held-out evaluation."""

import random
from pathlib import Path

from oni_ai.simulation import load_fixture, validate_fixture

BENCHMARK_VERSION = "synthetic-benchmark/1"


def sample_fixture(split: str, seed: int) -> dict:
    if split not in {"development", "evaluation"} or type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("Expected development/evaluation split and a uint32 seed")
    randomizer = random.Random(f"{BENCHMARK_VERSION}:{split}:{seed}")
    fixture = load_fixture("normal")
    fixture["fixture_id"] = f"{split}-{seed}"
    fixture["description"] = (
        "Generated synthetic initial state; never an ONI performance benchmark."
    )
    evaluation = split == "evaluation"
    fixture["resources"].update(
        {
            "oxygen": randomizer.randint(0, 7) if evaluation else randomizer.randint(10, 20),
            "food": randomizer.randint(0, 7) if evaluation else randomizer.randint(10, 20),
            "energy": randomizer.randint(0, 6) if evaluation else randomizer.randint(10, 20),
            "water": randomizer.randint(0, 12) if evaluation else randomizer.randint(30, 50),
            "research": 0,
            "work": 0,
        }
    )
    for process in fixture["processes"].values():
        process["enabled"] = randomizer.random() < 0.65
        process["blocked"] = randomizer.random() < (0.35 if evaluation else 0.1)
        process["requires_research"] = randomizer.randint(0, 2) if evaluation else 0
    if evaluation:
        unknown = ("oxygen", "water", "research")[seed % 3]
        fixture["resources"][unknown] = None
        fixture["processes"]["unseen_converter"] = {
            "enabled": False,
            "blocked": randomizer.choice([True, False]),
            "requires_research": randomizer.randint(0, 2),
            "inputs": {"energy": randomizer.randint(2, 4)},
            "outputs": {"work": randomizer.randint(2, 4)},
        }
        fixture["demand"] = {"oxygen": randomizer.randint(3, 5), "food": randomizer.randint(3, 5)}
    fixture["work_target"] = randomizer.randint(8, 15)
    validate_fixture(fixture)
    return fixture


def run_benchmark(
    split: str,
    seeds: list[int],
    output_dir: Path,
    *,
    config,
    policy_seed: int = 0,
    db_path: Path | None = None,
    objective: dict | None = None,
) -> dict:
    from oni_ai.episodes import replay_episode, run_episode
    from oni_ai.evaluation import _canonical
    from oni_ai.policy import SeededTestPolicy

    if (
        not isinstance(seeds, list)
        or not 1 <= len(seeds) <= 20
        or any(type(seed) is not int for seed in seeds)
        or len(set(seeds)) != len(seeds)
    ):
        raise ValueError("Provide 1..20 unique integer environment seeds")
    fixtures = [sample_fixture(split, seed) for seed in seeds]
    output_dir.mkdir()  # Exclusive directory creation preserves all prior benchmark receipts.
    results = []
    for seed, fixture in zip(seeds, fixtures, strict=True):
        path = output_dir / f"episode-{seed}.jsonl"
        summary = run_episode(
            fixture,
            SeededTestPolicy(policy_seed),
            path,
            config=config,
            db_path=db_path,
            objective=objective,
            metadata={
                "benchmark_version": BENCHMARK_VERSION,
                "split": split,
                "environment_seed": seed,
                "policy_seed": policy_seed,
            },
        )
        verified = replay_episode(path)
        results.append(
            {
                "environment_seed": seed,
                "receipt": path.name,
                "replay_verified": verified["verified"],
                **summary,
            }
        )
    report = {
        "schema_version": 1,
        "benchmark_version": BENCHMARK_VERSION,
        "split": split,
        "policy_seed": policy_seed,
        "results": results,
        "scope": "Synthetic test-policy plumbing only; no ONI performance claim",
    }
    with (output_dir / "report.json").open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(_canonical(report) + "\n")
    return report
