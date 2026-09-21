from matter_brief.brief import build_brief, render_html, render_markdown

from .helpers import as_of, run_demo

ORDER = ["What changed", "Key parties", "Important dates", "Documents", "Issues",
         "Outstanding requests", "Upcoming deadlines", "Recent activity"]


def test_sections_follow_the_matter_brief_structure():
    store, mid, _ = run_demo()
    titles = [s.title for s in build_brief(store, mid).sections]
    positions = [next(i for i, t in enumerate(titles) if t.startswith(name)) for name in ORDER]
    assert positions == sorted(positions)


def test_brief_after_the_extension_shows_the_moved_deadline():
    store, mid, _ = run_demo(upto=5)
    md = render_markdown(build_brief(store, mid))
    assert "Deadline moved" in md and "Sep 25, 2026 (Fri)" in md


def test_open_request_is_outstanding_until_answered():
    store, mid, _ = run_demo(upto=4)
    outstanding = next(s for s in build_brief(store, mid).sections if s.title == "Outstanding requests")
    assert len(outstanding.rows) == 1
    store, mid, _ = run_demo(upto=6)
    outstanding = next(s for s in build_brief(store, mid).sections if s.title == "Outstanding requests")
    assert outstanding.rows == []


def test_deadline_status_flags():
    store, mid, _ = run_demo()
    soon = render_markdown(build_brief(store, mid, as_of=as_of("2026-10-05")))
    assert "DUE SOON, 4 days" in soon
    late = render_markdown(build_brief(store, mid, as_of=as_of("2026-10-12")))
    assert "OVERDUE by 3 days" in late


def test_pending_changes_are_listed_but_not_in_the_record_sections():
    store, mid, _ = run_demo(approve=False, upto=3)
    brief = build_brief(store, mid)
    titles = [s.title for s in brief.sections]
    assert "Awaiting attorney review" in titles
    dates = next(s for s in brief.sections if s.title == "Important dates")
    assert all("Trial" not in r.cells[1] for r in dates.rows)


def test_html_is_self_contained_and_escaped():
    store, mid, _ = run_demo()
    page = render_html(build_brief(store, mid))
    assert page.startswith("<!doctype html>") and "<script" not in page
    assert "Rivera &amp; Chen LLP" in page and 'title="' in page
