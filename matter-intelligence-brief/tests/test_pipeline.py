from datetime import date

from matter_brief.deadlines import compute_due
from matter_brief.extractors import RulesExtractor
from matter_brief.models import DocumentMeta
from matter_brief.pipeline import ingest

from .helpers import run_demo


def state(store, matter_id, kind, key):
    return next(f.data for f in store.facts(matter_id, kind) if f.key == key)


def test_full_matter_reaches_the_expected_record():
    store, mid, _ = run_demo()
    assert compute_due(state(store, mid, "deadline", "tp-answer")) == date(2026, 10, 9)
    assert compute_due(state(store, mid, "deadline", "fact-discovery-close")) == date(2027, 1, 29)
    assert state(store, mid, "request", "rfp-set-1")["status"] == "responded"
    assert state(store, mid, "deadline", "rfp-set-1-response")["status"] == "satisfied"


def test_extension_moves_the_deadline_and_keeps_the_history():
    store, mid, _ = run_demo(upto=5)
    assert compute_due(state(store, mid, "deadline", "rfp-set-1-response")) == date(2026, 9, 25)
    moved = [c for c in store.changes_for_event(5) if c["key"] == "rfp-set-1-response"]
    assert moved and moved[0]["before"]["days"] == 30 and moved[0]["after"]["extension_days"] == 14


def test_reingesting_a_document_is_a_no_op():
    store, mid, _ = run_demo(upto=2)
    from matter_brief.cli import DEFAULT_DATA_DIR, load_demo
    _, docs = load_demo(DEFAULT_DATA_DIR)
    meta, text = docs[1]
    assert ingest(store, RulesExtractor(), mid, meta, text).skipped


def test_restating_a_known_party_creates_no_change():
    store, mid, results = run_demo(upto=2)
    # The Answer restates "Defendant: Northwind Logistics LLC". Only counsel and defenses are new.
    keys = {store.get_change(cid)["key"] for cid in results[1].change_ids}
    assert "party-defendant" not in keys and "counsel-defendant" in keys


def test_material_changes_wait_for_review_and_stay_out_of_the_record():
    store, mid, _ = run_demo(approve=False, upto=3)
    pending_keys = {c["key"] for c in store.pending(mid)}
    assert {"fact-discovery-close", "trial"} <= pending_keys
    assert all(f.key != "trial" for f in store.facts(mid, "date"))
    # The opening complaint is baseline context, not something to hold for review.
    assert not any(c["key"] in ("party-defendant", "complaint-filed") for c in store.pending(mid))


def test_approving_a_pending_change_applies_it():
    store, mid, _ = run_demo(approve=False, upto=3)
    for change in store.pending(mid):
        store.decide(change["id"], True, "attorney")
    assert not store.pending(mid)
    assert any(f.key == "trial" for f in store.facts(mid, "date"))


def test_rejecting_a_pending_change_keeps_it_out_of_the_record():
    store, mid, _ = run_demo(approve=False, upto=3)
    trial = next(c for c in store.pending(mid) if c["key"] == "trial")
    store.decide(trial["id"], False, "attorney")
    assert all(f.key != "trial" for f in store.facts(mid, "date"))


def test_a_new_adverse_party_is_material():
    store, mid, _ = run_demo(approve=False)
    assert any(c["key"] == "party-third-party-defendant" and c["material"] for c in store.pending(mid))


def test_extension_before_the_request_exists_is_rejected_not_guessed():
    from matter_brief.store import Store
    store = Store()
    store.create_matter("m", "Test matter")
    text = ("Defendant's counsel requested a 14-day extension to respond to the First Set of Requests "
            "for Production, and Plaintiff's counsel agreed.")
    result = ingest(store, RulesExtractor(), "m", DocumentMeta("D1", "Email", "Correspondence", "2026-09-02"), text)
    assert result.rejected == 1 and not store.facts("m")
    assert "missing required fields" in store.rejections("m")[0]["reason"]
