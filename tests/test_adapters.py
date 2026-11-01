import json
from unittest.mock import create_autospec

import pytest

from oni_ai.adapters import MockGameAdapter, ReadOnlyViolation, demo_adapter
from oni_ai.interfaces import PlanningAgent, PlanProposal, ReadOnlyGameAdapter


def test_mock_copies_input_and_returns_immutable_observations():
    payload = {"oni://colony/status": {"cycle": None}}
    adapter = MockGameAdapter(payload)
    payload["oni://colony/status"]["cycle"] = 123
    observation = adapter.read_resource("oni://colony/status")
    assert json.loads(observation.payload_json) == {"cycle": None}
    assert observation.provenance == "MOCK_SYNTHETIC_NOT_GAME_DATA"
    assert observation.observed_at == "UNKNOWN"


@pytest.mark.parametrize(
    "uri",
    [
        "http://localhost:8788/mcp/",
        "oni://game/load",
        "oni://unknown/read",
        "oni://colony/status?action=resume",
        "oni://tools/manifest?confirm=true",
    ],
)
def test_arbitrary_routing_rejected(uri):
    adapter = MockGameAdapter({uri: {"fixture": True}})
    with pytest.raises(ReadOnlyViolation):
        adapter.read_resource(uri)


def test_missing_fixture_is_not_invented():
    with pytest.raises(LookupError):
        MockGameAdapter({}).read_resource("oni://colony/status")


def test_ai_receives_observations_and_only_returns_proposal():
    adapter = create_autospec(ReadOnlyGameAdapter, instance=True, spec_set=True)
    adapter.read_resource.return_value = demo_adapter().read_resource("oni://colony/status")
    agent = create_autospec(PlanningAgent, instance=True, spec_set=True)
    proposal = PlanProposal("Review colony", "mock-phase0", (), ("Inspect knowledge",), ("all",))
    agent.propose.return_value = proposal
    knowledge = object()
    observations = (adapter.read_resource("oni://colony/status"),)
    assert agent.propose("Review colony", observations, knowledge) == proposal
    adapter.read_resource.assert_called_once_with("oni://colony/status")
    agent.propose.assert_called_once_with("Review colony", observations, knowledge)
    with pytest.raises(AttributeError):
        adapter.execute({"confirm": True})
