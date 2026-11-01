"""Preregistered paired experiments, development freeze, reports and receipt verification."""

import csv
import hashlib
import io
import statistics
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from oni_ai.benchmarks import sample_fixture
from oni_ai.contracts import strict_json
from oni_ai.episode_knowledge import database_snapshot, restore_snapshot
from oni_ai.episodes import EpisodeConfig, digest
from oni_ai.evaluation import _canonical
from oni_ai.policy_process import ProcessBudget
from oni_ai.research import replay_research, run_research_episode
from oni_ai.research_policy import POLICY_NAMES

GROUPS = {
    "development": [0, 1, 2, 17, 42, 101],
    "regression": [0, 1, 2, 17, 42, 101],
    "heldout": [203, 307, 409, 503, 607, 709, 811, 907],
}


def source_manifest() -> dict:
    package = Path(__file__).parent
    files = [p for p in package.rglob("*") if p.suffix in {".py", ".json", ".sql"}]
    return {
        p.relative_to(package).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(files)
    }


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(_canonical(value) + "\n")


def prepare_comparison(directory, db_path=None, *, config=None, budget=None):
    directory = Path(directory)
    plan = {
        "version": "comparison-plan/1",
        "groups": GROUPS,
        "policy_seeds": [0, 1, 2],
        "policies": list(POLICY_NAMES),
        "config": asdict(config or EpisodeConfig()),
        "budget": asdict(budget or ProcessBudget()),
        "sources": source_manifest(),
        "snapshot": [asdict(e) for e in database_snapshot(db_path)],
        "scope": "Synthetic only; regression seeds are previously public; heldout is not tuned",
    }
    plan["plan_digest"] = digest(plan)
    directory.mkdir()
    write_json(directory / "plan.json", plan)
    return {"plan": str(directory / "plan.json"), "plan_digest": plan["plan_digest"]}


def read_plan(path, *, current_source=True):
    try:
        return _read_plan(path, current_source=current_source)
    except (KeyError, TypeError, AttributeError, OverflowError) as error:
        raise ValueError("Malformed comparison plan") from error


def _read_plan(path, *, current_source=True):
    plan = strict_json(Path(path).read_text("utf-8"))
    body = {k: v for k, v in plan.items() if k != "plan_digest"}
    if plan["plan_digest"] != digest(body) or plan["version"] != "comparison-plan/1":
        raise ValueError("Comparison plan digest/version mismatch")
    if (
        plan["groups"] != GROUPS
        or plan["policies"] != list(POLICY_NAMES)
        or plan["policy_seeds"] != [0, 1, 2]
    ):
        raise ValueError("Unsupported comparison protocol")
    EpisodeConfig(**plan["config"])
    ProcessBudget(**plan["budget"])
    restore_snapshot(plan["snapshot"])
    if current_source and plan["sources"] != source_manifest():
        raise ValueError("Sources changed since preregistration; use a new plan")
    return plan


def freeze_comparison(plan_path):
    path = Path(plan_path)
    plan = read_plan(path)
    verified = verify_comparison(path.parent / "development" / "report.json")
    if verified["plan_digest"] != plan["plan_digest"]:
        raise ValueError("Development report belongs to a different plan")
    frozen = {
        "plan_digest": plan["plan_digest"],
        "development_sha256": hashlib.sha256(
            (path.parent / "development" / "report.json").read_bytes()
        ).hexdigest(),
        "source_digest": digest(plan["sources"]),
        "rule": "No tuning against regression/heldout outcomes after this freeze",
    }
    write_json(path.parent / "freeze.json", frozen)
    return frozen


def flatten_metrics(value, prefix=""):
    result = {}
    for key, item in value.items():
        name = f"{prefix}.{key}" if prefix else key
        if isinstance(item, dict):
            result.update(flatten_metrics(item, name))
        else:
            result[name] = item
    return result


def distribution(values):
    known = [float(v) for v in values if v is not None]
    return {
        "n": len(known),
        "missing": len(values) - len(known),
        "mean": statistics.mean(known) if known else None,
        "std": statistics.pstdev(known) if known else None,
        "min": min(known) if known else None,
        "max": max(known) if known else None,
    }


