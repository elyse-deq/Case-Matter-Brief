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

    quoted_dates = dates_in_text(proposal.quote)
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
    return True, ""
