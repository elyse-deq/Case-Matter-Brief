from matter_brief.models import Proposal
from matter_brief.validate import validate

DOC = "Fact discovery closes on January 29, 2027.\nTrial is set to begin on June 7, 2027."


def proposal(**overrides):
    base = dict(kind="deadline", key="fact-discovery-close",
                data={"label": "Fact discovery closes", "date": "2027-01-29", "status": "open"},
                source_doc_id="DOC-X", quote="Fact discovery closes on January 29, 2027.")
    base.update(overrides)
    return Proposal(**base)


def test_accepts_a_sourced_fact():
    assert validate(proposal(), DOC) == (True, "")


def test_rejects_a_quote_that_is_not_in_the_document():
    ok, reason = validate(proposal(quote="Fact discovery closes on March 1, 2027."), DOC)
    assert not ok and "not found" in reason


def test_rejects_a_date_the_quote_does_not_state():
    ok, reason = validate(proposal(data={"label": "x", "date": "2027-02-01", "status": "open"}), DOC)
    assert not ok and "not stated" in reason


def test_rejects_a_missing_quote():
    ok, _ = validate(proposal(quote=""), DOC)
    assert not ok


def test_rejects_unknown_kind():
    ok, _ = validate(proposal(kind="opinion"), DOC)
    assert not ok


def test_whitespace_and_case_differences_are_tolerated():
    ok, _ = validate(proposal(quote="fact discovery   closes on\nJanuary 29, 2027."), DOC)
    assert ok
