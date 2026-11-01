"""Generic bounded model search and structured evidence claims for offline comparison."""

import random
from dataclasses import asdict

from oni_ai.contracts import SyntheticAction, strict_json
from oni_ai.episode_knowledge import KnowledgeQuery
from oni_ai.evaluation import _canonical
from oni_ai.policy import PolicyContext, PolicyInput, SeededTestPolicy
from oni_ai.simulation import SyntheticEnvironment

POLICY_NAMES = ("exploration", "lookahead")


def common_queries(inputs: PolicyInput) -> tuple[KnowledgeQuery, ...]:
    observation = strict_json(inputs.observation_json)
    return tuple(
        KnowledgeQuery(kind, "*", observation["game_version"], observation["dlc_scope"])
        for kind in ("model", "building", "rule")
    )


def intent(action: dict) -> str:
    return _canonical({key: action.get(key) for key in ("kind", "target", "enabled", "ticks")})


def claimed(proposal: dict, context: PolicyContext) -> dict:
    """Expose exact retrieved values, without converting database facts into model rules."""
    references = set(proposal["decision"]["evidence_refs"])
    claims = [
        {
            "evidence_id": item.evidence_id,
            "pointer": "",
            "value": strict_json(item.value_json),
            "status": item.status,
        }
        for item in context.knowledge
        if item.evidence_id in references or item.kind != "MODEL"
    ]
    return {"schema_version": 1, "proposal": proposal, "claims": claims}


class ResearchPolicy:
    """A common information boundary around the unchanged Phase 2 exploration baseline."""

    def __init__(self, name: str, seed: int = 0):
        if name not in POLICY_NAMES:
            raise ValueError("Unknown research policy")
        self.name = name
        self.policy = SeededTestPolicy(seed) if name == "exploration" else LookaheadPolicy(seed)

    def queries(self, inputs: PolicyInput) -> tuple[KnowledgeQuery, ...]:
        return common_queries(inputs)

    def propose(self, context: PolicyContext) -> dict:
        return claimed(self.policy.propose(context), context)


class LookaheadPolicy:
    """Depth-two, beam-eight receding-horizon search; no resource-specific solution rules."""

    name = "generic-lookahead/v1"

    def __init__(self, seed: int = 0):
        self.random = random.Random(seed)
        self.sequence = 0

    def queries(self, inputs: PolicyInput) -> tuple[KnowledgeQuery, ...]:
        return common_queries(inputs)

    @staticmethod
    def candidates(environment: SyntheticEnvironment) -> list[SyntheticAction]:
        observation = environment.observe()
        base = dict(context_id=observation["context_id"], expected_tick=observation["tick"])
        actions = [SyntheticAction(f"search-{observation['tick']}-wait", kind="wait", **base)]
        for target, process in sorted(observation["processes"].items()):
            actions.append(
                SyntheticAction(
                    f"search-{observation['tick']}-{target}-toggle",
                    kind="set_process",
                    target=target,
                    enabled=not process["enabled"],
                    **base,
                )
            )
            if process["blocked"]:
                actions.append(
                    SyntheticAction(
                        f"search-{observation['tick']}-{target}-clear",
                        kind="clear_blockage",
                        target=target,
                        **base,
                    )
                )
        return actions

    @staticmethod
    def predict(environment, action):
        from copy import deepcopy

        clone = deepcopy(environment)
        result = clone.step(action)
        if result["status"] != "APPLIED":
            return None
        if (
            action.target
            and result["after"]["processes"][action.target]["enabled"]
            and any(reason.endswith(f":{action.target}") for reason in result["failures"])
        ):
            return None
        return clone, result

    @staticmethod
    def score(state: dict, failures: list[str], objective: dict, transition: dict) -> tuple:
        # All resources use the same formula and their own observed demand/threshold scale.
        resources = state["resources"]
        unmet = sum(reason.startswith("UNMET_DEMAND:") for reason in failures)
        unknown = sum(reason.startswith("UNKNOWN_DEMAND:") for reason in failures)
        deficit = sum(
            max(0, target - resources[key]) / max(1, target)
            for key, target in objective.items()
            if resources[key] is not None
        )
        reserve = sum(
            min(3, resources[key] / max(1, demand, transition["thresholds"].get(key, 0)))
            for key, demand in transition["demand"].items()
            if resources[key] is not None
        )
        return -unmet, -unknown, -deficit, reserve

    def propose(self, context: PolicyContext) -> dict:
        observation = strict_json(context.inputs.observation_json)
        objective = strict_json(context.inputs.objective_json)
        specifications = {e.evidence_id: strict_json(e.value_json) for e in context.knowledge}
        transition = specifications["model:transition"]
        # This is a reconstruction from the allowed observation/specifications, never a fixture.
        fixture = {
            **{
                key: observation[key]
                for key in ("provenance", "model_version", "units", "resources", "processes")
            },
            "schema_version": 1,
            "fixture_id": "prediction",
            "description": "Policy prediction",
            "demand": transition["demand"],
            "thresholds": transition["thresholds"],
            "work_target": objective.get("work", 0),
        }
        environment = SyntheticEnvironment(fixture)
        recent = [
            strict_json(m.decision_json) for m in context.inputs.memory[-4:] if m.decision_json
        ]
        failed = {
            intent(strict_json(m.decision_json)["action"])
            for m in context.inputs.memory[-4:]
            if m.decision_json and m.failures
        }
        ranked = []
        for action in self.candidates(environment):
            prediction = self.predict(environment, action)
            if prediction is None:
                continue
            clone, result = prediction
            signature = intent(asdict(action))
            penalty = (
                int(signature in failed)
                + sum(intent(item["action"]) == signature for item in recent) / 10
            )
            score = self.score(result["after"], result["failures"], objective, transition)
            ranked.append((score, -penalty, self.random.random(), action, clone, result))
        if not ranked:
            raise ValueError("No feasible synthetic candidates")
        ranked.sort(key=lambda item: item[:3], reverse=True)
        finalists = []
        for _, penalty, tie, action, clone, first in ranked[:8]:
            second_scores = [
                self.score(
                    result["after"], first["failures"] + result["failures"], objective, transition
                )
                for candidate in self.candidates(clone)
                if (prediction := self.predict(clone, candidate)) is not None
                for _, result in [prediction]
            ]
            score = (
                max(second_scores)
                if second_scores
                else self.score(first["after"], first["failures"], objective, transition)
            )
            finalists.append((score, penalty, tie, action))
        selected = max(finalists, key=lambda item: item[:3])
        action = selected[3]
        self.sequence += 1
        action = SyntheticAction(
            f"lookahead-{self.sequence}",
            observation["context_id"],
            observation["tick"],
            action.kind,
            target=action.target,
            enabled=action.enabled,
        )
        refs = ["model:actions", "model:transition", "model:objective"]
        refs.extend(
            e.evidence_id for e in context.knowledge if e.evidence_id.startswith("model:process:")
        )
        return {
            "schema_version": 1,
            "observation_digest": observation["observation_digest"],
            "decision": {
                "action": asdict(action),
                "rationale": "Bounded generic model search: demand violations, normalized goal "
                "deficit and demand reserve; recent failed/repeated intents break ties. "
                "Database facts remain background evidence; unknown resources stay unknown.",
                "evidence_refs": refs,
                "unknowns": list(context.unknowns),
            },
        }
