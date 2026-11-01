"""Replaceable offline Policy boundary and a non-strategic seeded exploration test double."""

import random
from dataclasses import dataclass
from typing import Protocol

from oni_ai.contracts import Decision, SyntheticAction, strict_json
from oni_ai.episode_knowledge import Evidence, KnowledgeQuery


@dataclass(frozen=True)
class MemoryEntry:
    attempt: int
    decision_json: str | None
    observation_before_json: str
    observation_after_json: str
    failures: tuple[str, ...]
    metrics_json: str


@dataclass(frozen=True)
class PolicyInput:
    observation_json: str
    objective_json: str
    memory: tuple[MemoryEntry, ...]


@dataclass(frozen=True)
class PolicyContext:
    inputs: PolicyInput
    knowledge: tuple[Evidence, ...]
    unknowns: tuple[str, ...]


class Policy(Protocol):
    name: str

    def queries(self, inputs: PolicyInput) -> tuple[KnowledgeQuery, ...]: ...

    def propose(self, context: PolicyContext) -> object: ...


class SeededTestPolicy:
    """Generic random schema exploration. No fixture names, resource rules or solution tables."""

    name = "seeded-test-policy/v1"

    def __init__(self, seed: int = 0):
        if type(seed) is not int:
            raise ValueError("Policy seed must be an integer")
        self._random = random.Random(seed)
        self._sequence = 0

    def queries(self, inputs: PolicyInput) -> tuple[KnowledgeQuery, ...]:
        return (KnowledgeQuery("model", "*"),)

    def propose(self, context: PolicyContext) -> object:
        observation = strict_json(context.inputs.observation_json)
        choices = [("wait", None, None)]
        for target in sorted(observation["processes"]):
            choices.extend(
                [
                    ("set_process", target, False),
                    ("set_process", target, True),
                    ("clear_blockage", target, None),
                ]
            )
        kind, target, enabled = self._random.choice(choices)
        self._sequence += 1
        refs = ["model:actions"]
        if target is not None:
            refs.append(f"model:process:{target}")
        decision = Decision(
            SyntheticAction(
                f"proposal-{self._sequence}",
                observation["context_id"],
                observation["tick"],
                kind,
                target=target,
                enabled=enabled,
            ),
            "Seeded generic exploration of the action schema; no crisis-specific strategy. "
            f"Previous outcomes available in memory: {len(context.inputs.memory)}.",
            tuple(refs),
            context.unknowns,
        )
        return {
            "schema_version": 1,
            "observation_digest": observation["observation_digest"],
            "decision": {
                **decision.as_dict(),
                "evidence_refs": list(decision.evidence_refs),
                "unknowns": list(decision.unknowns),
            },
        }
