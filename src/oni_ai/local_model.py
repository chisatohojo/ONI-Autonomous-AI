"""Ollama-shaped StructuredModel with injected transport; no HTTP implementation."""

import math
import time
from dataclasses import dataclass

from oni_ai.episodes import digest
from oni_ai.inference_contracts import (
    CounterBinding,
    InferenceError,
    context_from_dict,
    decode_frame,
    envelope_schema,
    safe_json,
    validate_schema,
)
from oni_ai.model_adapter import ModelReply
from oni_ai.research_boundary import validate_envelope
from oni_ai.research_policy import ResearchPolicy


@dataclass(frozen=True)
class LocalModelProfile:
    model_id: str = "offline-byte-model/v1"
    tokenizer_revision: str = "mock-utf8-byte/1"
    template_revision: str = "mock-chat/1"
    artifact_digest: str = "MOCK_NOT_MODEL_WEIGHTS"
    input_microusd_per_million: int = 1_000_000
    output_microusd_per_million: int = 2_000_000

    def __post_init__(self):
        for value in (
            self.model_id,
            self.tokenizer_revision,
            self.template_revision,
            self.artifact_digest,
        ):
            if not isinstance(value, str) or not value or len(value) > 200:
                raise InferenceError("INVALID_MODEL_PROFILE")
        for value in (self.input_microusd_per_million, self.output_microusd_per_million):
            if type(value) is not int or value < 0:
                raise InferenceError("UNKNOWN_PRICE")


def profile_for(key):
    if key == "offline":
        return LocalModelProfile()
    if key == "unconfigured-local":
        return LocalModelProfile("qwen3.5:4b", "UNKNOWN", "UNKNOWN", "UNKNOWN", 0, 0)
    raise InferenceError("MODEL_NOT_ALLOWED")


def model_input(payload):
    raw = decode_frame(payload)
    if (
        not isinstance(raw, dict)
        or set(raw) != {"schema_version", "context", "response_contract", "previous_error"}
        or type(raw["schema_version"]) is not int
        or raw["schema_version"] != 1
    ):
        raise InferenceError("INVALID_MODEL_INPUT")
    context = context_from_dict(raw["context"])
    schema = envelope_schema(context)
    # This exact mock template defines the counted input, including schema/chat wrapper.
    wire = safe_json({"messages": [{"role": "user", "content": payload}], "format": schema})
    return context, schema, wire


class OllamaStructuredModel:
    def __init__(self, profile, transport):
        if not isinstance(profile, LocalModelProfile):
            raise InferenceError("INVALID_MODEL_PROFILE")
        self.profile, self.transport = profile, transport
        self.model_id = profile.model_id
        self.tokenizer_revision = profile.tokenizer_revision
        self.input_microusd_per_million = profile.input_microusd_per_million
        self.output_microusd_per_million = profile.output_microusd_per_million
        self.binding = CounterBinding(
            profile.model_id, profile.tokenizer_revision, profile.template_revision
        )

    def count_tokens(self, payload):
        _, _, wire = model_input(payload)
        return self.binding.count(wire)

    def request(self, payload, max_output_tokens):
        _, schema, _ = model_input(payload)
        if type(max_output_tokens) is not int or not 1 <= max_output_tokens <= 65536:
            raise InferenceError("OUTPUT_TOKEN_LIMIT")
        return {
            "model": self.model_id,
            "messages": [{"role": "user", "content": payload}],
            "format": schema,
            "stream": False,
            "think": False,
            "options": {"num_predict": max_output_tokens},
        }

    def parse_response(self, payload, raw, max_output_tokens):
        response = decode_frame(raw) if isinstance(raw, str) else decode_frame(safe_json(raw))
        context, schema, _ = model_input(payload)
        count = self.count_tokens(payload)
        try:
            if response["model"] != self.model_id:
                raise InferenceError("MODEL_RESPONSE_MISMATCH")
            if response["done"] is not True or response["done_reason"] != "stop":
                raise InferenceError("PARTIAL_MODEL_OUTPUT")
            message = response["message"]
            if (
                set(message) - {"role", "content", "thinking"}
                or message["role"] != "assistant"
                or not isinstance(message["content"], str)
                or not isinstance(message.get("thinking", ""), str)
            ):
                raise InferenceError("UNSUPPORTED_MODEL_RESPONSE")
            used_input, used_output = response["prompt_eval_count"], response["eval_count"]
            if (
                type(used_input) is not int
                or used_input != count
                or type(used_output) is not int
                or not 0 <= used_output <= max_output_tokens
                or used_output
                != len((message["content"] + message.get("thinking", "")).encode("utf-8"))
            ):
                raise InferenceError("USAGE_MISMATCH")
            value = decode_frame(message["content"])
            validate_schema(value, schema)
            _, failures = validate_envelope(
                value, decode_frame(context.inputs.observation_json), context.knowledge, set()
            )
            if failures:
                raise InferenceError("EVIDENCE_OR_OBSERVATION_MISMATCH")
            return ModelReply(message["content"], used_input, used_output)
        except (KeyError, TypeError, AttributeError) as error:
            raise InferenceError("INVALID_MODEL_RESPONSE") from error

    def complete(self, payload, *, max_output_tokens, timeout_seconds):
        if (
            type(timeout_seconds) not in {int, float}
            or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 300
        ):
            raise InferenceError("MODEL_DEADLINE")
        deadline = time.monotonic() + timeout_seconds
        self.count_tokens(payload)  # A missing exact binding never reaches the transport.
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise InferenceError("MODEL_DEADLINE")
        try:
            raw = self.transport(self.request(payload, max_output_tokens), remaining)
        except InferenceError:
            raise
        except Exception:
            raise InferenceError("MOCK_CONNECTION_FAILURE") from None
        if time.monotonic() > deadline:
            raise InferenceError("MODEL_DEADLINE")
        return self.parse_response(payload, raw, max_output_tokens)


