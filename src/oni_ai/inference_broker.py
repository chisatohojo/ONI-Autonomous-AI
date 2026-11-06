"""Bounded, journaled mock generation broker. No URL, command or network transport RPC."""

import re
from dataclasses import asdict, dataclass

from oni_ai.episodes import digest
from oni_ai.inference_contracts import InferenceError, safe_json
from oni_ai.local_model import (
    MockChatTransport,
    OllamaStructuredModel,
    model_input,
    profile_for,
)

BROKER_VERSION = "offline-inference-broker/1"


@dataclass(frozen=True)
class BrokerLimits:
    input_tokens: int = 500000
    output_tokens: int = 65536
    total_tokens: int = 4_000_000
    cost_microusd: int = 10_000_000
    requests: int = 128

    def __post_init__(self):
        for value in asdict(self).values():
            if type(value) is not int or not 1 <= value <= 100_000_000:
                raise InferenceError("INVALID_BROKER_BUDGET")
        if self.requests > 400 or self.output_tokens > 65536:
            raise InferenceError("INVALID_BROKER_BUDGET")


class InferenceBroker:
    def __init__(
        self, model_key="offline", limits=None, *, seed=0, mode="normal", emit=None, call_seconds=5
    ):
        self.model = OllamaStructuredModel(profile_for(model_key), MockChatTransport(seed, mode))
        self.limits = limits or BrokerLimits()
        self.call_seconds = call_seconds
        self.records, self.cache, self.tickets, self.spent_tickets = [], {}, {}, set()
        self.tokens = self.cost = self.generations = 0
        self.emit = emit
        self.record(
            {
                "kind": "broker_header",
                "version": BROKER_VERSION,
                "model_key": model_key,
                "profile": asdict(self.model.profile),
                "limits": asdict(self.limits),
                "scope": "OFFLINE_MOCK_NOT_LLM",
            }
        )

    def record(self, record):
        safe_json(record)
        if self.emit:
            self.emit(record)
        self.records.append(record)

    def handle(self, request):
        try:
            safe_json(request)
            if (
                not isinstance(request, dict)
                or not isinstance(request.get("id"), str)
                or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", request["id"])
            ):
                raise InferenceError("INVALID_REQUEST_ID")
            request_id, request_digest = request["id"], digest(request)
            if request_id in self.cache:
                old_digest, response = self.cache[request_id]
                if old_digest != request_digest:
                    raise InferenceError("REQUEST_ID_CONFLICT")
                self.record(
                    {"kind": "duplicate", "id": request_id, "request_digest": request_digest}
                )
                return response
            if len(self.cache) >= self.limits.requests:
                raise InferenceError("BROKER_REQUEST_LIMIT")
            response = self.dispatch(request)
        except InferenceError as error:
            response = {"ok": False, "error": error.code}
            self.record(
                {
                    "kind": "rejected",
                    "id": request.get("id")
                    if isinstance(request, dict)
                    and isinstance(request.get("id"), str)
                    and re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", request["id"])
                    else "invalid",
                    "error": error.code,
                }
            )
        # Record only controlled errors; rejected secrets never enter the journal.
        if (
            isinstance(request, dict)
            and isinstance(request.get("id"), str)
            and re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", request["id"])
        ):
            committed = request["id"] in self.tickets or any(
                r["kind"] == "reserve" and r["id"] == request["id"] for r in self.records
            )
            if (
                committed
                and request["id"] not in self.cache
                and len(self.cache) < self.limits.requests
            ):
                self.cache[request["id"]] = digest(request), response
        return response

    def dispatch(self, request):
        if request.get("op") == "count" and set(request) == {"id", "op", "payload"}:
            count = self.model.count_tokens(request["payload"])
            if count > self.limits.input_tokens:
                raise InferenceError("BROKER_INPUT_LIMIT")
            _, schema, _ = model_input(request["payload"])
            ticket = {
                "payload": request["payload"],
                "count": count,
                "schema_digest": digest(schema),
            }
            self.tickets[request["id"]] = ticket
            self.record({"kind": "count", "id": request["id"], **ticket})
            return {"ok": True, "value": {"count": count, "ticket": request["id"]}}
        if request.get("op") != "generate" or set(request) != {
            "id",
            "op",
            "ticket",
            "payload",
            "max_output_tokens",
        }:
            raise InferenceError("RPC_NOT_ALLOWED")
        if not isinstance(request["ticket"], str):
            raise InferenceError("COUNT_TICKET_MISMATCH")
        ticket = self.tickets.get(request["ticket"])
        output = request["max_output_tokens"]
        if ticket is None or ticket["payload"] != request["payload"]:
            raise InferenceError("COUNT_TICKET_MISMATCH")
        if request["ticket"] in self.spent_tickets:
            raise InferenceError("COUNT_TICKET_USED")
        if type(output) is not int or not 1 <= output <= self.limits.output_tokens:
            raise InferenceError("BROKER_OUTPUT_LIMIT")
        tokens = ticket["count"] + output
        profile = self.model.profile
        cost = (
            ticket["count"] * profile.input_microusd_per_million
            + output * profile.output_microusd_per_million
            + 999999
        ) // 1000000
        if (
            self.tokens + tokens > self.limits.total_tokens
            or self.cost + cost > self.limits.cost_microusd
        ):
            raise InferenceError("BROKER_TOTAL_LIMIT")
        self.tokens += tokens
        self.cost += cost
        self.generations += 1
        self.spent_tickets.add(request["ticket"])
        reservation = {
            "kind": "reserve",
            "id": request["id"],
            "ticket": request["ticket"],
            "max_output_tokens": output,
            "tokens": tokens,
            "cost_microusd": cost,
        }
        self.record(reservation)  # The subprocess flushes/fsyncs this before transport invocation.
        raw, reply, error = None, None, None
        try:
            raw = self.model.transport(
                self.model.request(ticket["payload"], output), self.call_seconds
            )
            safe_json(raw)
            reply = self.model.parse_response(ticket["payload"], raw, output)
        except InferenceError as failure:
            error = failure.code
            try:
                safe_json(raw)
            except InferenceError:
                raw = None
        except Exception:
            raw, error = None, "MOCK_CONNECTION_FAILURE"
        self.record(
            {
                "kind": "result",
                "id": request["id"],
                "raw": raw,
                "reply": asdict(reply) if reply else None,
                "error": error,
            }
        )
        return {"ok": False, "error": error} if error else {"ok": True, "value": asdict(reply)}


