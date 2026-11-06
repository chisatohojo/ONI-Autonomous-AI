"""Internal allowlisted offline worker entrypoint; never accepts commands or URLs."""

import os
import socket
import sys
import time
from pathlib import Path

from oni_ai.episode_knowledge import query_records
from oni_ai.inference_broker import BrokerLimits, InferenceBroker
from oni_ai.inference_contracts import MAX_AUDIT, InferenceError, context_from_dict, safe_json
from oni_ai.inference_ipc import IPCStructuredModel, atomic_json, read_frame
from oni_ai.model_adapter import BudgetedModelAdapter, ModelLimits
from oni_ai.research_policy import ResearchPolicy


def blocked(*args, **kwargs):
    raise InferenceError("SOCKET_BLOCKED")


def serve(role, root):
    socket.socket = socket.create_connection = socket.getaddrinfo = blocked
    directory = root / role
    config = read_frame(directory / "config.json")
    broker = policy = None
    if role == "broker":
        audit_size = audit_sequence = 0

        def emit(record):
            nonlocal audit_size, audit_sequence
            encoded = safe_json(record)
            if audit_size + len(encoded.encode("utf-8")) > MAX_AUDIT:
                raise InferenceError("AUDIT_LIMIT")
            atomic_json(directory / f"audit-{audit_sequence:04d}.json", record)
            audit_size += len(encoded.encode("utf-8"))
            audit_sequence += 1

        broker = InferenceBroker(
            config["model_key"],
            BrokerLimits(**config["limits"]),
            seed=config["seed"],
            mode=config["mode"],
            emit=emit,
            call_seconds=config["call_seconds"],
        )
    else:
        if config["name"] == "model-mock":
            policy = BudgetedModelAdapter(
                IPCStructuredModel(root / "broker", config["model_key"], config["seconds"]),
                ModelLimits(**config["model_limits"]),
            )
        else:
            policy = ResearchPolicy(config["name"], config["seed"])
    atomic_json(directory / "ready.json", {"ready": True})
    while True:
        path = directory / "request.json"
        if not path.exists():
            time.sleep(0.005)
            continue
        request = read_frame(path)
        path.unlink()
        try:
            if role == "broker":
                response = broker.handle(request)
            else:
                if config["fault"] == "exit":
                    os._exit(74)
                if config["fault"] == "hang":
                    while True:
                        time.sleep(1)
                if config["fault"] == "network":
                    socket.create_connection(("127.0.0.1", 1))
                if config["fault"] == "environment":
                    response = {"ok": True, "value": sorted(os.environ)}
                elif request.get("op") in {"queries", "propose"}:
                    expected = {"id", "op", "inputs"} | (
                        {"knowledge", "unknowns"} if request["op"] == "propose" else set()
                    )
                    if set(request) != expected:
                        raise InferenceError("RPC_NOT_ALLOWED")
                    raw = {
                        "inputs": request["inputs"],
                        "knowledge": request.get("knowledge", []),
                        "unknowns": request.get("unknowns", []),
                    }
                    context = context_from_dict(raw)
                    value = (
                        query_records(policy.queries(context.inputs))
                        if request["op"] == "queries"
                        else policy.propose(context)
                    )
                    response = {"ok": True, "value": value}
                else:
                    raise InferenceError("RPC_NOT_ALLOWED")
            response = {"id": request["id"], **response}
            safe_json(response)
        except InferenceError as error:
            response = {"id": request.get("id"), "ok": False, "error": error.code}
        except Exception:
            response = {"id": request.get("id"), "ok": False, "error": "POLICY_ERROR"}
        atomic_json(directory / "response.json", response)


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in {"policy", "broker"}:
        raise SystemExit(2)
    try:
        serve(sys.argv[1], Path(sys.argv[2]))
    except BaseException:
        raise SystemExit(3) from None
