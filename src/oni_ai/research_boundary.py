"""Exact structured claim checking, independent of natural-language rationale."""

from oni_ai.contracts import strict_json
from oni_ai.episodes import validate_proposal
from oni_ai.evaluation import _canonical


def pointer_value(document: object, pointer: str) -> object:
    if not isinstance(pointer, str) or (pointer and not pointer.startswith("/")):
        raise ValueError("Invalid JSON pointer")
    value = document
    if pointer:
        for part in pointer[1:].split("/"):
            if "~" in part.replace("~0", "").replace("~1", ""):
                raise ValueError("Invalid pointer escape")
            key = part.replace("~1", "/").replace("~0", "~")
            if isinstance(value, list):
                if not key.isdigit() or str(int(key)) != key:
                    raise ValueError("Invalid array index")
                value = value[int(key)]
            else:
                value = value[key]
    return value


def validate_envelope(raw: object, observation: dict, evidence: tuple, seen_ids: set) -> tuple:
    """Return a Phase 2 proposal only if its citations and exact claims are consistent."""
    try:
        envelope = strict_json(raw) if isinstance(raw, str) else raw
        if (
            not isinstance(envelope, dict)
            or set(envelope) != {"schema_version", "proposal", "claims"}
            or type(envelope["schema_version"]) is not int
            or envelope["schema_version"] != 1
            or not isinstance(envelope["claims"], list)
            or not 1 <= len(envelope["claims"]) <= 64
        ):
            return None, ["INVALID_ENVELOPE"]
        decision, failures = validate_proposal(
            envelope["proposal"], observation, evidence, seen_ids
        )
        available = {item.evidence_id: item for item in evidence}
        claimed = set()
        for claim in envelope["claims"]:
            if not isinstance(claim, dict) or set(claim) != {
                "evidence_id",
                "pointer",
                "value",
                "status",
            }:
                failures.append("INVALID_CLAIM")
                continue
            item = available.get(claim["evidence_id"])
            if item is None:
                failures.append("CLAIM_NOT_RETRIEVED")
                continue
            expected = pointer_value(strict_json(item.value_json), claim["pointer"])
            if claim["status"] != item.status or _canonical(claim["value"]) != _canonical(expected):
                failures.append("CLAIM_VALUE_OR_STATUS_MISMATCH")
            # Full source values must support each model citation; partial claims are supplemental.
            if claim["pointer"] == "":
                claimed.add(item.evidence_id)
        if (
            decision
            and not {ref for ref in decision.evidence_refs if not ref.startswith("obs:")} <= claimed
        ):
            failures.append("MISSING_STRUCTURED_CLAIM")
        return (envelope["proposal"] if not failures else None), sorted(set(failures))
    except (ValueError, TypeError, KeyError, IndexError, OverflowError, RecursionError):
        return None, ["INVALID_CLAIM_OR_JSON"]
