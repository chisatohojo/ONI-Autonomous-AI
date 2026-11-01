"""JSON Schema 2020-12 exports for the public synthetic observation/action boundary."""

from oni_ai.contracts import ACTION_KINDS, MODEL_VERSION, PROVENANCE, RESOURCE_KEYS


def experiment_schemas() -> dict:
    number = {"type": "number", "minimum": 0}
    process = {
        "type": "object",
        "additionalProperties": False,
        "required": ["enabled", "blocked", "requires_research", "inputs", "outputs"],
        "properties": {
            "enabled": {"type": "boolean"},
            "blocked": {"type": "boolean"},
            "requires_research": number,
            **{
                field: {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {r: number for r in sorted(RESOURCE_KEYS)},
                }
                for field in ("inputs", "outputs")
            },
        },
    }
    action = {
        "type": "object",
        "additionalProperties": False,
        "required": ["action_id", "context_id", "expected_tick", "kind"],
        "properties": {
            "schema_version": {"const": 1, "type": "integer", "default": 1},
            "action_id": {"type": "string", "minLength": 1, "maxLength": 4000},
            "context_id": {"type": "string", "minLength": 1, "maxLength": 4000},
            "expected_tick": {"type": "integer", "minimum": 0},
            "kind": {"enum": sorted(ACTION_KINDS)},
            "target": {"type": ["string", "null"], "default": None},
            "enabled": {"type": ["boolean", "null"], "default": None},
            "ticks": {"type": "integer", "minimum": 1, "maximum": 10, "default": 1},
            "dry_run": {"type": "boolean", "default": False},
        },
        "allOf": [
            {
                "if": {"properties": {"kind": {"const": "wait"}}},
                "then": {"properties": {"target": {"type": "null"}, "enabled": {"type": "null"}}},
                "else": {
                    "required": ["target"],
                    "properties": {
                        "target": {"type": "string", "minLength": 1, "maxLength": 4000},
                        "ticks": {"const": 1},
                    },
                },
            },
            {
                "if": {"properties": {"kind": {"const": "set_process"}}},
                "then": {"required": ["enabled"], "properties": {"enabled": {"type": "boolean"}}},
            },
            {
                "if": {"properties": {"kind": {"const": "clear_blockage"}}},
                "then": {"properties": {"enabled": {"type": "null"}}},
            },
        ],
    }
    properties = {
        "schema_version": {"type": "integer", "const": 1},
        "provenance": {"const": PROVENANCE},
        "model_version": {"const": MODEL_VERSION},
        "game_version": {"const": "UNKNOWN"},
        "dlc_scope": {"const": "UNKNOWN"},
        "fixture_id": {"type": "string"},
        "context_id": {"type": "string"},
        "tick": {"type": "integer", "minimum": 0},
        "units": {"const": "arbitrary_synthetic_units_per_tick_NOT_ONI"},
        "resources": {
            "type": "object",
            "additionalProperties": False,
            "required": sorted(RESOURCE_KEYS),
            "properties": {
                r: {"type": ["number", "null"], "minimum": 0} for r in sorted(RESOURCE_KEYS)
            },
        },
        "processes": {"type": "object", "maxProperties": 20, "additionalProperties": process},
        "alerts": {"type": "array", "items": {"type": "string"}},
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "ONI AI synthetic experiment contracts v1 (not OniMcp wire schemas)",
        "$defs": {
            "action": action,
            "observation": {
                "type": "object",
                "additionalProperties": False,
                "required": list(properties),
                "properties": properties,
            },
            "decision": {
                "type": "object",
                "additionalProperties": False,
                "required": ["action", "rationale"],
                "properties": {
                    "action": {"$ref": "#/$defs/action"},
                    "rationale": {"type": "string", "minLength": 1, "maxLength": 4000},
                    **{
                        key: {
                            "type": "array",
                            "maxItems": 100,
                            "items": {"type": "string", "minLength": 1, "maxLength": 4000},
                        }
                        for key in ("evidence_refs", "unknowns")
                    },
                },
            },
        },
    }
