"""Provider-neutral structured model boundary, exercised only with injected offline mocks."""

import math
import time
from dataclasses import asdict, dataclass
from typing import Protocol

from oni_ai.contracts import strict_json
from oni_ai.evaluation import _canonical
from oni_ai.research_boundary import validate_envelope
from oni_ai.research_policy import common_queries


@dataclass(frozen=True)
class ModelLimits:
    input_tokens: int = 8000
    output_tokens: int = 2000
    total_tokens: int = 20000
    cost_microusd: int = 100000
    attempts: int = 2
    seconds: float = 10.0

    def __post_init__(self):
        for value in (
            self.input_tokens,
            self.output_tokens,
            self.total_tokens,
            self.cost_microusd,
            self.attempts,
        ):
            if type(value) is not int or value < 1:
                raise ValueError("Model limits must be positive integers")
        if (
            self.attempts > 5
            or type(self.seconds) not in {int, float}
            or not math.isfinite(self.seconds)
            or not 0 < self.seconds <= 300
        ):
            raise ValueError("Invalid retry/time limit")


@dataclass(frozen=True)
class ModelReply:
    text: str
    input_tokens: int
    output_tokens: int


class StructuredModel(Protocol):
    """No implementation here opens a socket or starts a model service."""

    model_id: str
    tokenizer_revision: str
    input_microusd_per_million: int
    output_microusd_per_million: int

    def count_tokens(self, text: str) -> int: ...

    def complete(
        self, payload: str, *, max_output_tokens: int, timeout_seconds: float
    ) -> ModelReply: ...


class BudgetedModelAdapter:
    """Reserve worst-case token/cost usage before every attempt; never refund failed calls."""

    name = "structured-model-adapter/mock-validated-v1"

    def __init__(self, model: StructuredModel, limits=None):
        self.model = model
        self.limits = limits or ModelLimits()
        for value in (model.input_microusd_per_million, model.output_microusd_per_million):
            if type(value) is not int or value < 0:
                raise ValueError("Known nonnegative prices required; UNKNOWN is not zero")
        if not model.model_id or not model.tokenizer_revision:
            raise ValueError("Explicit model/tokenizer versions required")
        self.reserved_tokens = self.reserved_cost = self.calls = 0

    def queries(self, inputs):
        return common_queries(inputs)

    def propose(self, context):
        deadline = time.monotonic() + self.limits.seconds
        previous_error = None
        for _ in range(self.limits.attempts):
            payload = _canonical(
                {
                    "schema_version": 1,
                    "context": asdict(context),
                    "response_contract": (
                        "research envelope: proposal, exact source claims, UNKNOWN"
                    ),
                    "previous_error": previous_error,
                }
            )
            count = self.model.count_tokens(payload)
            if type(count) is not int or not 0 <= count <= self.limits.input_tokens:
                raise ValueError("MODEL_INPUT_BUDGET")
            tokens = count + self.limits.output_tokens
            cost = (
                count * self.model.input_microusd_per_million
                + self.limits.output_tokens * self.model.output_microusd_per_million
                + 999999
            ) // 1000000
            if (
                self.reserved_tokens + tokens > self.limits.total_tokens
                or self.reserved_cost + cost > self.limits.cost_microusd
            ):
                raise ValueError("MODEL_TOTAL_BUDGET")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError("MODEL_TIME_BUDGET")
            self.reserved_tokens += tokens
            self.reserved_cost += cost
            self.calls += 1
            try:
                reply = self.model.complete(
                    payload, max_output_tokens=self.limits.output_tokens, timeout_seconds=remaining
                )
            except Exception:
                previous_error = "MODEL_TRANSPORT_ERROR"
                continue
            if time.monotonic() > deadline:
                raise ValueError("MODEL_TIME_BUDGET")
            if (
                not isinstance(reply, ModelReply)
                or type(reply.input_tokens) is not int
                or not 0 <= reply.input_tokens <= count
                or type(reply.output_tokens) is not int
                or not 0 <= reply.output_tokens <= self.limits.output_tokens
                or not isinstance(reply.text, str)
                or len(reply.text.encode("utf-8")) > 65536
            ):
                raise ValueError("MODEL_USAGE_OR_OUTPUT_BUDGET")
            proposal, failures = validate_envelope(
                reply.text, strict_json(context.inputs.observation_json), context.knowledge, set()
            )
            if not failures and proposal is not None:
                return strict_json(reply.text)
            previous_error = "INVALID_STRUCTURED_OUTPUT"
        raise ValueError("MODEL_ATTEMPTS_EXHAUSTED")
