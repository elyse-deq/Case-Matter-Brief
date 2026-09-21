"""Render the matter brief from the approved record.

The brief is a view, not a document that gets rewritten. Regenerating it after a
new arrival is cheap, and every line carries the id of the document it came from.
"""
from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .dates import fmt
from .deadlines import compute_due, days_remaining
from .store import Store

DUE_SOON_DAYS = 14

FOOTER = ("Prepared from the matter record. Every line cites the document it came from "
          "(hover a row in the HTML version to see the quoted passage). Computed dates are "
          "illustrative and must be verified against the governing rules by a lawyer.")


@dataclass
class Row:
    cells: list[str]
    quote: str = ""


@dataclass
class Section:
    title: str
    headers: list[str]
    rows: list[Row]
    empty_text: str = "None."
    intro: str = ""


@dataclass
class Brief:
    title: str
    meta: list[tuple[str, str]]
    sections: list[Section] = field(default_factory=list)


def describe_change(ch: dict[str, Any]) -> str:
    kind, after, before = ch["kind"], ch["after"], ch["before"] or {}
    label = after.get("label") or after.get("name") or ch["key"]
    added = ch["change_type"] == "added"
    if kind == "deadline":
        new_due, old_due = compute_due(after), compute_due(before) if before else None
        if added:
            return f"Added deadline: {label}, due {fmt(new_due)}"
        if new_due != old_due:
            return f"Deadline moved: {label}, {fmt(old_due)} to {fmt(new_due)}"
        if after.get("status") != before.get("status"):
            return f"Deadline {after.get('status')}: {label}"
        return f"Updated deadline: {label}"
    if kind == "date":
        return f"Added date: {label}, {fmt(compute_due(after))}" if added else f"Date changed: {label}"
    if kind == "party":
        return f"Added party: {after.get('name')} ({after.get('role')})" if added else f"Updated party: {label}"
    if kind == "issue":
        return f"Added issue: {label}" if added else f"Updated issue: {label}"
    if kind == "request":
        if after.get("status") != before.get("status") and not added:
            return f"Request {after.get('status')}: {label}"
        return f"Added request: {label}" if added else f"Updated request: {label}"
    return f"{ch['change_type'].title()} {kind}: {label}"


ROLE_ORDER = ["Plaintiff", "Defendant", "Third-Party Defendant",
              "Counsel for Plaintiff", "Counsel for Defendant", "Counsel for Third-Party Defendant"]


def _role_order(role: str) -> tuple[int, str]:
    return (ROLE_ORDER.index(role) if role in ROLE_ORDER else len(ROLE_ORDER), role)


def _status_of(due: date, as_of: date) -> str:
    remaining = days_remaining(due, as_of)
    if remaining < 0:
        return f"OVERDUE by {-remaining} days"
    if remaining <= DUE_SOON_DAYS:
        return f"DUE SOON, {remaining} days"
    return "Upcoming"


