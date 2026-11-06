"""Fail-closed JSON, secret checks and a small explicit schema subset for mock inference."""

import math
import re
from dataclasses import dataclass

from oni_ai.contracts import strict_json
from oni_ai.episode_knowledge import Evidence
from oni_ai.evaluation import _canonical
from oni_ai.policy import MemoryEntry, PolicyContext, PolicyInput

MAX_FRAME = 1_000_000
MAX_AUDIT = 20_000_000


class InferenceError(ValueError):
    """Only a controlled code is exposed across process and log boundaries."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code

    @property
    def retryable(self):
        return self.code in {
            "MOCK_CONNECTION_FAILURE",
            "INVALID_JSON",
            "PARTIAL_MODEL_OUTPUT",
            "SCHEMA_OUTPUT_MISMATCH",
            "EVIDENCE_OR_OBSERVATION_MISMATCH",
        }


def safe_json(value):
    encoded = _canonical(value)
    if len(encoded.encode("utf-8")) > MAX_FRAME:
        raise InferenceError("FRAME_LIMIT")
    patterns = (
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        r"\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{25,})",
        r"https?://[^\s/:]+:[^\s/@]+@",
        r'(?i)"(?:api_key|apikey|access_token|password|authorization|client_secret)"\s*:',
        r"(?i)[A-Z]:[\\/]Users[\\/][^\s<>]+",
    )

    def scan(item, depth=0):
        if depth > 50:
            raise InferenceError("FRAME_LIMIT")
        if isinstance(item, str):
            if any(re.search(pattern, item) for pattern in patterns):
                raise InferenceError("SECRET_OR_PRIVATE_DATA")
        elif isinstance(item, dict):
            for key, child in item.items():
                if key.casefold() in {
                    "api_key",
                    "apikey",
                    "access_token",
                    "password",
                    "authorization",
                    "client_secret",
                }:
                    raise InferenceError("SECRET_OR_PRIVATE_DATA")
                scan(key, depth + 1)
                scan(child, depth + 1)
        elif isinstance(item, (list, tuple)):
            for child in item:
                scan(child, depth + 1)

    scan(value)
    return encoded


def decode_frame(text):
    try:
        if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_FRAME:
            raise InferenceError("FRAME_LIMIT")
        value = strict_json(text)
        safe_json(value)
        return value
    except InferenceError:
        raise
    except (ValueError, TypeError, RecursionError, OverflowError) as error:
        raise InferenceError("INVALID_JSON") from error


def context_from_dict(raw):
    try:
        inputs = raw["inputs"]
        context = PolicyContext(
            PolicyInput(
                inputs["observation_json"],
                inputs["objective_json"],
                tuple(
                    MemoryEntry(**{**m, "failures": tuple(m["failures"])}) for m in inputs["memory"]
                ),
            ),
            tuple(Evidence(**item) for item in raw["knowledge"]),
            tuple(raw["unknowns"]),
        )
        if len(context.inputs.memory) > 200 or len(context.knowledge) > 64:
            raise ValueError("Bounded context required")
        decode_frame(context.inputs.observation_json)
        decode_frame(context.inputs.objective_json)
        return context
    except (KeyError, TypeError, ValueError) as error:
        raise InferenceError("INVALID_CONTEXT") from error


def object_schema(properties):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def value_schema(value):
    if isinstance(value, dict):
        return object_schema({k: value_schema(v) for k, v in value.items()})
    if isinstance(value, list):
        shapes = {_canonical(value_schema(v)): value_schema(v) for v in value}
        item = (
            {"type": "null"}
            if not shapes
            else (
                next(iter(shapes.values()))
                if len(shapes) == 1
                else {"anyOf": list(shapes.values())}
            )
        )
        return {"type": "array", "items": item, "maxItems": 100}
    kind = {str: "string", bool: "boolean", int: "integer", float: "number", type(None): "null"}
    if type(value) not in kind:
        raise InferenceError("SCHEMA_UNSUPPORTED")
    return {"type": kind[type(value)]}


def envelope_schema(context):
    text = {"type": "string", "minLength": 1, "maxLength": 4000}
    actions = []
    for kind in ("wait", "set_process", "clear_blockage"):
        actions.append(
            object_schema(
                {
                    "schema_version": {"type": "integer", "const": 1},
                    "action_id": text,
                    "context_id": text,
                    "expected_tick": {"type": "integer", "minimum": 0},
                    "kind": {"type": "string", "enum": [kind]},
                    "target": {"type": "null"} if kind == "wait" else text,
                    "enabled": {"type": "boolean"} if kind == "set_process" else {"type": "null"},
                    "ticks": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 10 if kind == "wait" else 1,
                    },
                    "dry_run": {"type": "boolean", "const": False},
                }
            )
        )
    references = {"type": "array", "items": text, "maxItems": 100}
    decision = object_schema(
        {
            "action": {"anyOf": actions},
            "rationale": text,
            "evidence_refs": {**references, "minItems": 1},
            "unknowns": references,
        }
    )
    claims = [
        object_schema(
            {
                "evidence_id": {"type": "string", "enum": [e.evidence_id]},
                "pointer": {"type": "string", "enum": [""]},
                "value": value_schema(strict_json(e.value_json)),
                "status": {"type": "string", "enum": [e.status]},
            }
        )
        for e in context.knowledge
    ]
    if not claims:
        raise InferenceError("NO_EVIDENCE")
    schema = object_schema(
        {
            "schema_version": {"type": "integer", "const": 1},
            "proposal": object_schema(
                {
                    "schema_version": {"type": "integer", "const": 1},
                    "observation_digest": {"type": "string", "minLength": 64, "maxLength": 64},
                    "decision": decision,
                }
            ),
            "claims": {"type": "array", "minItems": 1, "maxItems": 64, "items": {"anyOf": claims}},
        }
    )
    check_schema(schema)
    return schema


def check_schema(schema):
    allowed = {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "anyOf",
        "minItems",
        "maxItems",
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
        "enum",
        "const",
    }
    count = 0

    def walk(node, depth):
        nonlocal count
        count += 1
        if count > 4000 or depth > 20 or not isinstance(node, dict) or not node:
            raise InferenceError("SCHEMA_LIMIT")
        if set(node) - allowed:
            raise InferenceError("SCHEMA_UNSUPPORTED")
        if "anyOf" in node:
            if (
                set(node) != {"anyOf"}
                or not isinstance(node["anyOf"], list)
                or not 1 <= len(node["anyOf"]) <= 64
            ):
                raise InferenceError("SCHEMA_UNSUPPORTED")
            for branch in node["anyOf"]:
                walk(branch, depth + 1)
            return
        kind = node.get("type")
        if kind not in {"object", "array", "string", "integer", "number", "boolean", "null"}:
            raise InferenceError("SCHEMA_UNSUPPORTED")
        by_kind = {
            "object": {"properties", "required", "additionalProperties"},
            "array": {"items", "minItems", "maxItems"},
            "string": {"minLength", "maxLength"},
            "integer": {"minimum", "maximum"},
            "number": {"minimum", "maximum"},
            "boolean": set(),
            "null": set(),
        }
        if set(node) - ({"type", "enum", "const"} | by_kind[kind]):
            raise InferenceError("SCHEMA_UNSUPPORTED")
        if kind == "object":
            properties = node.get("properties")
            if (
                not isinstance(properties, dict)
                or node.get("additionalProperties") is not False
                or not isinstance(node.get("required"), list)
                or len(node["required"]) != len(set(node["required"]))
                or set(node["required"]) != set(properties)
            ):
                raise InferenceError("SCHEMA_UNSUPPORTED")
            for child in properties.values():
                walk(child, depth + 1)
        if kind == "array":
            walk(node.get("items"), depth + 1)
        if "enum" in node and (not isinstance(node["enum"], list) or not node["enum"]):
            raise InferenceError("SCHEMA_UNSUPPORTED")
        for key in ("minItems", "maxItems", "minLength", "maxLength", "minimum", "maximum"):
            if key in node and (
                type(node[key]) not in {int, float} or not math.isfinite(node[key]) or node[key] < 0
            ):
                raise InferenceError("SCHEMA_UNSUPPORTED")
            if key in node and key not in {"minimum", "maximum"} and type(node[key]) is not int:
                raise InferenceError("SCHEMA_UNSUPPORTED")
        for lower, upper in (
            ("minItems", "maxItems"),
            ("minLength", "maxLength"),
            ("minimum", "maximum"),
        ):
            if lower in node and upper in node and node[lower] > node[upper]:
                raise InferenceError("SCHEMA_UNSUPPORTED")

    walk(schema, 0)
    if len(_canonical(schema).encode("utf-8")) > 262144:
        raise InferenceError("SCHEMA_LIMIT")


def validate_schema(value, schema):
    def valid(item, node):
        if "anyOf" in node:
            return any(valid(item, branch) for branch in node["anyOf"])
        kind = node["type"]
        types = {
            "object": dict,
            "array": list,
            "string": str,
            "integer": int,
            "boolean": bool,
            "null": type(None),
        }
        if kind == "number":
            if type(item) not in {int, float} or not math.isfinite(item):
                return False
        elif type(item) is not types[kind]:
            return False
        if "enum" in node and _canonical(item) not in {_canonical(v) for v in node["enum"]}:
            return False
        if "const" in node and _canonical(item) != _canonical(node["const"]):
            return False
        if kind == "object":
            return set(item) == set(node["properties"]) and all(
                valid(item[k], s) for k, s in node["properties"].items()
            )
        if kind in {"string", "array"}:
            lower, upper = (
                ("minLength", "maxLength") if kind == "string" else ("minItems", "maxItems")
            )
            if not node.get(lower, 0) <= len(item) <= node.get(upper, MAX_FRAME):
                return False
            return kind == "string" or all(valid(v, node["items"]) for v in item)
        if kind in {"integer", "number"}:
            return node.get("minimum", -math.inf) <= item <= node.get("maximum", math.inf)
        return True

    check_schema(schema)
    if not valid(value, schema):
        raise InferenceError("SCHEMA_OUTPUT_MISMATCH")


@dataclass(frozen=True)
class CounterBinding:
    model_id: str
    tokenizer_revision: str
    template_revision: str

    def count(self, wire):
        if (self.model_id, self.tokenizer_revision, self.template_revision) != (
            "offline-byte-model/v1",
            "mock-utf8-byte/1",
            "mock-chat/1",
        ):
            raise InferenceError("EXACT_COUNTER_UNAVAILABLE")
        # An exact definition of this artificial model only, never an LLM token estimate.
        return len(wire.encode("utf-8"))
