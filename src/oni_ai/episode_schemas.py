"""Portable schema definitions for the anonymized Policy boundary (Phase 1 remains intact)."""

from copy import deepcopy

from oni_ai.schemas import experiment_schemas


def policy_schemas() -> dict:
    definitions = deepcopy(experiment_schemas()["$defs"])
    observation = definitions["observation"]
    del observation["properties"]["fixture_id"]
    observation["required"].remove("fixture_id")
    observation["properties"]["schema_version"] = {"type": "integer", "const": 2}
    observation["properties"]["observation_digest"] = {
        "type": "string",
        "pattern": "^[0-9a-f]{64}$",
    }
    observation["required"].append("observation_digest")
    definitions["action"]["properties"]["dry_run"] = {"type": "boolean", "const": False}
    definitions["decision"]["properties"]["evidence_refs"]["minItems"] = 1
    definitions["proposal"] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "observation_digest", "decision"],
        "properties": {
            "schema_version": {"type": "integer", "const": 1},
            "observation_digest": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "decision": {"$ref": "#/$defs/decision"},
        },
    }
    definitions["query"] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["kind", "query"],
        "properties": {
            "kind": {"enum": ["model", "building", "rule"]},
            "query": {"type": "string", "minLength": 1, "maxLength": 4000},
            "game_version": {"type": "string", "default": "UNKNOWN"},
            "dlc_scope": {"type": "string", "default": "UNKNOWN"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 32, "default": 32},
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Offline Policy proposals v1 and anonymous observations v2",
        "$defs": definitions,
    }
