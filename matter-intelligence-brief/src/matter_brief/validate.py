"""Validation gate. Nothing reaches the matter record without passing it.

Two checks do most of the work:
  1. The quoted passage must appear in the source document.
  2. Every date in the proposal must be written in that quoted passage.

The second check is deliberately strict. A model that infers a date the document
never states gets rejected, and the rejection is logged for review.
"""
from __future__ import annotations

import re
from datetime import date

from .dates import dates_in_text
from .models import DATE_FIELDS, KINDS, Proposal

INT_FIELDS = ("days", "extension_days", "add_extension_days")
TEXT_FIELDS = ("name", "served_by", "served_on")


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def validate(proposal: Proposal, document_text: str) -> tuple[bool, str]:
    if proposal.kind not in KINDS:
        return False, f"unknown kind: {proposal.kind!r}"
    if not proposal.key or not isinstance(proposal.key, str):
        return False, "missing key"
    if not proposal.quote or not proposal.quote.strip():
        return False, "missing quote"
    if normalize(proposal.quote) not in normalize(document_text):
        return False, "quote not found in source document"

    for extra in proposal.supporting_quotes:
        if not extra or not extra.strip():
            return False, "supporting quote missing"
        if normalize(extra) not in normalize(document_text):
            return False, "supporting quote not found in source document"

    passages = " ".join([proposal.quote, *proposal.supporting_quotes])
    quoted_dates = dates_in_text(passages)
    for field in DATE_FIELDS:
        value = proposal.data.get(field)
        if value is None:
            continue
        try:
            parsed = date.fromisoformat(str(value))
        except ValueError:
            return False, f"{field} is not an ISO date: {value!r}"
        if parsed not in quoted_dates:
            return False, f"{field} {value} is not stated in the quoted passage"

    for field in INT_FIELDS:
        value = proposal.data.get(field)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return False, f"{field} must be a whole number, got {value!r}"
        if not re.search(rf"(?<!\d){value}(?!\d)", passages):
            return False, f"{field} {value} is not stated in the quoted passage"

    haystack = normalize(passages)
    for field in TEXT_FIELDS:
        value = proposal.data.get(field)
        if value and normalize(str(value)) not in haystack:
            return False, f"{field} {value!r} is not stated in the quoted passage"
    return True, ""
