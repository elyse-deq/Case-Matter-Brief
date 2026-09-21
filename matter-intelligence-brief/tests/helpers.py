from datetime import date

from matter_brief.cli import DEFAULT_DATA_DIR, load_demo
from matter_brief.extractors import RulesExtractor
from matter_brief.pipeline import ingest
from matter_brief.store import Store


def run_demo(approve: bool = True, upto: int | None = None) -> tuple[Store, str, list]:
    matter, docs = load_demo(DEFAULT_DATA_DIR)
    store = Store()
    store.create_matter(matter["id"], matter["name"], matter["court"], matter["matter_type"])
    results = []
    for meta, text in docs[:upto]:
        results.append(ingest(store, RulesExtractor(), matter["id"], meta, text,
                              approve_material=approve, actor="test-reviewer"))
    return store, matter["id"], results


def as_of(iso: str) -> date:
    return date.fromisoformat(iso)
