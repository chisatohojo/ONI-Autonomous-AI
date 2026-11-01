"""In-memory resource fixture adapter. This module does not open sockets or processes."""

import json
from collections.abc import Mapping
from copy import deepcopy

from oni_ai.interfaces import Observation

ALLOWED_RESOURCES = frozenset(
    {
        "oni://tools/manifest",
        "oni://colony/status",
        "oni://buildings/defs",
    }
)


class ReadOnlyViolation(ValueError):
    """Resource is outside the reviewed observation surface."""


class MockGameAdapter:
    """A deliberately small allowlist; arbitrary oni:// query routing is not accepted."""

    def __init__(self, fixtures: Mapping[str, object]):
        self._fixtures = deepcopy(dict(fixtures))

    def read_resource(self, uri: str) -> Observation:
        if uri not in ALLOWED_RESOURCES:
            raise ReadOnlyViolation(f"Resource is not allowlisted: {uri}")
        if uri not in self._fixtures:
            raise LookupError(f"No mock fixture for {uri}")
        return Observation(
            resource_uri=uri,
            payload_json=json.dumps(self._fixtures[uri], ensure_ascii=False, allow_nan=False),
            observed_at="UNKNOWN",
            game_version="UNKNOWN",
            dlc_scope="UNKNOWN",
            context_id="mock-phase0",
            provenance="MOCK_SYNTHETIC_NOT_GAME_DATA",
        )


def demo_adapter() -> MockGameAdapter:
    return MockGameAdapter(
        {
            "oni://tools/manifest": {
                "fixture": True,
                "notice": "Synthetic local contract, not an OniMcp manifest",
                "mode": "READ_ONLY_MOCK",
                "resources": sorted(ALLOWED_RESOURCES),
            },
            "oni://colony/status": {
                "fixture": True,
                "cycle": None,
                "duplicants": None,
                "isPaused": None,
            },
            "oni://buildings/defs": {"fixture": True, "buildings": []},
        }
    )
