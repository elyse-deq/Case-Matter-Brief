"""Deterministic, rule-based extractor for the synthetic demo matter.

This is a scaffold, not a production extractor. It exists so the whole pipeline
(validation, change log, review queue, brief) runs and is testable with no model
and no API key. Swap in LLMExtractor for real documents.
"""
from __future__ import annotations

import re

from ..dates import LONG_DATE_PATTERN, parse_long_date
from ..models import DocumentMeta, Proposal

ROLE = r"(Plaintiff|Defendant|Third-Party Defendant)"
ORDINAL = r"(First|Second|Third|Fourth|Fifth)"
_ORDINAL_NUM = {"First": 1, "Second": 2, "Third": 3, "Fourth": 4, "Fifth": 5}

SCHEDULE = {
    "Fact discovery closes": ("fact-discovery-close", "Fact discovery closes"),
    "Expert disclosures are due": ("expert-disclosures", "Expert disclosures"),
    "Dispositive motions are due": ("dispositive-motions", "Dispositive motions"),
}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _iso(long_date: str) -> str:
    return parse_long_date(long_date).isoformat()


class RulesExtractor:
    name = "rules"

    def extract(self, meta: DocumentMeta, text: str) -> list[Proposal]:
        proposals: list[Proposal] = []
        for raw in text.splitlines():
            line = raw.strip()
            if line:
                proposals.extend(self._line(meta, line))
        return proposals

    def _line(self, meta: DocumentMeta, line: str) -> list[Proposal]:
        def p(kind: str, key: str, data: dict) -> Proposal:
            return Proposal(kind, key, data, meta.doc_id, line, 1.0)

        if m := re.fullmatch(rf"{ROLE}: (.+)", line):
            role, name = m.groups()
            return [p("party", f"party-{_slug(role)}", {"name": name, "role": role})]

        if m := re.fullmatch(rf"Counsel for {ROLE}: (.+)", line):
            role, name = m.groups()
            return [p("party", f"counsel-{_slug(role)}", {"name": name, "role": f"Counsel for {role}"})]

        if m := re.fullmatch(r"Count ([IVX]+): (.+)", line):
            num, title = m.groups()
            return [p("issue", f"count-{num.lower()}",
                      {"label": f"Count {num}: {title}", "side": "Claim by Plaintiff"})]

        if m := re.fullmatch(r"Affirmative Defense (\d+): (.+)", line):
            num, title = m.groups()
            return [p("issue", f"defense-{num}",
                      {"label": f"Defense {num}: {title}", "side": "Defense by Defendant"})]

        if m := re.fullmatch(r"Third-Party Claim: (.+)", line):
            title = m.group(1)
            return [p("issue", f"tp-claim-{_slug(title)}",
                      {"label": f"Third-party claim: {title}", "side": "Claim by Defendant"})]

        if m := re.fullmatch(rf"Complaint filed on {LONG_DATE_PATTERN}\.", line):
            return [p("date", "complaint-filed", {"label": "Complaint filed", "date": _iso(m.group(1))})]

        if m := re.fullmatch(rf"Trial is set to begin on {LONG_DATE_PATTERN}\.", line):
            return [p("date", "trial", {"label": "Trial begins", "date": _iso(m.group(1))})]

        for phrase, (key, label) in SCHEDULE.items():
            if m := re.fullmatch(rf"{phrase} on {LONG_DATE_PATTERN}\.", line):
                return [p("deadline", key, {"label": label, "date": _iso(m.group(1)),
                                            "status": "open", "authority": meta.title})]

        if m := re.fullmatch(
            rf"{ROLE} served the {ORDINAL} Set of Requests for Production on {ROLE} on "
            rf"{LONG_DATE_PATTERN}\. Responses are due within (\d+) days after service\.", line
        ):
            served_by, ordinal, served_on, when, days = m.groups()
            n = _ORDINAL_NUM[ordinal]
            label = f"{ordinal} Set of Requests for Production"
            return [
                p("request", f"rfp-set-{n}", {
                    "label": label, "served_by": served_by, "served_on": served_on,
                    "service_date": _iso(when), "status": "open"}),
                p("deadline", f"rfp-set-{n}-response", {
                    "label": f"Responses to {label}", "trigger_date": _iso(when),
                    "days": int(days), "status": "open", "related_request": f"rfp-set-{n}",
                    "authority": meta.title}),
            ]

        if m := re.fullmatch(
            rf"Defendant's counsel requested a (\d+)-day extension to respond to the {ORDINAL} "
            r"Set of Requests for Production, and Plaintiff's counsel agreed\.", line
        ):
            days, ordinal = m.groups()
            n = _ORDINAL_NUM[ordinal]
            return [p("deadline", f"rfp-set-{n}-response", {"add_extension_days": int(days)})]

        if m := re.fullmatch(
            rf"Defendant served written responses and objections to the {ORDINAL} Set of Requests "
            rf"for Production on {LONG_DATE_PATTERN}\.", line
        ):
            ordinal, when = m.groups()
            n = _ORDINAL_NUM[ordinal]
            return [
                p("request", f"rfp-set-{n}", {"status": "responded", "response_date": _iso(when)}),
                p("deadline", f"rfp-set-{n}-response", {"status": "satisfied", "satisfied_on": _iso(when)}),
            ]

        if m := re.fullmatch(
            rf"The Third-Party Complaint was served on {LONG_DATE_PATTERN}\. The Third-Party "
            r"Defendant's answer is due within (\d+) days after service\.", line
        ):
            when, days = m.groups()
            return [p("deadline", "tp-answer", {
                "label": "Third-party defendant's answer", "trigger_date": _iso(when),
                "days": int(days), "status": "open", "authority": meta.title})]

        return []