def verify_broker_records(records):
    """Recompute exact mock counts, reservations and safe responses without invoking transport."""
    try:
        if not isinstance(records, list) or not records:
            raise InferenceError("INCOMPLETE_BROKER_AUDIT")
        header = records[0]
        if (
            header["kind"] != "broker_header"
            or header["version"] != BROKER_VERSION
            or header["scope"] != "OFFLINE_MOCK_NOT_LLM"
            or header["profile"] != asdict(profile_for(header["model_key"]))
        ):
            raise InferenceError("BROKER_AUDIT_HEADER")
        limits = BrokerLimits(**header["limits"])
        model = OllamaStructuredModel(profile_for(header["model_key"]), None)
        counts, reservations, results, requests = {}, {}, {}, {}
        total_tokens = total_cost = 0
        spent_tickets = set()
        for record in records[1:]:
            safe_json(record)
            key = record["id"]
            if record["kind"] == "count":
                _, schema, _ = model_input(record["payload"])
                count = model.count_tokens(record["payload"])
                if (
                    record
                    != {
                        "kind": "count",
                        "id": key,
                        "payload": record["payload"],
                        "count": count,
                        "schema_digest": digest(schema),
                    }
                    or count > limits.input_tokens
                    or key in requests
                ):
                    raise InferenceError("BROKER_AUDIT_COUNT")
                counts[key] = record
                requests[key] = {"id": key, "op": "count", "payload": record["payload"]}
            elif record["kind"] == "reserve":
                ticket = counts[record["ticket"]]
                if record["ticket"] in spent_tickets:
                    raise InferenceError("BROKER_AUDIT_RESERVATION")
                spent_tickets.add(record["ticket"])
                output = record["max_output_tokens"]
                if (
                    type(output) is not int
                    or not 1 <= output <= limits.output_tokens
                    or key in requests
                ):
                    raise InferenceError("BROKER_AUDIT_RESERVATION")
                tokens = ticket["count"] + output
                profile = model.profile
                cost = (
                    ticket["count"] * profile.input_microusd_per_million
                    + output * profile.output_microusd_per_million
                    + 999999
                ) // 1000000
                if record != {
                    "kind": "reserve",
                    "id": key,
                    "ticket": record["ticket"],
                    "max_output_tokens": output,
                    "tokens": tokens,
                    "cost_microusd": cost,
                }:
                    raise InferenceError("BROKER_AUDIT_RESERVATION")
                total_tokens += tokens
                total_cost += cost
                reservations[key] = record
                requests[key] = {
                    "id": key,
                    "op": "generate",
                    "ticket": record["ticket"],
                    "payload": ticket["payload"],
                    "max_output_tokens": output,
                }
            elif record["kind"] == "result":
                reservation = reservations[key]
                if key in results or set(record) != {"kind", "id", "raw", "reply", "error"}:
                    raise InferenceError("BROKER_AUDIT_RESULT")
                if record["raw"] is not None:
                    try:
                        reply = model.parse_response(
                            counts[reservation["ticket"]]["payload"],
                            record["raw"],
                            reservation["max_output_tokens"],
                        )
                        expected_reply, expected_error = asdict(reply), None
                    except InferenceError as error:
                        expected_reply, expected_error = None, error.code
                    if expected_reply != record["reply"] or expected_error != record["error"]:
                        raise InferenceError("BROKER_AUDIT_RESULT")
                elif record["reply"] is not None or record["error"] not in {
                    "MOCK_CONNECTION_FAILURE",
                    "SECRET_OR_PRIVATE_DATA",
                }:
                    raise InferenceError("BROKER_AUDIT_FAULT")
                results[key] = record
            elif record["kind"] == "duplicate":
                if record != {
                    "kind": "duplicate",
                    "id": key,
                    "request_digest": digest(requests[key]),
                }:
                    raise InferenceError("BROKER_AUDIT_DUPLICATE")
            elif record["kind"] == "rejected":
                if set(record) != {"kind", "id", "error"} or record["error"] not in {
                    "INVALID_REQUEST_ID",
                    "REQUEST_ID_CONFLICT",
                    "BROKER_REQUEST_LIMIT",
                    "BROKER_INPUT_LIMIT",
                    "RPC_NOT_ALLOWED",
                    "COUNT_TICKET_MISMATCH",
                    "COUNT_TICKET_USED",
                    "BROKER_OUTPUT_LIMIT",
                    "BROKER_TOTAL_LIMIT",
                    "EXACT_COUNTER_UNAVAILABLE",
                    "SECRET_OR_PRIVATE_DATA",
                    "INVALID_JSON",
                    "INVALID_MODEL_INPUT",
                    "INVALID_CONTEXT",
                    "SCHEMA_LIMIT",
                    "SCHEMA_UNSUPPORTED",
                    "NO_EVIDENCE",
                    "FRAME_LIMIT",
                    "IPC_IO_FAILURE",
                }:
                    raise InferenceError("BROKER_AUDIT_REJECTION")
            else:
                raise InferenceError("BROKER_AUDIT_RECORD")
            if (
                total_tokens > limits.total_tokens
                or total_cost > limits.cost_microusd
                or len(requests) > limits.requests
            ):
                raise InferenceError("BROKER_AUDIT_BUDGET")
        completed = [r["reply"] for r in results.values() if r["reply"] is not None]
        verified_input = sum(reply["input_tokens"] for reply in completed)
        verified_output = sum(reply["output_tokens"] for reply in completed)
        profile = model.profile
        verified_cost = sum(
            (
                reply["input_tokens"] * profile.input_microusd_per_million
                + reply["output_tokens"] * profile.output_microusd_per_million
                + 999999
            )
            // 1000000
            for reply in completed
        )
        return {
            "verified": True,
            "reserved_tokens": total_tokens,
            "reserved_cost_microusd": total_cost,
            "generations": len(reservations),
            "usage_unknown_requests": len(set(reservations) - set(results))
            + sum(r["reply"] is None for r in results.values()),
            "incomplete_requests": len(set(reservations) - set(results)),
            "verified_input_tokens": verified_input,
            "verified_output_tokens": verified_output,
            "verified_cost_microusd": verified_cost,
        }
    except (KeyError, TypeError, AttributeError, OverflowError) as error:
        raise InferenceError("MALFORMED_BROKER_AUDIT") from error
