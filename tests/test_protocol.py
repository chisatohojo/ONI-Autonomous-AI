import json
from importlib.resources import files

import pytest

from oni_ai.contracts import ACTION_KINDS
from oni_ai.protocol import (
    ONIMCP_COMMIT,
    initialize_message,
    initialize_session,
    json_resource,
    operation_catalog,
    rpc_result,
)
from oni_ai.schemas import experiment_schemas
from oni_ai.simulation import SyntheticEnvironment, load_fixture


def test_static_code_contract_and_schema_exports_stay_separate():
    catalog = operation_catalog()
    assert catalog["source_commit"] == ONIMCP_COMMIT
    assert catalog["documentation_discrepancy"] == "UNRESOLVED"
    assert all(op["live_execution_allowed"] is False for op in catalog["operations"])
    direct = next(op for op in catalog["operations"] if op["operation_id"] == "direct_build_area")
    assert direct["support"] == "DIRECT_PUBLIC_ROUTE_FORBIDDEN"
    schema = experiment_schemas()
    stored = json.loads(files("oni_ai").joinpath("data/experiment_schemas.json").read_text("utf-8"))
    assert schema == stored
    assert set(schema["$defs"]["action"]["properties"]["kind"]["enum"]) == ACTION_KINDS
    observation = SyntheticEnvironment(load_fixture("normal")).observe()
    assert set(observation) == set(schema["$defs"]["observation"]["required"])


@pytest.mark.parametrize("version", ["2025-11-25", "2025-06-18", "2026-07-28"])
def test_initialize_accepts_only_fixed_code_protocol(version):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": version}})
    assert initialize_message(1)["params"]["protocolVersion"] == "2025-11-25"
    if version == "2025-11-25":
        assert (
            initialize_session(body, 1, {"Mcp-Session-Id": "synthetic-session"})
            == "synthetic-session"
        )
        with pytest.raises(ValueError):
            initialize_session(body, 1, {})
    else:
        with pytest.raises(ValueError):
            initialize_session(body, 1, {"Mcp-Session-Id": "synthetic-session"})


@pytest.mark.parametrize(
    "envelope",
    [
        {"jsonrpc": "2.0", "id": 1, "error": {"code": -32022}},
        {"jsonrpc": "2.0", "id": True, "result": {}},
        {"jsonrpc": "2.0", "id": 1, "result": {"isError": True}},
        [{"jsonrpc": "2.0", "id": 1, "result": {}}],
    ],
)
def test_error_envelopes_are_never_success(envelope):
    with pytest.raises(ValueError):
        rpc_result(json.dumps(envelope), 1)


def test_resource_json_uri_mime_and_content_errors():
    uri = "oni://colony/status"
    item = {"uri": uri, "mimeType": "application/json", "text": '{"fixture":true}'}

    def body():
        return json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"contents": [item]}})

    assert json_resource(body(), 2, uri) == {"fixture": True}
    for change in [
        {"text": '{"error":true}'},
        {"text": "cycle: 1"},
        {"uri": "oni://unreviewed"},
        {"mimeType": "text/plain"},
    ]:
        saved = dict(item)
        item.update(change)
        with pytest.raises(ValueError):
            json_resource(body(), 2, uri)
        item.clear()
        item.update(saved)
