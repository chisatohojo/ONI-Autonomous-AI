from dataclasses import replace

import pytest

from oni_ai.episodes import EpisodeConfig, EpisodeEngine
from oni_ai.evaluation import _canonical
from oni_ai.model_adapter import BudgetedModelAdapter, ModelLimits, ModelReply
from oni_ai.research_policy import ResearchPolicy
from oni_ai.simulation import load_fixture


class MockModel:
    model_id = "offline-test-model/1"
    tokenizer_revision = "mock-counter/1-not-real-tokens"
    input_microusd_per_million = 1000000
    output_microusd_per_million = 2000000

    def __init__(self, replies):
        self.replies = iter(replies)
        self.payloads = []

    def count_tokens(self, text):
        return 100  # Explicit artificial tokenizer for budget tests only.

    def complete(self, payload, **kwargs):
        self.payloads.append((payload, kwargs))
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        return reply


def case():
    engine = EpisodeEngine(load_fixture("normal"), "e" * 32, EpisodeConfig(), {"work": 100})
    policy = ResearchPolicy("lookahead")
    context = engine.context(policy.queries(engine.inputs()))
    return context, ModelReply(_canonical(policy.propose(context)), 100, 100)


def test_model_adapter_structured_retry_budget_and_no_fixture_label():
    context, valid = case()
    model = MockModel([replace(valid, text="bad JSON"), valid])
    adapter = BudgetedModelAdapter(model)
    assert adapter.queries(context.inputs)
    assert adapter.propose(context)["proposal"]
    assert adapter.calls == 2 and adapter.reserved_tokens == 4200
    assert adapter.reserved_cost == 8200
    assert "INVALID_STRUCTURED_OUTPUT" in model.payloads[1][0]
    assert '"fixture_id"' not in model.payloads[0][0]


@pytest.mark.parametrize(
    "limits,reply,expected",
    [
        (ModelLimits(input_tokens=99), None, "INPUT_BUDGET"),
        (ModelLimits(total_tokens=2099), None, "TOTAL_BUDGET"),
        (ModelLimits(cost_microusd=1), None, "TOTAL_BUDGET"),
        (ModelLimits(), ModelReply("{}", 101, 1), "USAGE_OR_OUTPUT_BUDGET"),
        (ModelLimits(), ModelReply("{}", 100, 2001), "USAGE_OR_OUTPUT_BUDGET"),
    ],
)
def test_model_adapter_rejects_budget_overruns(limits, reply, expected):
    context, valid = case()
    model = MockModel([reply or valid])
    adapter = BudgetedModelAdapter(model, limits)
    with pytest.raises(ValueError, match=expected):
        adapter.propose(context)


def test_failed_calls_remain_reserved_and_unknown_prices_are_rejected():
    context, _ = case()
    model = MockModel([RuntimeError("secret message"), RuntimeError("secret message")])
    adapter = BudgetedModelAdapter(model)
    with pytest.raises(ValueError, match="ATTEMPTS_EXHAUSTED"):
        adapter.propose(context)
    assert adapter.calls == 2 and adapter.reserved_tokens == 4200
    assert "secret message" not in model.payloads[1][0]
    model.input_microusd_per_million = None
    with pytest.raises(ValueError, match="UNKNOWN"):
        BudgetedModelAdapter(model)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"attempts": 0},
        {"attempts": 6},
        {"seconds": -1},
        {"seconds": float("nan")},
        {"total_tokens": True},
    ],
)
def test_invalid_model_budget(kwargs):
    with pytest.raises(ValueError):
        ModelLimits(**kwargs)
