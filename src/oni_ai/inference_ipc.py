"""JSON file IPC and explicitly sanitized subprocesses for trusted offline model workers."""

import os
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from oni_ai.episode_knowledge import parse_queries
from oni_ai.inference_broker import BrokerLimits
from oni_ai.inference_contracts import MAX_AUDIT, MAX_FRAME, InferenceError, decode_frame, safe_json
from oni_ai.local_model import profile_for
from oni_ai.model_adapter import ModelLimits, ModelReply
from oni_ai.policy_process import PolicyProcessError, ProcessBudget


def retry_permission(operation, deadline):
    while True:
        try:
            return operation()
        except PermissionError:
            if time.monotonic() >= deadline:
                raise InferenceError("IPC_IO_FAILURE") from None
            time.sleep(0.005)


def atomic_json(path, value, *, deadline=None):
    payload = safe_json(value)
    pending = path.with_suffix(".pending")
    deadline = time.monotonic() + 1 if deadline is None else deadline

    def publish():
        with pending.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, path)

    try:
        retry_permission(publish, deadline)
    except OSError:
        raise InferenceError("IPC_IO_FAILURE") from None


def read_frame(path, *, deadline=None):
    deadline = time.monotonic() + 1 if deadline is None else deadline

    def read():
        if path.stat().st_size > MAX_FRAME:
            raise InferenceError("FRAME_LIMIT")
        return decode_frame(path.read_text("utf-8"))

    try:
        return retry_permission(read, deadline)
    except FileNotFoundError:
        raise
    except OSError:
        raise InferenceError("IPC_IO_FAILURE") from None
    except UnicodeError:
        raise InferenceError("INVALID_JSON") from None


class Mailbox:
    def __init__(self, directory):
        self.directory = Path(directory)

    def call(self, request, seconds, *, alive=None):
        if not isinstance(request, dict) or not isinstance(request.get("id"), str):
            raise InferenceError("INVALID_REQUEST_ID")
        deadline = time.monotonic() + seconds
        response = self.directory / "response.json"
        if response.exists():
            retry_permission(response.unlink, deadline)
        atomic_json(self.directory / "request.json", request, deadline=deadline)
        while True:
            if response.exists():
                try:
                    result = read_frame(response, deadline=deadline)
                except FileNotFoundError:
                    continue
                if (
                    not isinstance(result, dict)
                    or (
                        set(result) != {"id", "ok", "value"}
                        and set(result) != {"id", "ok", "error"}
                    )
                    or type(result.get("ok")) is not bool
                ):
                    raise InferenceError("IPC_PROTOCOL_ERROR")
                if result.get("id") != request["id"]:
                    raise InferenceError("IPC_RESPONSE_MISMATCH")
                if time.monotonic() > deadline:
                    raise InferenceError("IPC_TIMEOUT")
                return result
            if alive and not alive():
                raise InferenceError("IPC_WORKER_EXITED")
            if time.monotonic() >= deadline:
                raise InferenceError("IPC_TIMEOUT")
            time.sleep(0.005)


def clean_environment():
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in {"SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "TEMP", "TMP"}
    }
    environment["PATH"] = os.path.dirname(sys.executable)
    return environment


def mock_model_limits():
    # Bytes-as-tokens belongs to the artificial fixture only, not a recommended LLM budget.
    return ModelLimits(
        input_tokens=500000,
        output_tokens=65536,
        total_tokens=4_000_000,
        cost_microusd=10_000_000,
        attempts=2,
        seconds=5,
    )


class ManagedWorker:
    def __init__(self, root, role, configuration, startup=10):
        if role not in {"policy", "broker"}:
            raise InferenceError("ROLE_NOT_ALLOWED")
        self.directory = Path(root) / role
        self.directory.mkdir()
        atomic_json(self.directory / "config.json", configuration)
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-m",
                "oni_ai.inference_worker",
                role,
                str(Path(root).resolve()),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=clean_environment(),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.closed = False
        deadline = time.monotonic() + startup
        try:
            while not (self.directory / "ready.json").exists():
                if self.process.poll() is not None:
                    raise InferenceError("IPC_WORKER_EXITED")
                if time.monotonic() >= deadline:
                    raise InferenceError("IPC_TIMEOUT")
                time.sleep(0.005)
            if read_frame(self.directory / "ready.json") != {"ready": True}:
                raise InferenceError("IPC_PROTOCOL_ERROR")
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.closed:
            return
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=2)
        if self.process.poll() is None:
            raise RuntimeError("Inference worker cleanup was not verified")
        self.closed = True


