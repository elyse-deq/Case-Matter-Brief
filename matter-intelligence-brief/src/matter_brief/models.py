"""Core types. Standard library only."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# The five kinds of fact a matter record holds. Documents are tracked separately.
KINDS = ("party", "date", "issue", "request", "deadline")

REQUIRED_FIELDS = {
    "party": ("name", "role"),
    "date": ("label", "date"),
    "issue": ("label", "side"),
    "request": ("label", "served_by", "served_on", "service_date", "status"),
    "deadline": ("label", "status"),
}

# Fields that must hold ISO dates, and must be supported by the quoted passage.
DATE_FIELDS = ("date", "trigger_date", "service_date", "response_date", "satisfied_on")


@dataclass
class DocumentMeta:
    doc_id: str
    title: str
    doc_type: str
    received_at: str  # ISO date


@dataclass
class Proposal:
    """A change an extractor wants to make to the matter record.

    Every proposal must carry a verbatim quote from the source document.
    The validator rejects any proposal whose quote is not in the document.
    When a fact is assembled from several cells (a trigger date in one, a period
    in another), the other cells' passages go in `supporting_quotes`, and each of
    those must be found in the document too.
    """

    kind: str
    key: str
    data: dict[str, Any]
    source_doc_id: str
    quote: str
    confidence: float = 1.0
    supporting_quotes: list[str] = field(default_factory=list)


@dataclass
class Fact:
    kind: str
    key: str
    data: dict[str, Any]
    source_doc_id: str
    quote: str


def missing_fields(kind: str, data: dict[str, Any]) -> list[str]:
    missing = [f for f in REQUIRED_FIELDS.get(kind, ()) if data.get(f) in (None, "")]
    if kind == "deadline":
        has_fixed = bool(data.get("date"))
        has_rule = bool(data.get("trigger_date")) and data.get("days") is not None
        if not (has_fixed or has_rule):
            missing.append("date or (trigger_date and days)")
    return missing


def merge_data(old: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Merge a patch into existing data.

    `add_extension_days` is folded into a running `extension_days` total so that
    two separate extensions accumulate instead of overwriting each other.
    """
    merged = dict(old)
    patch = dict(patch)
    add_ext = patch.pop("add_extension_days", None)
    merged.update(patch)
    if add_ext is not None:
        merged["extension_days"] = int(merged.get("extension_days", 0)) + int(add_ext)
    return merged
