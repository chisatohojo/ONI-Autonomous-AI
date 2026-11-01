"""Spawned, JSON-only trusted Policy worker with terminate/kill/join deadlines."""

import multiprocessing
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from oni_ai.contracts import finite_nonnegative, strict_json
from oni_ai.episode_knowledge import Evidence, parse_queries, query_records
from oni_ai.evaluation import _canonical
from oni_ai.policy import MemoryEntry, PolicyContext, PolicyInput
from oni_ai.research_policy import ResearchPolicy


@dataclass(frozen=True)
class ProcessBudget:
    call_seconds: float = 2.0
    total_seconds: float = 60.0
    startup_seconds: float = 10.0
    max_calls: int = 400
    max_input_bytes: int = 1_000_000
    max_output_bytes: int = 65_536

    def __post_init__(self):
        for value in (self.call_seconds, self.total_seconds, self.startup_seconds):
            finite_nonnegative(value)
            if not 0.01 <= value <= 300:
                raise ValueError("Time budgets must be 0.01..300 seconds")
        for value, upper in (
            (self.max_calls, 400),
            (self.max_input_bytes, 2_000_000),
            (self.max_output_bytes, 1_000_000),
        ):
            if type(value) is not int or not 1 <= value <= upper:
                raise ValueError("Invalid process count/byte budget")


class PolicyProcessError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _inputs(raw):
    return PolicyInput(
        raw["observation_json"],
        raw["objective_json"],
        tuple(
            MemoryEntry(**{**item, "failures": tuple(item["failures"])}) for item in raw["memory"]
        ),
    )


def _worker(directory, request_ready, response_ready, factory, name, seed, max_input, max_output):
    # spawn does not inherit pytest's monkeypatch. Explicitly block sockets in the child too.
    import socket

    def blocked(*args, **kwargs):
        raise RuntimeError("Offline Policy worker forbids network")

    socket.socket = socket.create_connection = socket.getaddrinfo = blocked
    try:
        policy = factory(name, seed)
        request_path = Path(directory) / "request.json"
        response_path = Path(directory) / "response.json"
        response_path.write_bytes(b'{"ready":true}')
        response_ready.set()
        while True:
            request_ready.wait()
            request_ready.clear()
            if request_path.stat().st_size > max_input:
                return
            request = strict_json(request_path.read_text("utf-8"))
            try:
                if request["method"] == "queries":
                    value = query_records(policy.queries(_inputs(request["inputs"])))
                elif request["method"] == "propose":
                    value = policy.propose(
                        PolicyContext(
                            _inputs(request["inputs"]),
                            tuple(Evidence(**item) for item in request["knowledge"]),
                            tuple(request["unknowns"]),
                        )
                    )
                else:
                    raise ValueError("Unsupported Policy method")
                payload = _canonical({"ok": True, "value": value}).encode("utf-8")
                if len(payload) > max_output:
                    payload = b'{"ok":false,"error":"OUTPUT_BUDGET"}'
            except Exception:
                # Exception messages and arbitrary worker output never enter receipts.
                payload = b'{"ok":false,"error":"POLICY_EXCEPTION"}'
            response_path.write_bytes(payload)
            response_ready.set()
    except Exception:
        pass


class ProcessPolicy:
    """A process limit for trusted code, not an OS sandbox or descendant-process supervisor."""

    def __init__(self, name, seed=0, budget=None, *, factory=ResearchPolicy):
        self.budget = budget or ProcessBudget()
        if not isinstance(self.budget, ProcessBudget):
            raise ValueError("Validated process budget required")
        self.calls = 0
        self.started = time.monotonic()
        self.cleanup_verified = False
        context = multiprocessing.get_context("spawn")
        self.directory = TemporaryDirectory(prefix="oni-policy-")
        self.request_ready, self.response_ready = context.Event(), context.Event()
        self.process = context.Process(
            target=_worker,
            args=(
                self.directory.name,
                self.request_ready,
                self.response_ready,
                factory,
                name,
                seed,
                self.budget.max_input_bytes,
                self.budget.max_output_bytes,
            ),
            daemon=True,
        )
        try:
            self.process.start()
        except BaseException:
            self.process.close()
            self.directory.cleanup()
            raise
        self.pid = self.process.pid
        try:
            ready = self._receive(min(self.budget.startup_seconds, self.budget.total_seconds))
            if ready != {"ready": True}:
                raise PolicyProcessError("WORKER_PROTOCOL_ERROR")
        except BaseException:
            self.close()
            raise

    def _receive(self, seconds):
        try:
            deadline = time.monotonic() + seconds
            while not self.response_ready.wait(max(0, min(0.05, deadline - time.monotonic()))):
                if not self.process.is_alive():
                    raise PolicyProcessError("WORKER_EXITED")
                if time.monotonic() >= deadline:
                    raise PolicyProcessError("POLICY_TIMEOUT")
            self.response_ready.clear()
            if time.monotonic() > deadline:
                raise PolicyProcessError("POLICY_TIMEOUT")
            path = Path(self.directory.name) / "response.json"
            if path.stat().st_size > self.budget.max_output_bytes:
                raise PolicyProcessError("OUTPUT_BUDGET")
            return strict_json(path.read_text("utf-8"))
        except (EOFError, OSError, UnicodeError, ValueError) as error:
            raise PolicyProcessError("WORKER_PROTOCOL_ERROR") from error

    def request(self, method, inputs, context=None):
        try:
            self.calls += 1
            if self.calls > self.budget.max_calls:
                raise PolicyProcessError("CALL_BUDGET")
            remaining = self.budget.total_seconds - (time.monotonic() - self.started)
            if remaining <= 0:
                raise PolicyProcessError("TIME_BUDGET")
            request = {"method": method, "inputs": asdict(inputs)}
            if context:
                request.update(
                    knowledge=[asdict(e) for e in context.knowledge], unknowns=context.unknowns
                )
            payload = _canonical(request).encode("utf-8")
            if len(payload) > self.budget.max_input_bytes:
                raise PolicyProcessError("INPUT_BUDGET")
            # Files + events avoid an unbounded send/partial recv on a pipe.
            (Path(self.directory.name) / "request.json").write_bytes(payload)
            self.request_ready.set()
            remaining = self.budget.total_seconds - (time.monotonic() - self.started)
            response = self._receive(min(self.budget.call_seconds, remaining))
            if not isinstance(response, dict) or type(response.get("ok")) is not bool:
                raise PolicyProcessError("WORKER_PROTOCOL_ERROR")
            if not response["ok"]:
                code = response.get("error")
                raise PolicyProcessError(
                    code
                    if code in {"OUTPUT_BUDGET", "POLICY_EXCEPTION"}
                    else "WORKER_PROTOCOL_ERROR"
                )
            return response["value"]
        except PolicyProcessError:
            self.close()
            raise
        except (OSError, EOFError, KeyError) as error:
            self.close()
            raise PolicyProcessError("WORKER_PROTOCOL_ERROR") from error

    def queries(self, inputs):
        return parse_queries(self.request("queries", inputs))

    def propose(self, context):
        return self.request("propose", context.inputs, context)

    def close(self):
        if self.cleanup_verified:
            return
        if self.process.is_alive():
            self.process.terminate()
        self.process.join(2)
        if self.process.is_alive():
            self.process.kill()
            self.process.join(2)
        if self.process.is_alive():
            raise RuntimeError("Policy process cleanup could not be verified")
        self.cleanup_verified = True
        self.process.close()
        self.directory.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
