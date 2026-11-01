"""Ports for observation and AI planning. No execution port is implemented in Phase 0."""

from dataclasses import dataclass
from typing import Protocol

from oni_ai.knowledge import BuildingKnowledge


@dataclass(frozen=True)
class Observation:
    resource_uri: str
    payload_json: str
    observed_at: str
    game_version: str
    dlc_scope: str
    context_id: str
    provenance: str


class ReadOnlyGameAdapter(Protocol):
    def read_resource(self, uri: str) -> Observation: ...


class KnowledgeSearch(Protocol):
    def search(
        self,
        query: str,
        *,
        game_version: str | None = None,
        dlc_scope: str | None = None,
        limit: int = 20,
    ) -> tuple[BuildingKnowledge, ...]: ...


@dataclass(frozen=True)
class PlanProposal:
    objective: str
    observation_context: str
    rationale: tuple[str, ...]
    steps: tuple[str, ...]
    unknowns: tuple[str, ...]


class PlanningAgent(Protocol):
    def propose(
        self,
        objective: str,
        observations: tuple[Observation, ...],
        knowledge: KnowledgeSearch,
    ) -> PlanProposal: ...
