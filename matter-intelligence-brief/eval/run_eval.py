"""Score an extractor against the synthetic matter's gold labels.

    python -m eval.run_eval                                   # rules extractor
    python -m eval.run_eval --extractor llm --provider ollama # a local model
    python -m eval.run_eval --min-f1 1.0                      # fail CI below a threshold

Two things are measured:
  proposals   did the extractor propose the right (kind, key) for each document,
              after the validation gate has thrown out anything ungrounded?
  due dates   does the final record compute the right due date for each deadline?

The rules extractor is written against these documents, so its score proves the
harness works, not that extraction is solved. The point of the harness is to
compare a real model against the same labels, and to catch regressions.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from matter_brief.cli import DEFAULT_DATA_DIR, build_extractor, load_demo
from matter_brief.deadlines import compute_due
from matter_brief.pipeline import ingest
from matter_brief.store import Store

GOLD = Path(__file__).with_name("gold.json")


def run(extractor_name: str, provider: str | None, model: str | None) -> tuple[float, float, float, float]:
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    matter, docs = load_demo(DEFAULT_DATA_DIR)
    store = Store()
    store.create_matter(matter["id"], matter["name"])
    extractor = build_extractor(extractor_name, provider, model)

    tp = fp = fn = rejected = 0
    print(f"{'document':<10} {'expected':>8} {'found':>6} {'missed':>7} {'extra':>6} {'rejected':>9}")
    for meta, text in docs:
        result = ingest(store, extractor, matter["id"], meta, text, approve_material=True, actor="eval")
        found = {f"{p.kind}/{p.key}" for p in result.accepted}
        expected = set(gold["proposals"][meta.doc_id])
        hit, missed, extra = found & expected, expected - found, found - expected
        tp, fn, fp, rejected = tp + len(hit), fn + len(missed), fp + len(extra), rejected + result.rejected
        print(f"{meta.doc_id:<10} {len(expected):>8} {len(hit):>6} {len(missed):>7} {len(extra):>6} {result.rejected:>9}")
        for m in sorted(missed):
            print(f"    missed: {m}")
        for e in sorted(extra):
            print(f"    extra:  {e}")

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    facts = {f.key: f for f in store.facts(matter["id"], "deadline")}
    correct = 0
    for key, expected_due in gold["final_due_dates"].items():
        due = compute_due(facts[key].data) if key in facts else None
        ok = due is not None and due.isoformat() == expected_due
        correct += ok
        print(f"due date {key:<24} expected {expected_due} got {due.isoformat() if due else 'none'} {'ok' if ok else 'WRONG'}")
    due_acc = correct / len(gold["final_due_dates"])

    print(f"\nprecision {precision:.2f}  recall {recall:.2f}  f1 {f1:.2f}  due-date accuracy {due_acc:.2f}  "
          f"rejected by validation {rejected}")
    return precision, recall, f1, due_acc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--extractor", choices=["rules", "llm"], default="rules")
    parser.add_argument("--provider", choices=["anthropic", "ollama"])
    parser.add_argument("--model")
    parser.add_argument("--min-f1", type=float, default=0.0)
    args = parser.parse_args()
    _, _, f1, due_acc = run(args.extractor, args.provider, args.model)
    return 0 if f1 >= args.min_f1 and (due_acc >= args.min_f1) else 1


if __name__ == "__main__":
    sys.exit(main())
