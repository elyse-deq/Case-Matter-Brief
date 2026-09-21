"""Ingest pipeline: document in, reviewed record changes out.

    document -> event -> extract -> validate -> merge -> materiality -> record

Non-material changes are applied immediately. Material changes (a new or moved
deadline or date, a new adverse party) wait in a review queue for a lawyer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .deadlines import compute_due
from .extractors.base import Extractor
from .models import DocumentMeta, Proposal, merge_data, missing_fields
from .store import Store
from .validate import validate


@dataclass
class IngestResult:
    skipped: bool = False
    event_id: int | None = None
    accepted: list[Proposal] = field(default_factory=list)
    change_ids: list[int] = field(default_factory=list)
    rejected: int = 0


def is_material(store: Store, matter_id: str, kind: str, change_type: str,
                before: dict[str, Any] | None, after: dict[str, Any],
                *, event_id: int, received_at: str) -> bool:
    """Decide whether a change needs a lawyer's approval before it reaches the brief.

    Material: a new or moved deadline, a new or moved future date, and a new
    adverse party joining a matter that already has parties. Everything else
    (issues, counsel, status changes, historical dates) is applied immediately
    and stays visible in the change log.
    """
    if kind == "deadline":
        return change_type == "added" or compute_due(before or {}) != compute_due(after)
    if kind == "date":
        if change_type == "updated":
            return (before or {}).get("date") != after.get("date")
        return str(after.get("date", "")) > received_at  # a future date, not a historical one
    if kind == "party":
        is_counsel = str(after.get("role", "")).startswith("Counsel")
        return change_type == "added" and not is_counsel and store.has_earlier_parties(matter_id, event_id)
    return False


def ingest(store: Store, extractor: Extractor, matter_id: str, meta: DocumentMeta, text: str,
           *, approve_material: bool = False, actor: str = "reviewer") -> IngestResult:
    if not store.add_document(matter_id, meta, text):
        return IngestResult(skipped=True)

    event_id = store.add_event(matter_id, meta.received_at, "document_received", meta.doc_id,
                               f"Received {meta.title}")
    result = IngestResult(event_id=event_id)

    for proposal in extractor.extract(meta, text):
        ok, reason = validate(proposal, text)
        if not ok:
            store.log_rejection(matter_id, event_id, proposal.kind, proposal.key, reason, proposal.quote)
            result.rejected += 1
            continue

        before = store.current_state(matter_id, proposal.kind, proposal.key)
        after = merge_data(before or {}, proposal.data)

        gaps = missing_fields(proposal.kind, after)
        if gaps:
            store.log_rejection(matter_id, event_id, proposal.kind, proposal.key,
                                "missing required fields: " + ", ".join(gaps), proposal.quote)
            result.rejected += 1
            continue

        result.accepted.append(proposal)
        if before == after:
            continue  # nothing new (for example, a party restated in a later filing)

        change_type = "added" if before is None else "updated"
        material = is_material(store, matter_id, proposal.kind, change_type, before, after,
                               event_id=event_id, received_at=meta.received_at)
        needs_review = material and not approve_material
        change_id = store.record_change(
            matter_id=matter_id, event_id=event_id, kind=proposal.kind, key=proposal.key,
            change_type=change_type, before=before, after=after, source_doc_id=proposal.source_doc_id,
            quote=proposal.quote, confidence=proposal.confidence, material=material,
            status="pending" if needs_review else "approved",
            decided_by=None if needs_review else (actor if material else "auto (non-material)"),
        )
        result.change_ids.append(change_id)
    return result