def build_brief(store: Store, matter_id: str, as_of: date | None = None) -> Brief:
    matter = store.matter(matter_id)
    if matter is None:
        raise KeyError(f"unknown matter: {matter_id}")
    docs = store.documents(matter_id)
    if as_of is None:
        as_of = date.fromisoformat(docs[-1]["received_at"]) if docs else date.today()
    latest = store.latest_event(matter_id)

    brief = Brief(
        title=matter["name"],
        meta=[("Matter type", matter.get("matter_type") or ""), ("Court", matter.get("court") or ""),
              ("Brief as of", fmt(as_of)),
              ("Documents on file", str(len(docs)))],
    )

    # What changed in the latest update, including changes still awaiting review.
    changes = store.changes_for_event(latest["id"]) if latest else []
    rows = [Row([describe_change(c), c["status"], c["source_doc_id"]], c["quote"]) for c in changes]
    latest_label = latest["summary"] if latest else "no documents yet"
    brief.sections.append(Section(
        f"What changed: {latest_label}", ["Change", "Status", "Source"], rows,
        empty_text="No new information in the latest document."))

    pending = store.pending(matter_id)
    if pending:
        brief.sections.append(Section(
            "Awaiting attorney review", ["Id", "Change", "Source"],
            [Row([str(c["id"]), describe_change(c), c["source_doc_id"]], c["quote"]) for c in pending],
            intro="These changes are not in the sections below until a lawyer approves them."))

    facts = store.facts(matter_id)
    by_kind = lambda k: [f for f in facts if f.kind == k]  # noqa: E731

    parties = sorted(by_kind("party"), key=lambda f: _role_order(f.data["role"]))
    brief.sections.append(Section(
        "Key parties", ["Role", "Name", "Source"],
        [Row([f.data["role"], f.data["name"], f.source_doc_id], f.quote) for f in parties]))

    dated = sorted(by_kind("date"), key=lambda f: f.data["date"])
    brief.sections.append(Section(
        "Important dates", ["Date", "Event", "Source"],
        [Row([fmt(compute_due(f.data)), f.data["label"], f.source_doc_id], f.quote) for f in dated]))

    brief.sections.append(Section(
        "Documents", ["Id", "Title", "Type", "Received"],
        [Row([d["doc_id"], d["title"], d["doc_type"] or "", d["received_at"]]) for d in docs]))

    brief.sections.append(Section(
        "Issues", ["Side", "Issue", "Source"],
        [Row([f.data["side"], f.data["label"], f.source_doc_id], f.quote) for f in by_kind("issue")]))

    deadlines = {f.key: f for f in by_kind("deadline")}
    open_requests = [f for f in by_kind("request") if f.data.get("status") == "open"]
    req_rows = []
    for f in open_requests:
        linked = next((d for d in deadlines.values() if d.data.get("related_request") == f.key), None)
        due = compute_due(linked.data) if linked else None
        req_rows.append(Row([f.data["label"], f.data["served_by"], f.data["served_on"],
                             fmt(date.fromisoformat(f.data["service_date"])), fmt(due),
                             f.source_doc_id], f.quote))
    brief.sections.append(Section(
        "Outstanding requests",
        ["Request", "Served by", "Served on", "Date served", "Response due", "Source"], req_rows))

    upcoming = []
    for f in deadlines.values():
        if f.data.get("status") == "satisfied":
            continue
        due = compute_due(f.data)
        if due:
            upcoming.append((due, f))
    upcoming.sort(key=lambda pair: pair[0])
    brief.sections.append(Section(
        "Upcoming deadlines", ["Due", "Deadline", "Status", "Source"],
        [Row([fmt(due), f.data["label"], _status_of(due, as_of), f.source_doc_id], f.quote)
         for due, f in upcoming]))

    activity = []
    for ev in store.events(matter_id, limit=8):
        descs = "; ".join(describe_change(c) for c in store.changes_for_event(ev["id"])) or "No changes"
        activity.append(Row([ev["ts"], ev["summary"], descs]))
    brief.sections.append(Section("Recent activity", ["Date", "Event", "Record changes"], activity))
    return brief


# Renderers

def _md_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_markdown(brief: Brief) -> str:
    out = [f"# {brief.title}", "", "Matter Intelligence Brief", ""]
    out += [f"**{k}:** {v}  " for k, v in brief.meta if v]
    for s in brief.sections:
        out += ["", f"## {s.title}", ""]
        if s.intro:
            out += [s.intro, ""]
        if not s.rows:
            out.append(f"_{s.empty_text}_")
            continue
        out.append("| " + " | ".join(s.headers) + " |")
        out.append("| " + " | ".join("---" for _ in s.headers) + " |")
        out += ["| " + " | ".join(_md_cell(c) for c in r.cells) + " |" for r in s.rows]
    out += ["", "---", "", f"_{FOOTER}_", ""]
    return "\n".join(out)


