"""Small synthetic resource model. No ONI physics, strategy, transport or live executor."""

from copy import deepcopy
from dataclasses import replace
from importlib.resources import files

from oni_ai.contracts import (
    MODEL_VERSION,
    PROVENANCE,
    RESOURCE_KEYS,
    SyntheticAction,
    finite_nonnegative,
    nonempty,
    strict_json,
)


def fixture_names() -> tuple[str, ...]:
    catalog = strict_json(
        files("oni_ai").joinpath("data/synthetic_fixtures.json").read_text("utf-8")
    )
    return tuple(sorted(catalog["scenarios"]))


def load_fixture(name: str) -> dict:
    catalog = strict_json(
        files("oni_ai").joinpath("data/synthetic_fixtures.json").read_text("utf-8")
    )
    if name not in catalog["scenarios"]:
        raise ValueError("Unknown packaged fixture")
    fixture = deepcopy(catalog["base"])
    overrides = catalog["scenarios"][name]
    fixture["fixture_id"] = name
    fixture["description"] = overrides["description"]
    fixture["resources"].update(overrides.get("resources", {}))
    for process_id, changes in overrides.get("processes", {}).items():
        fixture["processes"][process_id].update(changes)
    validate_fixture(fixture)
    return fixture


def validate_fixture(fixture: dict) -> None:
    try:
        _validate_fixture(fixture)
    except (KeyError, TypeError, AttributeError, OverflowError) as error:
        raise ValueError("Malformed synthetic fixture") from error


def _validate_fixture(fixture: dict) -> None:
    if (
        fixture.get("provenance") != PROVENANCE
        or fixture.get("model_version") != MODEL_VERSION
        or type(fixture.get("schema_version")) is not int
        or fixture["schema_version"] != 1
    ):
        raise ValueError("Only explicitly synthetic model version 1 fixtures are accepted")
    nonempty(fixture.get("fixture_id"))
    nonempty(fixture.get("description"))
    if fixture.get("units") != "arbitrary_synthetic_units_per_tick_NOT_ONI":
        raise ValueError("Fixture units must explicitly exclude ONI interpretation")
    if set(fixture["resources"]) != RESOURCE_KEYS:
        raise ValueError("Fixture resources must exactly match the observation schema")
    for value in fixture["resources"].values():
        finite_nonnegative(value, nullable=True)
    for mapping in (fixture["demand"], fixture["thresholds"]):
        if set(mapping) - RESOURCE_KEYS:
            raise ValueError("Unknown demand/threshold resource")
        for value in mapping.values():
            finite_nonnegative(value)
    finite_nonnegative(fixture["work_target"])
    if not isinstance(fixture["processes"], dict) or len(fixture["processes"]) > 20:
        raise ValueError("Process map must contain at most 20 processes")
    for process_id, process in fixture["processes"].items():
        nonempty(process_id)
        if set(process) != {"enabled", "blocked", "requires_research", "inputs", "outputs"}:
            raise ValueError("Unknown or missing process fields")
        if type(process["enabled"]) is not bool or type(process["blocked"]) is not bool:
            raise ValueError("Process flags must be booleans")
        finite_nonnegative(process["requires_research"])
        for field in ("inputs", "outputs"):
            if set(process[field]) - RESOURCE_KEYS:
                raise ValueError("Unknown process resource")
            for value in process[field].values():
                finite_nonnegative(value)


