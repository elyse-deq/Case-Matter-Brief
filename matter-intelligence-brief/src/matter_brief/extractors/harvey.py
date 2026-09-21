"""Harvey adapter: Vault review tables in, validated proposals out.

Harvey is one extraction source. It reads a document and answers a fixed set of
questions in a Vault review table. This module turns those answers into
proposals. Everything after that (validation, change log, review queue,
deadline engine, brief) is the same as for any other extractor.

What the public developer docs (developers.harvey.ai) document, and what this
adapter uses:
  POST /api/v1/vault/upload_files/{project_id}     upload a file, returns file_ids
  GET  /api/v1/vault/get_files?file_ids=...        poll processing_status
  POST /api/v1/vault/add_row/{review_table_id}     run the table's columns on a new file
  GET  /api/v1/vault/get_row/{review_table_id}/{file_id}
                                                   cells with summary and citations
Bearer token auth. Vault and review table endpoints are limited to 10 requests
per minute, and API access has to be enabled on the workspace by Harvey.

What is NOT verified: none of the live client code has been run against a Harvey
workspace. It follows the public docs and is tested against a fake transport.
The offline path (SampleRowProvider plus the sample rows in data/harvey_sample)
uses an assumed, synthetic table that follows the documented get_row shape.

Things the validation gate will catch, by design:
  * A cell with no citation, including a cell a person edited by hand, since
    an edited cell is returned without citations. No source, no fact.
  * A citation quote that is not in our copy of the document. Harvey's text
    extraction can differ from ours, especially for scanned PDFs.
  * A date or period the citation does not state.
Harvey's citation quotes can be cut off mid-sentence. That is fine: a
truncated quote is still a verbatim prefix of a passage, so it still validates.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import date
from pathlib import Path
from typing import Any, Callable

from ..dates import dates_in_text, parse_long_date
from ..models import DocumentMeta, Proposal

BASE_URL = "https://api.harvey.ai"
MIN_INTERVAL_SECONDS = 6.0  # documented limit: 10 requests per minute

EMPTY_ANSWERS = {"", "not found", "n/a", "na", "none", "not addressed", "not specified",
                 "not applicable", "not stated"}

Transport = Callable[[str, str, dict, "bytes | None"], "tuple[int, dict]"]


class HarveyError(RuntimeError):
    def __init__(self, status: int | None, payload: Any) -> None:
        super().__init__(f"Harvey API error {status}: {payload}")
        self.status = status
        self.payload = payload


def _urllib_transport(method: str, url: str, headers: dict, body: bytes | None) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as err:
        raw = err.read().decode("utf-8", errors="replace")
        try:
            return err.code, json.loads(raw)
        except json.JSONDecodeError:
            return err.code, {"error": raw}


def _multipart(fields: dict[str, str], filename: str, content: bytes) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    out = bytearray()
    for name, value in fields.items():
        out += (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n').encode()
    out += (f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{filename}"\r\n'
            "Content-Type: text/plain\r\n\r\n").encode() + content + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


class HarveyClient:
    def __init__(self, api_key: str | None = None, base_url: str = BASE_URL,
                 transport: Transport | None = None, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic,
                 min_interval: float = MIN_INTERVAL_SECONDS) -> None:
        self.api_key = api_key or os.environ.get("HARVEY_API_KEY")
        if not self.api_key and transport is None:
            raise RuntimeError("Set HARVEY_API_KEY to use the live Harvey client.")
        self.base_url = base_url.rstrip("/")
        self.transport = transport or _urllib_transport
        self.sleep, self.clock, self.min_interval = sleep, clock, min_interval
        self._last_call: float | None = None

    def _throttle(self) -> None:
        now = self.clock()
        if self._last_call is not None and now - self._last_call < self.min_interval:
            self.sleep(self.min_interval - (now - self._last_call))
        self._last_call = self.clock()

    def _request(self, method: str, path: str, *, params: dict | None = None,
                 json_body: dict | None = None, multipart: tuple[bytes, str] | None = None) -> dict:
        self._throttle()
        url = self.base_url + path + ("?" + urllib.parse.urlencode(params) if params else "")
        headers = {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}
        body: bytes | None = None
        if json_body is not None:
            body, headers["Content-Type"] = json.dumps(json_body).encode("utf-8"), "application/json"
        elif multipart is not None:
            body, headers["Content-Type"] = multipart
        status, payload = self.transport(method, url, headers, body)
        if status >= 400:
            raise HarveyError(status, payload)
        return payload

    def upload_file(self, project_id: str, name: str, content: bytes, duplicate_mode: str = "skip") -> list[str]:
        body = _multipart({"file_paths": name, "duplicate_mode": duplicate_mode}, name, content)
        return list(self._request("POST", f"/api/v1/vault/upload_files/{project_id}", multipart=body)["file_ids"])

    def get_files(self, file_ids: list[str]) -> list[dict]:
        payload = self._request("GET", "/api/v1/vault/get_files", params={"file_ids": ",".join(file_ids)})
        return payload.get("response", {}).get("content", [])

    def add_row(self, review_table_id: int | str, file_ids: list[str], group_name: str | None = None) -> dict:
        body: dict[str, Any] = {"file_ids": file_ids}
        if group_name:
            body["group_name"] = group_name
        return self._request("POST", f"/api/v1/vault/add_row/{review_table_id}", json_body=body)

    def get_row(self, review_table_id: int | str, file_id: str) -> dict:
        return self._request("GET", f"/api/v1/vault/get_row/{review_table_id}/{file_id}")

    def wait_until_ready(self, file_id: str, timeout: float = 300, poll: float = 10) -> None:
        deadline = self.clock() + timeout
        while True:
            for item in self.get_files([file_id]):
                status = item.get("processing_status")
                if item.get("error") or status == "unrecoverable_failure":
                    raise HarveyError(None, item)
                if status == "ready_to_query":
                    return
            if self.clock() > deadline:
                raise HarveyError(None, f"file {file_id} not ready after {timeout}s")
            self.sleep(poll)

    def wait_for_row(self, review_table_id: int | str, file_id: str, timeout: float = 600, poll: float = 10) -> dict:
        """Poll until the review run has populated the row. The run is asynchronous."""
        deadline = self.clock() + timeout
        while True:
            try:
                row = self.get_row(review_table_id, file_id)
                if row.get("response", {}).get("cells"):
                    return row
            except HarveyError as err:
                if err.status != 404:
                    raise
            if self.clock() > deadline:
                raise HarveyError(None, f"row for {file_id} not populated after {timeout}s")
            self.sleep(poll)


class LiveRowProvider:
    """Upload the document to Vault, run the review table on it, and return the row."""

    def __init__(self, client: HarveyClient, project_id: str, review_table_id: int | str) -> None:
        self.client, self.project_id, self.review_table_id = client, project_id, review_table_id

    def __call__(self, meta: DocumentMeta, text: str) -> dict | None:
        file_id = self.client.upload_file(self.project_id, f"{meta.doc_id}.txt", text.encode("utf-8"))[0]
        self.client.wait_until_ready(file_id)
        self.client.add_row(self.review_table_id, [file_id])
        return self.client.wait_for_row(self.review_table_id, file_id)


class SampleRowProvider:
    """Read pre-saved rows shaped like Harvey's get_row response. Offline and synthetic."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)

    def __call__(self, meta: DocumentMeta, text: str) -> dict | None:
        path = self.directory / f"{meta.doc_id}.row.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def load_column_map(path: str | Path) -> dict[str, list[dict]]:
    """Which review table column feeds which field of which record.

    Each column maps to one rule or a list of rules:
      {"kind": "deadline", "key": "tp-answer", "field": "trigger_date", "parse": "date",
       "static": {"label": "...", "status": "open"}}
    Cells that feed the same (kind, key) are assembled into one proposal.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))["columns"]
    return {name: rule if isinstance(rule, list) else [rule] for name, rule in raw.items()}


def _parse(kind: str, raw: str) -> Any:
    """Parse a cell answer. On failure return the raw text so validation rejects and logs it."""
    text = raw.strip()
    if kind == "date":
        try:
            return parse_long_date(text).isoformat()
        except ValueError:
            return text
    if kind == "int":
        m = re.search(r"\d+", text)
        return int(m.group()) if m and len(text) <= 24 else text
    return text


def _pick_quote(citations: list[dict], parsed: Any, parse: str, raw: str) -> str:
    quotes = [c.get("citation_quote", "").strip() for c in citations if c.get("citation_quote", "").strip()]
    if not quotes:
        return ""
    for quote in quotes:
        if parse == "date" and isinstance(parsed, str) and parsed:
            try:
                if date.fromisoformat(parsed) in dates_in_text(quote):
                    return quote
            except ValueError:
                pass
        elif parse == "int" and isinstance(parsed, int) and re.search(rf"(?<!\d){parsed}(?!\d)", quote):
            return quote
        elif parse == "text" and raw.lower() in quote.lower():
            return quote
    return quotes[0]


def _confidence(cell: dict) -> float:
    if cell.get("is_flagged"):
        return 0.4
    return 0.95 if cell.get("is_verified") else 0.75


class HarveyReviewTableExtractor:
    name = "harvey"

    def __init__(self, row_provider: Callable[[DocumentMeta, str], dict | None],
                 column_map: dict[str, list[dict]]) -> None:
        self.row_provider, self.columns = row_provider, column_map

    def extract(self, meta: DocumentMeta, text: str) -> list[Proposal]:
        row = self.row_provider(meta, text)
        if not row:
            return []
        groups: dict[tuple[str, str], dict[str, Any]] = {}
        for cell in row.get("response", {}).get("cells", []):
            rules = self.columns.get(cell.get("column_name", ""))
            raw = (cell.get("summary") or "").strip()
            if not rules or raw.lower() in EMPTY_ANSWERS:
                continue  # unmapped column, or Harvey found nothing
            for rule in rules:
                parsed = _parse(rule.get("parse", "text"), raw)
                quote = _pick_quote(cell.get("citations") or [], parsed, rule.get("parse", "text"), raw)
                group = groups.setdefault((rule["kind"], rule["key"]),
                                          {"data": {}, "quotes": [], "confidence": 1.0})
                group["data"].update(rule.get("static", {}))
                group["data"][rule["field"]] = parsed
                group["quotes"].append((rule["field"], quote))
                group["confidence"] = min(group["confidence"], _confidence(cell))

        proposals = []
        for (kind, key), group in groups.items():
            quotes = group["quotes"]
            lead = next((q for field, q in quotes if field in ("date", "trigger_date", "service_date")), quotes[0][1])
            supporting = [q for _, q in quotes if q != lead or not q]
            supporting = list(dict.fromkeys(supporting))
            proposals.append(Proposal(kind, key, group["data"], meta.doc_id, lead,
                                      group["confidence"], supporting))
        return proposals


class FallbackExtractor:
    """Combine two extractors. The primary wins for any record it covers.

    A review table answers a fixed set of questions, so it will not cover every
    document or every fact in a document. For each (kind, key) the primary
    proposes, its proposal is used. Proposals from the fallback fill in only the
    records the primary did not address. Both go through the same validation.

    The primary's proposal is used even if validation later rejects it. The
    fallback never quietly covers for a rejected primary, so the rejection log
    shows the problem.
    """

    def __init__(self, primary: Any, fallback: Any) -> None:
        self.primary, self.fallback = primary, fallback
        self.name = f"{primary.name}+{fallback.name}"
        self.last = ""

    def extract(self, meta: DocumentMeta, text: str) -> list[Proposal]:
        first = self.primary.extract(meta, text)
        covered = {(p.kind, p.key) for p in first}
        extra = [p for p in self.fallback.extract(meta, text) if (p.kind, p.key) not in covered]
        if first and extra:
            self.last = self.name
        elif first:
            self.last = self.primary.name
        else:
            self.last = self.fallback.name
        return first + extra
