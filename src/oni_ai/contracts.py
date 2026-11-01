"""Versioned offline experiment contracts, separate from OniMcp wire schemas."""

import json
import math
from dataclasses import asdict, dataclass

PROVENANCE = "MOCK_SYNTHETIC_NOT_GAME_DATA"
MODEL_VERSION = "synthetic-resource-model/1"
RESOURCE_KEYS = frozenset({"oxygen", "food", "energy", "water", "research", "work"})
ACTION_KINDS = frozenset({"wait", "set_process", "clear_blockage"})


def strict_json(text: str) -> object:
    def invalid(value):
        raise ValueError(f"Nonfinite JSON number: {value}")

    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError(f"Duplicate JSON key: {key}")
            obj[key] = value
        return obj

    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("JSON float overflow")
        return number

    return json.loads(
        text, parse_constant=invalid, parse_float=finite_float, object_pairs_hook=unique
    )


def finite_nonnegative(value: object, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if type(value) not in {int, float} or not math.isfinite(value) or value < 0:
        raise ValueError("Expected finite nonnegative number, or explicit null if allowed")


def nonempty(value: object) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 4000:
        raise ValueError("Expected a nonempty string of at most 4000 characters")


@dataclass(frozen=True)
class SyntheticAction:
    action_id: str
    context_id: str
    expected_tick: int
    kind: str
    target: str | None = None
    enabled: bool | None = None
    ticks: int = 1
    dry_run: bool = False
    schema_version: int = 1

    def __post_init__(self):
        nonempty(self.action_id)
        nonempty(self.context_id)
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("Unknown action schema version")
        if type(self.expected_tick) is not int or self.expected_tick < 0:
            raise ValueError("expected_tick must be a nonnegative integer")
        if self.kind not in ACTION_KINDS:
            raise ValueError("Unknown synthetic action; no arbitrary tool calls")
        if type(self.ticks) is not int or not 1 <= self.ticks <= 10:
            raise ValueError("ticks must be an integer between 1 and 10")
        if type(self.dry_run) is not bool:
            raise ValueError("dry_run must be boolean")
        if self.kind == "wait":
            if self.target is not None or self.enabled is not None:
                raise ValueError("wait accepts no target/enabled")
        else:
            nonempty(self.target)
            if self.ticks != 1:
                raise ValueError("Configuration changes advance exactly one synthetic tick")
            if self.kind == "set_process" and type(self.enabled) is not bool:
                raise ValueError("set_process requires enabled boolean")
            if self.kind == "clear_blockage" and self.enabled is not None:
                raise ValueError("clear_blockage accepts no enabled flag")

    @classmethod
    def from_dict(cls, payload: dict) -> "SyntheticAction":
        if not isinstance(payload, dict):
            raise ValueError("Action must be an object")
        try:
            return cls(**payload)
        except TypeError as error:
            raise ValueError("Missing or unknown action fields") from error


@dataclass(frozen=True)
class Decision:
    action: SyntheticAction
    rationale: str
    evidence_refs: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()

    def __post_init__(self):
        if not isinstance(self.action, SyntheticAction):
            raise ValueError("Validated action required")
        nonempty(self.rationale)
        for values in (self.evidence_refs, self.unknowns):
            if not isinstance(values, tuple) or len(values) > 100:
                raise ValueError("References/unknowns must be bounded tuples")
            for value in values:
                nonempty(value)

    @classmethod
    def from_dict(cls, payload: dict) -> "Decision":
        if (
            not isinstance(payload, dict)
            or not {"action", "rationale"} <= payload.keys()
            or set(payload)
            - {
                "action",
                "rationale",
                "evidence_refs",
                "unknowns",
            }
        ):
            raise ValueError("Invalid decision fields")
        nonempty(payload.get("rationale"))
        for key in ("evidence_refs", "unknowns"):
            values = payload.get(key, [])
            if not isinstance(values, list) or len(values) > 100:
                raise ValueError("Decision references/unknowns must be bounded lists")
            for value in values:
                nonempty(value)
        return cls(
            SyntheticAction.from_dict(payload["action"]),
            payload["rationale"],
            tuple(payload.get("evidence_refs", [])),
            tuple(payload.get("unknowns", [])),
        )

    def as_dict(self) -> dict:
        return asdict(self)