class SyntheticEnvironment:
    def __init__(self, fixture: dict):
        validate_fixture(fixture)
        self._fixture = deepcopy(fixture)
        self._resources = deepcopy(fixture["resources"])
        self._processes = deepcopy(fixture["processes"])
        self._tick = 0
        self._seen_ids: set[str] = set()

    def observe(self) -> dict:
        alerts = []
        for resource, threshold in sorted(self._fixture["thresholds"].items()):
            value = self._resources[resource]
            if value is None:
                alerts.append(f"UNKNOWN:{resource}")
            elif value < threshold:
                alerts.append(f"LOW:{resource}")
        return {
            "schema_version": 1,
            "game_version": "UNKNOWN",
            "dlc_scope": "UNKNOWN",
            "provenance": PROVENANCE,
            "model_version": MODEL_VERSION,
            "fixture_id": self._fixture["fixture_id"],
            "context_id": f"synthetic:{self._fixture['fixture_id']}",
            "tick": self._tick,
            "units": self._fixture["units"],
            "resources": deepcopy(self._resources),
            "processes": deepcopy(self._processes),
            "alerts": alerts,
        }

    def step(self, action: SyntheticAction) -> dict:
        if not isinstance(action, SyntheticAction):
            raise ValueError("A validated SyntheticAction is required")
        before = self.observe()
        reason = None
        if action.context_id != before["context_id"]:
            reason = "CONTEXT_MISMATCH"
        elif action.action_id in self._seen_ids:
            reason = "DUPLICATE_ACTION"
        elif action.expected_tick != self._tick:
            reason = "STALE_OBSERVATION"
        elif action.kind != "wait" and action.target not in self._processes:
            reason = "UNKNOWN_TARGET"
        if reason:
            return {
                "status": "REJECTED",
                "before": before,
                "after": before,
                "failures": [reason],
                "metrics": self._metrics(before, []),
            }
        if action.dry_run:
            clone = deepcopy(self)
            result = clone.step(replace(action, dry_run=False))
            return {
                **result,
                "status": "PREVIEW",
                "preview": result["after"],
                "after": before,
                "metrics": self._metrics(before, []),
                "preview_metrics": result["metrics"],
            }
        self._seen_ids.add(action.action_id)
        if action.kind == "set_process":
            self._processes[action.target]["enabled"] = action.enabled
        elif action.kind == "clear_blockage":
            self._processes[action.target]["blocked"] = False
        failures = []
        try:
            for _ in range(action.ticks):
                failures.extend(self._advance())
                self._tick += 1
        except (ValueError, OverflowError):
            self._resources = deepcopy(before["resources"])
            self._processes = deepcopy(before["processes"])
            self._tick = before["tick"]
            self._seen_ids.remove(action.action_id)
            return {
                "status": "REJECTED",
                "before": before,
                "after": self.observe(),
                "failures": ["MODEL_NUMERIC_LIMIT"],
                "metrics": self._metrics(before, []),
            }
        return {
            "status": "APPLIED",
            "before": before,
            "after": self.observe(),
            "failures": sorted(set(failures)),
            "metrics": self._metrics(before, failures),
        }

    def _advance(self) -> list[str]:
        candidates, failures = {}, []
        for name, process in sorted(self._processes.items()):
            if not process["enabled"]:
                continue
            if process["blocked"]:
                failures.append(f"BLOCKED:{name}")
                continue
            required = process["requires_research"]
            if required and (
                self._resources["research"] is None or self._resources["research"] < required
            ):
                failures.append(f"RESEARCH_UNAVAILABLE:{name}")
                continue
            touched = set(process["inputs"]) | set(process["outputs"])
            if any(self._resources[r] is None for r in touched):
                failures.append(f"UNKNOWN_RESOURCE:{name}")
                continue
            candidates[name] = process
        # Conservative simultaneous allocation: do not introduce a hidden process priority.
        total_inputs = {
            r: sum(p["inputs"].get(r, 0) for p in candidates.values()) for r in RESOURCE_KEYS
        }
        scarce = {
            r for r, needed in total_inputs.items() if needed > 0 and self._resources[r] < needed
        }
        active = []
        for name, process in candidates.items():
            if scarce.intersection(process["inputs"]):
                failures.append(f"INSUFFICIENT_INPUT:{name}")
            else:
                active.append(process)
        updated = deepcopy(self._resources)
        for resource in RESOURCE_KEYS:
            if updated[resource] is None:
                continue
            delta = sum(
                p["outputs"].get(resource, 0) - p["inputs"].get(resource, 0) for p in active
            )
            updated[resource] += delta
            finite_nonnegative(updated[resource])
        for resource, demand in self._fixture["demand"].items():
            if updated[resource] is None:
                if demand:
                    failures.append(f"UNKNOWN_DEMAND:{resource}")
            else:
                if updated[resource] < demand:
                    failures.append(f"UNMET_DEMAND:{resource}")
                updated[resource] = max(0, updated[resource] - demand)
        self._resources = updated
        return failures

    def _metrics(self, before: dict, failures: list[str]) -> dict:
        changes = {}
        for resource in ("work", "research"):
            old, new = before["resources"][resource], self._resources[resource]
            changes[f"{resource}_delta"] = None if old is None or new is None else new - old
        old_work, work = before["resources"]["work"], self._resources["work"]
        return {
            **changes,
            "alerts": self.observe()["alerts"],
            "stalled": None
            if work is None or old_work is None
            else (
                self._tick > before["tick"]
                and work < self._fixture["work_target"]
                and work <= old_work
            ),
            "unmet_demand": sorted(
                {f.split(":", 1)[1] for f in failures if f.startswith("UNMET_DEMAND:")}
            ),
        }
