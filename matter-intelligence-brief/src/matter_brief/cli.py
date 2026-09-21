"""Command line interface.

    matter-brief demo                       run the synthetic matter end to end
    matter-brief init ...                   create a matter
    matter-brief ingest ...                 add one document and update the record
    matter-brief review --matter-id ID      list, approve, or reject pending changes
    matter-brief brief --matter-id ID       print the current brief
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from .brief import build_brief, describe_change, render_html, render_markdown
from .extractors import LLMExtractor, RulesExtractor, anthropic_complete, ollama_complete
from .models import DocumentMeta
from .pipeline import ingest
from .store import Store

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "synthetic_matter"


def build_extractor(name: str, provider: str | None = None, model: str | None = None):
    if name == "rules":
        return RulesExtractor()
    if name == "llm":
        if provider == "anthropic":
            return LLMExtractor(anthropic_complete(model))
        if provider == "ollama":
            return LLMExtractor(ollama_complete(model))
        raise SystemExit("--extractor llm requires --provider anthropic or --provider ollama")
    raise SystemExit(f"unknown extractor: {name}")


def load_demo(data_dir: Path) -> tuple[dict, list[tuple[DocumentMeta, str]]]:
    manifest = json.loads((data_dir / "manifest.json").read_text(encoding="utf-8"))
    docs = []
    for d in manifest["documents"]:
        meta = DocumentMeta(d["doc_id"], d["title"], d["doc_type"], d["received_at"])
        docs.append((meta, (data_dir / d["file"]).read_text(encoding="utf-8")))
    return manifest["matter"], docs


def cmd_demo(args: argparse.Namespace) -> int:
    matter, docs = load_demo(Path(args.data_dir))
    db_path = Path(args.out) / "demo.db"
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    store = Store(str(db_path))
    store.create_matter(matter["id"], matter["name"], matter.get("court", ""), matter.get("matter_type", ""))
    extractor = RulesExtractor()

    print(f"Matter: {matter['name']}")
    print("Reviewer: " + ("auto-approving material changes" if not args.no_approve
                          else "material changes wait in the review queue"))
    for n, (meta, text) in enumerate(docs, start=1):
        result = ingest(store, extractor, matter["id"], meta, text, approve_material=not args.no_approve,
                        actor="demo-reviewer")
        print(f"\n[{n}] {meta.received_at}  {meta.title}")
        for cid in result.change_ids:
            ch = store.get_change(cid)
            flag = " (material)" if ch["material"] else ""
            print(f"    {ch['status']:<8}{flag:<11} {describe_change(ch)}")
        if not result.change_ids:
            print("    no record changes")
        if result.rejected:
            print(f"    {result.rejected} proposal(s) rejected by validation")
        brief = build_brief(store, matter["id"], as_of=date.fromisoformat(meta.received_at))
        (out_dir / f"brief_{n:02d}.md").write_text(render_markdown(brief), encoding="utf-8")

    final = build_brief(store, matter["id"])
    (out_dir / "brief.md").write_text(render_markdown(final), encoding="utf-8")
    (out_dir / "brief.html").write_text(render_html(final), encoding="utf-8")
    print(f"\nWrote briefs to {out_dir}/ (brief_01.md ... brief.md, brief.html)")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    Store(args.db).create_matter(args.matter_id, args.name, args.court, args.type)
    print(f"Created matter {args.matter_id}")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    store = Store(args.db)
    text = Path(args.file).read_text(encoding="utf-8")
    meta = DocumentMeta(args.doc_id, args.title, args.type, args.received)
    extractor = build_extractor(args.extractor, args.provider, args.model)
    result = ingest(store, extractor, args.matter_id, meta, text, approve_material=args.approve,
                    actor=args.by)
    if result.skipped:
        print("Skipped: this document was already ingested.")
        return 0
    for cid in result.change_ids:
        ch = store.get_change(cid)
        print(f"#{cid} {ch['status']}: {describe_change(ch)}")
    if result.rejected:
        print(f"{result.rejected} proposal(s) rejected by validation.")
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    store = Store(args.db)
    if args.approve:
        ids = [c["id"] for c in store.pending(args.matter_id)] if args.approve == "all" else [int(args.approve)]
        for cid in ids:
            store.decide(cid, True, args.by)
            print(f"Approved #{cid}")
    elif args.reject:
        store.decide(int(args.reject), False, args.by)
        print(f"Rejected #{args.reject}")
    else:
        pending = store.pending(args.matter_id)
        if not pending:
            print("Nothing awaiting review.")
        for c in pending:
            print(f"#{c['id']} [{c['source_doc_id']}] {describe_change(c)}\n      \"{c['quote']}\"")
    return 0


def cmd_brief(args: argparse.Namespace) -> int:
    store = Store(args.db)
    as_of = date.fromisoformat(args.as_of) if args.as_of else None
    brief = build_brief(store, args.matter_id, as_of=as_of)
    text = render_html(brief) if args.format == "html" else render_markdown(brief)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"Wrote {args.out}")
    else:
        print(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="matter-brief", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("demo", help="run the synthetic matter end to end")
    p.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    p.add_argument("--out", default="output")
    p.add_argument("--no-approve", action="store_true", help="leave material changes in the review queue")
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("init", help="create a matter")
    p.add_argument("--db", default="matter_brief.db")
    p.add_argument("--matter-id", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--court", default="")
    p.add_argument("--type", default="")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("ingest", help="add a document and update the record")
    p.add_argument("--db", default="matter_brief.db")
    p.add_argument("--matter-id", required=True)
    p.add_argument("--file", required=True)
    p.add_argument("--doc-id", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--type", default="")
    p.add_argument("--received", required=True, help="ISO date the document arrived")
    p.add_argument("--extractor", choices=["rules", "llm"], default="llm")
    p.add_argument("--provider", choices=["anthropic", "ollama"])
    p.add_argument("--model")
    p.add_argument("--approve", action="store_true", help="approve material changes immediately")
    p.add_argument("--by", default="reviewer")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("review", help="list, approve, or reject pending changes")
    p.add_argument("--db", default="matter_brief.db")
    p.add_argument("--matter-id", required=True)
    p.add_argument("--approve", help="change id, or 'all'")
    p.add_argument("--reject", help="change id")
    p.add_argument("--by", default="reviewer")
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("brief", help="print the current brief")
    p.add_argument("--db", default="matter_brief.db")
    p.add_argument("--matter-id", required=True)
    p.add_argument("--format", choices=["md", "html"], default="md")
    p.add_argument("--as-of", help="ISO date used for days remaining")
    p.add_argument("--out")
    p.set_defaults(func=cmd_brief)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