def aggregates(rows):
    flat = [(r, flatten_metrics(r["metrics"])) for r in rows]
    result = {}
    for policy in POLICY_NAMES:
        subset = [(r, m) for r, m in flat if r["policy"] == policy]
        keys = sorted({k for _, m in subset for k in m})
        result[policy] = {
            "episodes": len(subset),
            "stop_reasons": dict(sorted(Counter(r["stop_reason"] for r, _ in subset).items())),
            "distributions": {k: distribution([m.get(k) for _, m in subset]) for k in keys},
        }
    # Average policy-seed repetitions within an environment before descriptive paired differences.
    paired = {}
    for metric in (
        "progress.goal_met",
        "validity.invalid_action_rate",
        "progress.work_delta",
        "survival.synthetic_demand_proxy",
        "validity.attempts",
    ):
        differences = []
        for environment_seed in sorted({r["environment_seed"] for r in rows}):
            means = {}
            for policy in POLICY_NAMES:
                values = [
                    m[metric]
                    for r, m in flat
                    if r["environment_seed"] == environment_seed
                    and r["policy"] == policy
                    and m[metric] is not None
                ]
                means[policy] = statistics.mean(values) if values else None
            differences.append(
                None if None in means.values() else means["lookahead"] - means["exploration"]
            )
        paired[metric] = distribution(differences)
    return {
        "by_policy": result,
        "paired_environment_mean_difference": paired,
        "uncertainty_note": "Descriptive statistics only; repetitions share environments; "
        "no significance or ONI performance claim",
    }


def _row(group, seed, policy_seed, policy, receipt, summary, fixture):
    return {
        "group": group,
        "environment_seed": seed,
        "policy_seed": policy_seed,
        "policy": policy,
        "receipt": receipt,
        "fixture_digest": digest(fixture),
        "stop_reason": summary["stop_reason"],
        "metrics": summary["metrics"],
        "replay_verified": True,
    }