MOCK_MODES = {
    "normal",
    "invalid_json",
    "partial",
    "oversize_usage",
    "missing_usage",
    "disconnect",
    "hang",
    "exit",
    "secret",
    "stale",
    "invented_evidence",
    "promote_unknown",
    "bad_schema",
    "invalid_then_valid",
}


class MockChatTransport:
    """A test double producing seeded exploration proposals, not an LLM or quality benchmark."""

    def __init__(self, seed=0, mode="normal"):
        if mode not in MOCK_MODES:
            raise InferenceError("MOCK_MODE_NOT_ALLOWED")
        self.policy, self.mode, self.calls = ResearchPolicy("exploration", seed), mode, 0

    def __call__(self, request, timeout_seconds):
        import os
        import time

        self.calls += 1
        if self.mode == "disconnect":
            raise InferenceError("MOCK_CONNECTION_FAILURE")
        if self.mode == "hang":
            while True:
                time.sleep(1)
        if self.mode == "exit":
            os._exit(73)
        payload = request["messages"][0]["content"]
        context, schema, wire = model_input(payload)
        if digest(schema) != digest(request["format"]):
            raise InferenceError("SCHEMA_REQUEST_MISMATCH")
        envelope = self.policy.propose(context)
        if self.mode == "stale":
            envelope["proposal"]["observation_digest"] = "0" * 64
        elif self.mode == "invented_evidence":
            envelope["proposal"]["decision"]["evidence_refs"].append("invented:source")
        elif self.mode == "promote_unknown":
            envelope["proposal"]["decision"]["unknowns"] = []
            for claim in envelope["claims"]:
                if claim["status"] == "UNKNOWN":
                    claim["status"] = "GAME_VERIFIED"
        elif self.mode == "bad_schema":
            envelope["extra"] = True
        elif self.mode == "secret":
            envelope["proposal"]["decision"]["rationale"] = "sk-proj-" + "x" * 40
        content = safe_json(envelope)
        if self.mode == "invalid_json" or (self.mode == "invalid_then_valid" and self.calls == 1):
            content = '{"schema_version":1,"schema_version":2}'
        raw = {
            "model": request["model"],
            "done": True,
            "done_reason": "stop",
            "message": {"role": "assistant", "content": content},
            "prompt_eval_count": len(wire.encode("utf-8")),
            "eval_count": len(content.encode("utf-8")),
        }
        if self.mode == "partial" or raw["eval_count"] > request["options"]["num_predict"]:
            raw["done"], raw["done_reason"] = False, "length"
        if self.mode == "oversize_usage":
            raw["eval_count"] = request["options"]["num_predict"] + 1
        if self.mode == "missing_usage":
            del raw["eval_count"]
        return raw
