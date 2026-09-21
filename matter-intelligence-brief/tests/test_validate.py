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


def test_periods_must_be_whole_numbers_stated_in_the_quote():
    doc = "Responses are due within 30 days after service."
    ok = Proposal("deadline", "k", {"label": "x", "trigger_date": None, "days": 30, "status": "open"},
                  "D", "Responses are due within 30 days after service.")
    assert validate(ok, doc)[0]
    wrong = Proposal("deadline", "k", {"label": "x", "days": 45, "status": "open"}, "D",
                     "Responses are due within 30 days after service.")
    assert "not stated" in validate(wrong, doc)[1]
    text = Proposal("deadline", "k", {"label": "x", "days": "thirty", "status": "open"}, "D",
                    "Responses are due within 30 days after service.")
    assert "whole number" in validate(text, doc)[1]


def test_names_must_appear_in_the_quote():
    doc = "Third-Party Defendant: Harbor Freight Partners LP"
    good = Proposal("party", "k", {"name": "Harbor Freight Partners LP", "role": "Third-Party Defendant"}, "D", doc)
    bad = Proposal("party", "k", {"name": "Harborview Logistics", "role": "Third-Party Defendant"}, "D", doc)
    assert validate(good, doc)[0] and not validate(bad, doc)[0]


def test_supporting_quotes_must_also_be_in_the_document():
    doc = "Plaintiff served the request on August 12, 2026. Responses are due within 30 days."
    data = {"label": "x", "trigger_date": "2026-08-12", "days": 30, "status": "open"}
    ok = Proposal("deadline", "k", data, "D", "Plaintiff served the request on August 12, 2026.",
                  supporting_quotes=["Responses are due within 30 days."])
    missing = Proposal("deadline", "k", data, "D", "Plaintiff served the request on August 12, 2026.",
                       supporting_quotes=[""])
    invented = Proposal("deadline", "k", data, "D", "Plaintiff served the request on August 12, 2026.",
                        supporting_quotes=["Responses are due within 45 days."])
    assert validate(ok, doc)[0]
    assert "missing" in validate(missing, doc)[1]
    assert "not found" in validate(invented, doc)[1]
