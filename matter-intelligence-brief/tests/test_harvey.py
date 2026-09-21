import copy
import json
from datetime import date

import pytest

from matter_brief.cli import DEFAULT_DATA_DIR, HARVEY_SAMPLE_DIR, build_extractor, load_demo
from matter_brief.deadlines import compute_due
from matter_brief.extractors import (HarveyClient, HarveyError, HarveyReviewTableExtractor,
                                     LiveRowProvider, SampleRowProvider, load_column_map)
from matter_brief.models import DocumentMeta
from matter_brief.pipeline import ingest
from matter_brief.store import Store

_, DOCS = load_demo(DEFAULT_DATA_DIR)
DOC = {meta.doc_id: (meta, text) for meta, text in DOCS}
COLUMN_MAP = load_column_map(HARVEY_SAMPLE_DIR / "column_map.json")


def row_for(doc_id):
    return json.loads((HARVEY_SAMPLE_DIR / f"{doc_id}.row.json").read_text(encoding="utf-8"))


def extractor_with(row):
    return HarveyReviewTableExtractor(lambda meta, text: row, COLUMN_MAP)


def run(doc_id, row, approve=True):
    meta, text = DOC[doc_id]
    store = Store()
    store.create_matter("m", "Test")
    result = ingest(store, extractor_with(row), "m", meta, text, approve_material=approve)
    return store, result


def state(store, kind, key):
    return next(f.data for f in store.facts("m", kind) if f.key == key)


def test_scheduling_order_row_becomes_four_grounded_records():
    store, result = run("DOC-003", row_for("DOC-003"))
    assert result.rejected == 0 and len(result.accepted) == 4
    assert compute_due(state(store, "deadline", "fact-discovery-close")) == date(2027, 1, 29)
    assert state(store, "date", "trial")["date"] == "2027-06-07"


def test_cells_are_combined_and_a_truncated_quote_still_validates():
    # The period cell's citation stops mid-word ("30 days aft") but is a verbatim prefix.
    store, result = run("DOC-004", row_for("DOC-004"))
    assert result.rejected == 0
    assert compute_due(state(store, "deadline", "rfp-set-1-response")) == date(2026, 9, 11)
    request = state(store, "request", "rfp-set-1")
    assert (request["served_by"], request["served_on"]) == ("Plaintiff", "Defendant")


def test_not_found_and_unmapped_columns_are_skipped():
    _, result = run("DOC-007", row_for("DOC-007"))
    assert {(p.kind, p.key) for p in result.accepted} == {("party", "party-third-party-defendant"),
                                                          ("deadline", "tp-answer")}


def test_edited_cell_without_citation_is_rejected_and_logged():
    row = copy.deepcopy(row_for("DOC-003"))
    trial = next(c for c in row["response"]["cells"] if c["column_name"] == "Trial date")
    trial.update(is_edited=True, citations=[])
    store, result = run("DOC-003", row)
    assert result.rejected == 1
    assert all(f.key != "trial" for f in store.facts("m", "date"))
    assert "missing quote" in store.rejections("m")[0]["reason"]


def test_a_period_cell_with_no_citation_blocks_the_whole_deadline():
    row = copy.deepcopy(row_for("DOC-004"))
    period = next(c for c in row["response"]["cells"] if "period" in c["column_name"])
    period["citations"] = []
    store, result = run("DOC-004", row)
    assert any("supporting quote" in r["reason"] for r in store.rejections("m"))
    assert not [f for f in store.facts("m", "deadline")]


def test_a_date_harvey_cannot_source_is_rejected():
    row = copy.deepcopy(row_for("DOC-003"))
    trial = next(c for c in row["response"]["cells"] if c["column_name"] == "Trial date")
    trial["summary"] = "June 8, 2027"  # cell says the 8th, the citation says the 7th
    store, result = run("DOC-003", row)
    assert any("not stated" in r["reason"] for r in store.rejections("m"))


def test_an_unparseable_date_is_rejected_not_guessed():
    row = copy.deepcopy(row_for("DOC-003"))
    trial = next(c for c in row["response"]["cells"] if c["column_name"] == "Trial date")
    trial["summary"] = "Second quarter of 2027"
    store, _ = run("DOC-003", row)
    assert any("not an ISO date" in r["reason"] for r in store.rejections("m"))