def markdown_report(report):
    lines = [
        "# 合成Policy比較",
        "",
        f"group: {report['group']}",
        f"plan: `{report['plan_digest']}`",
        "",
        "同じ初期状態・観測・操作予算・step上限での記述統計です。"
        "実ゲーム攻略性能や統計的な優越性は示しません。",
        "",
        "| Policy | episodes | 目標達成率 | 無効試行率 平均±SD | 試行数 平均±SD |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for policy, item in report["aggregates"]["by_policy"].items():
        d = item["distributions"]
        goal = d["progress.goal_met"]["mean"]
        invalid, attempts = d["validity.invalid_action_rate"], d["validity.attempts"]
        lines.append(
            f"| {policy} | {item['episodes']} | {goal:.3f} | "
            f"{invalid['mean']:.3f} ± {invalid['std']:.3f} | "
            f"{attempts['mean']:.2f} ± {attempts['std']:.2f} |"
        )
    lines += [
        "",
        "資源別の初期値・残量・純変化・観測減少量の代理指標・要求需要、"
        "需要充足のtrue/false/UNKNOWN、進捗、停滞、失敗後の変更/適用、"
        "UNKNOWN申告、終了理由、環境ごとのペア差はreport.jsonとmetrics.csvに保存します。",
        "",
        "観測減少量は生産と消費の相殺を含むため、設備の総投入量ではありません。"
        "行動意図の変更回数は計画の質を証明せず、拒否後の適用も生存改善を保証しません。",
        "",
        "評価に用いた環境seed: " + ", ".join(map(str, report["environment_seeds"])),
        "Policy seed: " + ", ".join(map(str, report["policy_seeds"])),
        "",
    ]
    return "\n".join(lines)


def csv_report(report):
    rows = [
        {**{k: v for k, v in row.items() if k != "metrics"}, **flatten_metrics(row["metrics"])}
        for row in report["rows"]
    ]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=sorted(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def run_comparison(plan_path, group):
    path = Path(plan_path)
    plan = read_plan(path)
    if group not in GROUPS:
        raise ValueError("Unknown comparison group")
    if group != "development":
        frozen = strict_json((path.parent / "freeze.json").read_text("utf-8"))
        if (
            frozen["plan_digest"] != plan["plan_digest"]
            or frozen["source_digest"] != digest(plan["sources"])
            or frozen["development_sha256"]
            != hashlib.sha256(
                (path.parent / "development" / "report.json").read_bytes()
            ).hexdigest()
        ):
            raise ValueError("Development freeze mismatch")
    directory = path.parent / group
    directory.mkdir()
    rows = []
    for seed in plan["groups"][group]:
        fixture = sample_fixture("development" if group == "development" else "evaluation", seed)
        for policy_seed in plan["policy_seeds"]:
            episode_id = digest({"fixture": fixture, "policy_seed": policy_seed})[:32]
            for policy in plan["policies"]:
                receipt = f"{seed}-{policy_seed}-{policy}.jsonl"
                summary = run_research_episode(
                    fixture,
                    policy,
                    policy_seed,
                    directory / receipt,
                    episode_id=episode_id,
                    config=EpisodeConfig(**plan["config"]),
                    budget=ProcessBudget(**plan["budget"]),
                    snapshot=restore_snapshot(plan["snapshot"]),
                    metadata={
                        "plan_digest": plan["plan_digest"],
                        "group": group,
                        "environment_seed": seed,
                        "policy_seed": policy_seed,
                    },
                )
                replay_research(directory / receipt)
                rows.append(_row(group, seed, policy_seed, policy, receipt, summary, fixture))
    report = {
        "version": "comparison-report/1",
        "plan_digest": plan["plan_digest"],
        "group": group,
        "environment_seeds": plan["groups"][group],
        "policy_seeds": plan["policy_seeds"],
        "rows": rows,
        "aggregates": aggregates(rows),
        "scope": "SYNTHETIC_ONLY_NOT_ONI",
    }
    write_json(directory / "report.json", report)
    with (directory / "summary.md").open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(markdown_report(report))
    with (directory / "metrics.csv").open("x", encoding="utf-8", newline="") as stream:
        stream.write(csv_report(report))
    verify_comparison(directory / "report.json")
    return {
        "report": str(directory / "report.json"),
        "episodes": len(rows),
        "all_replayed": True,
        "aggregates": report["aggregates"],
    }


def verify_comparison(report_path):
    try:
        return _verify_comparison(report_path)
    except (KeyError, TypeError, AttributeError, IndexError, OverflowError) as error:
        raise ValueError("Malformed comparison report") from error


def _verify_comparison(report_path):
    path = Path(report_path)
    report = strict_json(path.read_text("utf-8"))
    plan = read_plan(path.parent.parent / "plan.json", current_source=False)
    group = report["group"]
    if (
        report["version"] != "comparison-report/1"
        or report["plan_digest"] != plan["plan_digest"]
        or group not in GROUPS
        or report["environment_seeds"] != plan["groups"][group]
        or report["policy_seeds"] != plan["policy_seeds"]
    ):
        raise ValueError("Report protocol mismatch")
    expected_rows = []
    for seed in plan["groups"][group]:
        fixture = sample_fixture("development" if group == "development" else "evaluation", seed)
        for policy_seed in plan["policy_seeds"]:
            episode_id = digest({"fixture": fixture, "policy_seed": policy_seed})[:32]
            for policy in plan["policies"]:
                receipt = f"{seed}-{policy_seed}-{policy}.jsonl"
                receipt_path = path.parent / receipt
                summary = replay_research(receipt_path)
                header = strict_json(receipt_path.read_text("utf-8").splitlines()[0])
                if (
                    header["episode_id"] != episode_id
                    or header["fixture"] != fixture
                    or header["policy"] != {"name": policy, "seed": policy_seed}
                    or header["config"] != plan["config"]
                    or header["budget"] != plan["budget"]
                    or header["snapshot"] != plan["snapshot"]
                    or header["metadata"]
                    != {
                        "plan_digest": plan["plan_digest"],
                        "group": group,
                        "environment_seed": seed,
                        "policy_seed": policy_seed,
                    }
                ):
                    raise ValueError("Paired experiment conditions mismatch")
                expected_rows.append(
                    _row(group, seed, policy_seed, policy, receipt, summary, fixture)
                )
    if _canonical(expected_rows) != _canonical(report["rows"]) or _canonical(
        aggregates(expected_rows)
    ) != _canonical(report["aggregates"]):
        raise ValueError("Comparison metrics/aggregates mismatch")
    if (path.parent / "summary.md").read_text("utf-8") != markdown_report(report):
        raise ValueError("Markdown report mismatch")
    with (path.parent / "metrics.csv").open(encoding="utf-8", newline="") as stream:
        if stream.read() != csv_report(report):
            raise ValueError("CSV report mismatch")
    return {"verified": True, "episodes": len(expected_rows), "plan_digest": plan["plan_digest"]}
