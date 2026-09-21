"""LLM extractor.

The model is only asked to propose. Everything it returns goes through the same
validation gate as any other extractor: a verbatim quote, dates stated in that
quote, and required fields present. A hallucinated fact is rejected and logged.

Provider helpers are thin and use only the standard library:
  anthropic_complete   needs ANTHROPIC_API_KEY
  ollama_complete      needs a local Ollama server, so documents never leave the machine
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from typing import Callable

from ..models import KINDS, DocumentMeta, Proposal

SYSTEM_PROMPT = """You extract structured facts about a legal matter from ONE document.
Return only a JSON array. No prose, no markdown fences.

Each item: {"kind": ..., "key": ..., "data": {...}, "quote": ..., "confidence": 0.0-1.0}

Kinds and their data fields:
  party    {name, role}                       key like "party-defendant" or "counsel-plaintiff"
  date     {label, date}                      milestones such as filing or trial dates
  issue    {label, side}                      claims, defenses, and third-party claims
  request  {label, served_by, served_on, service_date, status}   discovery requests
  deadline {label, status, and either date, or trigger_date + days}   obligations

Rules:
  1. "quote" must be copied verbatim from the document. Do not paraphrase it.
  2. Write dates as YYYY-MM-DD, and only dates that appear in the quote.
  3. Never compute a due date. Give trigger_date and days, and code will compute it.
  4. If the document extends, satisfies, or otherwise updates an existing item, use the
     same key with only the changed fields. For an agreed extension use add_extension_days.
  5. If you are unsure, leave it out. A missing fact is better than a wrong one.
"""


def build_prompt(meta: DocumentMeta, text: str) -> str:
    return (f"Document id: {meta.doc_id}\nTitle: {meta.title}\nType: {meta.doc_type}\n"
            f"Received: {meta.received_at}\n\n---\n{text}\n---")


def parse_proposals(raw: str, doc_id: str) -> list[Proposal]:
    """Parse model output into proposals. Malformed output yields an empty list."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    try:
        items = json.loads(cleaned)
    except json.JSONDecodeError:
        return []
    if not isinstance(items, list):
        return []
    proposals: list[Proposal] = []
    for item in items:
        if not isinstance(item, dict) or item.get("kind") not in KINDS:
            continue
        data = item.get("data")
        if not isinstance(data, dict):
            continue
        try:
            confidence = float(item.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        proposals.append(Proposal(
            kind=item["kind"], key=str(item.get("key", "")), data=data,
            source_doc_id=doc_id, quote=str(item.get("quote", "")), confidence=confidence,
        ))
    return proposals


class LLMExtractor:
    name = "llm"

    def __init__(self, complete: Callable[[str, str], str]) -> None:
        """`complete(system_prompt, user_prompt)` returns the model's text."""
        self.complete = complete

    def extract(self, meta: DocumentMeta, text: str) -> list[Proposal]:
        return parse_proposals(self.complete(SYSTEM_PROMPT, build_prompt(meta, text)), meta.doc_id)


def _post_json(url: str, payload: dict, headers: dict) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json", **headers},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def anthropic_complete(model: str | None = None) -> Callable[[str, str], str]:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("Set ANTHROPIC_API_KEY to use the Anthropic provider.")
    model = model or os.environ.get("MATTER_BRIEF_MODEL", "claude-sonnet-5")

    def complete(system: str, user: str) -> str:
        body = _post_json(
            "https://api.anthropic.com/v1/messages",
            {"model": model, "max_tokens": 4000, "system": system,
             "messages": [{"role": "user", "content": user}]},
            {"x-api-key": api_key, "anthropic-version": "2023-06-01"},
        )
        return "".join(block.get("text", "") for block in body.get("content", []))

    return complete


def ollama_complete(model: str | None = None, host: str = "http://localhost:11434") -> Callable[[str, str], str]:
    model = model or os.environ.get("MATTER_BRIEF_MODEL", "llama3.1")

    def complete(system: str, user: str) -> str:
        body = _post_json(
            f"{host}/api/chat",
            {"model": model, "stream": False,
             "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
            {},
        )
        return body.get("message", {}).get("content", "")

    return complete
