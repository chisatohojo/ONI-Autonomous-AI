"""Offline MCP message validation only; no HTTP client, socket or tool executor."""

from importlib.resources import files

from oni_ai import __version__
from oni_ai.contracts import strict_json

SUPPORTED_PROTOCOL = "2025-11-25"
ONIMCP_COMMIT = "14c08591cbd0bf66cd0f53b37bfb498bdef4abf6"


def operation_catalog() -> dict:
    catalog = strict_json(
        files("oni_ai").joinpath("data/operation_catalog.json").read_text("utf-8")
    )
    if (
        catalog["source_commit"] != ONIMCP_COMMIT
        or catalog["protocol_version"] != SUPPORTED_PROTOCOL
    ):
        raise ValueError("Unknown operation evidence version")
    return catalog


def initialize_message(request_id: int | str) -> dict:
    if type(request_id) not in {int, str}:
        raise ValueError("MCP request ID must be a string or integer")
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "initialize",
        "params": {
            "protocolVersion": SUPPORTED_PROTOCOL,
            "capabilities": {},
            "clientInfo": {"name": "oni-ai-offline-codec", "version": __version__},
        },
    }


def rpc_result(text: str, request_id: int | str) -> dict:
    if type(request_id) not in {int, str}:
        raise ValueError("MCP request ID must be a string or integer")
    response = strict_json(text)
    if (
        not isinstance(response, dict)
        or response.get("jsonrpc") != "2.0"
        or type(response.get("id")) is not type(request_id)
        or response.get("id") != request_id
    ):
        raise ValueError("Invalid JSON-RPC envelope or request ID")
    if "error" in response or "result" not in response:
        raise ValueError("JSON-RPC error or missing result")
    result = response["result"]
    if not isinstance(result, dict) or result.get("isError") or result.get("error"):
        raise ValueError("Tool/resource error or invalid result object")
    return result


def initialize_session(text: str, request_id: int | str, headers: dict[str, str]) -> str:
    result = rpc_result(text, request_id)
    if result.get("protocolVersion") != SUPPORTED_PROTOCOL:
        raise ValueError("Unsupported protocol; documentation discrepancy remains unresolved")
    normalized = {key.lower(): value for key, value in headers.items()}
    session = normalized.get("mcp-session-id")
    if not isinstance(session, str) or not session.strip():
        raise ValueError("Expected legacy Mcp-Session-Id")
    if normalized.get("mcp-protocol-version", SUPPORTED_PROTOCOL) != SUPPORTED_PROTOCOL:
        raise ValueError("Protocol header mismatch")
    return session


def json_resource(text: str, request_id: int | str, expected_uri: str) -> object:
    result = rpc_result(text, request_id)
    contents = result.get("contents")
    if not isinstance(contents, list) or len(contents) != 1:
        raise ValueError("Expected exactly one resource content object")
    item = contents[0]
    if (
        not isinstance(item, dict)
        or item.get("uri") != expected_uri
        or item.get("mimeType") != "application/json"
        or not isinstance(item.get("text"), str)
    ):
        raise ValueError("Unreviewed resource URI, MIME type or content")
    payload = strict_json(item["text"])
    if isinstance(payload, dict) and (payload.get("error") or payload.get("isError")):
        raise ValueError("Resource content reports an error")
    return payload