class IPCStructuredModel:
    """StructuredModel proxy in a socket-blocked Policy; only count/generate messages exist."""

    def __init__(self, directory, model_key="offline", seconds=2):
        profile = profile_for(model_key)
        self.model_id, self.tokenizer_revision = profile.model_id, profile.tokenizer_revision
        self.input_microusd_per_million = profile.input_microusd_per_million
        self.output_microusd_per_million = profile.output_microusd_per_million
        self.mailbox, self.seconds, self.pending = Mailbox(directory), seconds, None

    def count_tokens(self, payload):
        request = {"id": uuid4().hex, "op": "count", "payload": payload}
        response = self.mailbox.call(request, self.seconds)
        if not response.get("ok"):
            raise InferenceError(response.get("error", "IPC_PROTOCOL_ERROR"))
        self.pending = payload, response["value"]["ticket"]
        return response["value"]["count"]

    def complete(self, payload, *, max_output_tokens, timeout_seconds):
        if self.pending is None or self.pending[0] != payload:
            raise InferenceError("COUNT_TICKET_MISMATCH")
        request = {
            "id": uuid4().hex,
            "op": "generate",
            "ticket": self.pending[1],
            "payload": payload,
            "max_output_tokens": max_output_tokens,
        }
        self.pending = None
        response = self.mailbox.call(request, min(self.seconds, timeout_seconds))
        if not response.get("ok"):
            raise InferenceError(response.get("error", "IPC_PROTOCOL_ERROR"))
        return ModelReply(**response["value"])


class BrokerPolicyHost:
    """Own Policy+broker lifecycles. The only exposed model is the offline test fixture."""

    def __init__(
        self,
        name="model-mock",
        seed=0,
        budget=None,
        *,
        broker_limits=None,
        model_limits=None,
        model_key="offline",
        mode="normal",
        policy_fault=None,
    ):
        if name not in {"exploration", "lookahead", "model-mock"}:
            raise InferenceError("POLICY_NOT_ALLOWED")
        self.budget = budget or ProcessBudget(call_seconds=5)
        self.broker_limits = broker_limits or BrokerLimits()
        self.model_limits = model_limits or mock_model_limits()
        profile_for(model_key)
        self.started, self.calls = time.monotonic(), 0
        self.directory = TemporaryDirectory(prefix="oni-inference-")
        self.workers, self.audit, self.errors = [], [], []
        self.cleanup_verified = False
        try:
            if name == "model-mock":
                self.workers.append(
                    ManagedWorker(
                        self.directory.name,
                        "broker",
                        {
                            "model_key": model_key,
                            "limits": asdict(self.broker_limits),
                            "seed": seed,
                            "mode": mode,
                            "call_seconds": self.budget.call_seconds,
                        },
                        self.budget.startup_seconds,
                    )
                )
            self.workers.append(
                ManagedWorker(
                    self.directory.name,
                    "policy",
                    {
                        "name": name,
                        "seed": seed,
                        "model_key": model_key,
                        "model_limits": asdict(self.model_limits),
                        "seconds": self.budget.call_seconds,
                        "fault": policy_fault,
                    },
                    self.budget.startup_seconds,
                )
            )
            self.mailbox = Mailbox(Path(self.directory.name) / "policy")
        except BaseException:
            self.close()
            raise

    def request(self, method, inputs, context=None):
        try:
            self.calls += 1
            if self.calls > self.budget.max_calls:
                raise InferenceError("HOST_CALL_BUDGET")
            remaining = self.budget.total_seconds - (time.monotonic() - self.started)
            if remaining <= 0:
                raise InferenceError("HOST_TIME_BUDGET")
            request = {"id": uuid4().hex, "op": method, "inputs": asdict(inputs)}
            if context:
                request.update(
                    knowledge=[asdict(e) for e in context.knowledge], unknowns=context.unknowns
                )
            if len(safe_json(request).encode("utf-8")) > self.budget.max_input_bytes:
                raise InferenceError("HOST_INPUT_BUDGET")
            response = self.mailbox.call(
                request,
                min(self.budget.call_seconds, remaining),
                alive=lambda: all(w.process.poll() is None for w in self.workers),
            )
            if len(safe_json(response).encode("utf-8")) > self.budget.max_output_bytes:
                raise InferenceError("HOST_OUTPUT_BUDGET")
            if response.get("ok") is not True:
                raise InferenceError(response.get("error", "IPC_PROTOCOL_ERROR"))
            return response["value"]
        except InferenceError as error:
            self.errors.append(error.code)
            self.close()
            reason = (
                "POLICY_TIMEOUT"
                if error.code in {"IPC_TIMEOUT", "HOST_TIME_BUDGET"}
                else ("WORKER_EXITED" if error.code == "IPC_WORKER_EXITED" else "POLICY_EXCEPTION")
            )
            raise PolicyProcessError(reason) from error

    def queries(self, inputs):
        return parse_queries(self.request("queries", inputs))

    def propose(self, context):
        return self.request("propose", context.inputs, context)

    def close(self):
        if self.cleanup_verified:
            return
        for worker in reversed(self.workers):
            worker.close()
        paths = sorted((Path(self.directory.name) / "broker").glob("audit-*.json"))
        if sum(path.stat().st_size for path in paths) > MAX_AUDIT:
            raise InferenceError("AUDIT_LIMIT")
        self.audit = [read_frame(path) for path in paths]
        retry_permission(self.directory.cleanup, time.monotonic() + 1)
        self.cleanup_verified = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