def test_a_quote_missing_from_our_copy_of_the_document_is_rejected():
    row = copy.deepcopy(row_for("DOC-003"))
    trial = next(c for c in row["response"]["cells"] if c["column_name"] == "Trial date")
    trial["citations"][0]["citation_quote"] = "Trial is set to begin on June 7, 2027, at 9:00 a.m."
    store, _ = run("DOC-003", row)
    assert any("not found" in r["reason"] for r in store.rejections("m"))


def test_hybrid_run_matches_the_expected_due_dates():
    extractor = build_extractor("harvey-sample")
    store = Store()
    store.create_matter("m", "Test")
    used = []
    for meta, text in DOCS:
        assert ingest(store, extractor, "m", meta, text, approve_material=True).rejected == 0
        used.append(extractor.last)
    assert used == ["rules", "rules", "harvey", "harvey", "rules", "rules", "harvey+rules"]
    due = {f.key: compute_due(f.data) for f in store.facts("m", "deadline")}
    assert due["rfp-set-1-response"] == date(2026, 9, 25)  # Harvey trigger and period, rules extension
    assert due["tp-answer"] == date(2026, 10, 9)
    assert any(f.key.startswith("tp-claim") for f in store.facts("m", "issue"))  # filled by rules


def test_sample_provider_returns_none_when_there_is_no_row():
    assert SampleRowProvider(HARVEY_SAMPLE_DIR)(DocumentMeta("DOC-001", "x", "y", "2026-06-15"), "") is None


# The live client, tested against a fake transport. Not run against a real workspace.

class FakeHarvey:
    def __init__(self, ready_after=2, row_after=2):
        self.calls, self.ready_after, self.row_after = [], ready_after, row_after
        self.polls = self.row_polls = 0

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, headers, body))
        if "/upload_files/" in url:
            return 201, {"project_id": "P1", "file_ids": ["F1"]}
        if "/get_files" in url:
            self.polls += 1
            status = "ready_to_query" if self.polls >= self.ready_after else "processing"
            return 200, {"response": {"content": [{"file_id": "F1", "processing_status": status}]}}
        if "/add_row/" in url:
            return 200, {"response": {"status": "scheduled", "file_ids": ["F1"]}}
        if "/get_row/" in url:
            self.row_polls += 1
            if self.row_polls < self.row_after:
                return 404, {"error": "not found"}
            return 200, row_for("DOC-003")
        return 500, {"error": "unexpected"}


def make_client(fake):
    now = [0.0]
    return HarveyClient(api_key="k", transport=fake, sleep=lambda s: now.__setitem__(0, now[0] + s),
                        clock=lambda: now[0]), now


def test_client_sends_bearer_auth_and_respects_the_rate_limit():
    fake = FakeHarvey()
    client, now = make_client(fake)
    client.get_files(["F1"])
    client.get_files(["F1"])
    assert all(c[2]["Authorization"] == "Bearer k" for c in fake.calls)
    assert now[0] >= 6.0  # the second call waited out the 10-per-minute limit


def test_live_provider_runs_upload_poll_add_row_poll_row():
    fake = FakeHarvey()
    client, _ = make_client(fake)
    meta, text = DOC["DOC-003"]
    row = LiveRowProvider(client, "P1", 42)(meta, text)
    paths = [c[1].split("api.harvey.ai")[1].split("?")[0] for c in fake.calls]
    assert paths[0] == "/api/v1/vault/upload_files/P1"
    assert "/api/v1/vault/add_row/42" in paths
    assert paths[-1] == "/api/v1/vault/get_row/42/F1"
    assert paths.index("/api/v1/vault/add_row/42") > max(i for i, p in enumerate(paths) if p.endswith("get_files"))
    assert row["response"]["cells"]
    assert b'name="files"; filename="DOC-003.txt"' in fake.calls[0][3]


def test_client_raises_on_api_errors():
    client, _ = make_client(lambda *a: (401, {"error": "Unauthorized"}))
    with pytest.raises(HarveyError) as err:
        client.get_files(["F1"])
    assert err.value.status == 401


def test_client_gives_up_when_a_file_never_becomes_ready():
    fake = FakeHarvey(ready_after=10**9)
    client, _ = make_client(fake)
    with pytest.raises(HarveyError):
        client.wait_until_ready("F1", timeout=30, poll=10)