CSS = """
:root { --ink:#1b2733; --slate:#52606d; --rule:#d5dbe1; --accent:#0f5c63; --alert:#b42318; --amber:#b54708; --wash:#f3f6f8; }
* { box-sizing: border-box; }
body { margin: 0; padding: 2rem clamp(1rem, 4vw, 3rem) 4rem; color: var(--ink); background: #fff;
  font: 16px/1.5 system-ui, -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; text-align: left; }
main { max-width: 64rem; }
h1 { font-size: 1.9rem; line-height: 1.2; margin: 0 0 .25rem; font-weight: 650; }
.kicker { color: var(--slate); margin: 0 0 1rem; }
dl.meta { display: flex; flex-wrap: wrap; gap: .25rem 2rem; margin: 0 0 1.5rem; }
dl.meta div { display: flex; gap: .4rem; }
dl.meta dt { color: var(--slate); } dl.meta dd { margin: 0; font-weight: 600; }
h2 { font-size: 1.15rem; margin: 2rem 0 .5rem; font-weight: 650; }
section.changes { border-left: 4px solid var(--accent); padding-left: 1rem; background: var(--wash); padding-top: .1rem; padding-bottom: .75rem; }
section.changes h2 { margin-top: .9rem; }
.intro { color: var(--slate); margin: 0 0 .5rem; }
.empty { color: var(--slate); font-style: italic; }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; min-width: 34rem; }
th, td { text-align: left; padding: .45rem .75rem .45rem 0; border-bottom: 1px solid var(--rule); vertical-align: top; }
th { color: var(--slate); font-weight: 600; border-bottom: 2px solid var(--ink); white-space: nowrap; }
tr[title] { cursor: help; }
td.overdue { color: var(--alert); font-weight: 650; } td.soon { color: var(--amber); font-weight: 650; }
td.pending { color: var(--amber); font-weight: 650; }
footer { color: var(--slate); font-size: .875rem; margin-top: 2.5rem; max-width: 46rem; }
@media print { body { padding: 0; } tr[title] { cursor: auto; } }
"""


def render_html(brief: Brief) -> str:
    esc = html.escape
    parts = [
        "<!doctype html>", '<html lang="en">', "<head>", '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{esc(brief.title)}: Matter Intelligence Brief</title>", f"<style>{CSS}</style>",
        "</head>", "<body>", "<main>", f"<h1>{esc(brief.title)}</h1>",
        '<p class="kicker">Matter Intelligence Brief</p>', '<dl class="meta">',
    ]
    parts += [f"<div><dt>{esc(k)}</dt><dd>{esc(v)}</dd></div>" for k, v in brief.meta if v]
    parts.append("</dl>")
    for i, s in enumerate(brief.sections):
        parts.append('<section class="changes">' if i == 0 else "<section>")
        parts.append(f"<h2>{esc(s.title)}</h2>")
        if s.intro:
            parts.append(f'<p class="intro">{esc(s.intro)}</p>')
        if not s.rows:
            parts.append(f'<p class="empty">{esc(s.empty_text)}</p></section>')
            continue
        parts.append('<div class="scroll"><table><thead><tr>')
        parts += [f"<th>{esc(h)}</th>" for h in s.headers]
        parts.append("</tr></thead><tbody>")
        for r in s.rows:
            tip = f' title="{esc(r.quote, quote=True)}"' if r.quote else ""
            cells = []
            for c in r.cells:
                cls = ""
                if c.startswith("OVERDUE"):
                    cls = ' class="overdue"'
                elif c.startswith("DUE SOON"):
                    cls = ' class="soon"'
                elif c == "pending":
                    cls = ' class="pending"'
                cells.append(f"<td{cls}>{esc(c)}</td>")
            parts.append(f"<tr{tip}>{''.join(cells)}</tr>")
        parts.append("</tbody></table></div></section>")
    parts += [f"<footer>{esc(FOOTER)}</footer>", "</main>", "</body>", "</html>"]
    return "\n".join(parts)
