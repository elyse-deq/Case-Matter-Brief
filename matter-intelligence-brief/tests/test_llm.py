import json

from matter_brief.extractors import LLMExtractor, parse_proposals
from matter_brief.models import DocumentMeta
from matter_brief.pipeline import ingest
from matter_brief.store import Store

DOC = "Trial is set to begin on June 7, 2027.\nFact discovery closes on January 29, 2027."
META = DocumentMeta("DOC-9", "Scheduling Order", "Court order", "2026-08-05")


def fake_model(items):
    return lambda system, user: "```json\n" + json.dumps(items) + "\n```"


def test_parse_handles_code_fences_and_bad_output():
    assert len(parse_proposals('```json\n[{"kind": "party", "key": "k", "data": {}, "quote": "q"}]\n```', "D")) == 1
    assert parse_proposals("not json at all", "D") == []
    assert parse_proposals('{"kind": "party"}', "D") == []
    assert parse_proposals('[{"kind": "opinion", "data": {}}]', "D") == []


def test_grounded_output_is_accepted():
    store = Store()
    store.create_matter("m", "Test")
    good = {"kind": "date", "key": "trial", "confidence": 0.9,
            "data": {"label": "Trial begins", "date": "2027-06-07"},
            "quote": "Trial is set to begin on June 7, 2027."}
    result = ingest(store, LLMExtractor(fake_model([good])), "m", META, DOC, approve_material=True)
    assert result.rejected == 0 and any(f.key == "trial" for f in store.facts("m"))


def test_hallucinated_facts_are_rejected_and_logged():
    store = Store()
    store.create_matter("m", "Test")
    invented_quote = {"kind": "date", "key": "hearing", "data": {"label": "Hearing", "date": "2026-11-02"},
                      "quote": "A hearing is set for November 2, 2026."}
    wrong_date = {"kind": "date", "key": "trial", "data": {"label": "Trial begins", "date": "2027-07-06"},
                  "quote": "Trial is set to begin on June 7, 2027."}
    result = ingest(store, LLMExtractor(fake_model([invented_quote, wrong_date])), "m", META, DOC)
    assert result.rejected == 2 and not store.facts("m")
    reasons = [r["reason"] for r in store.rejections("m")]
    assert any("not found in source" in r for r in reasons) and any("not stated" in r for r in reasons)
