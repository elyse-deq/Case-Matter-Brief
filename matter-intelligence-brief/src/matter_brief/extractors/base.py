from __future__ import annotations

from typing import Protocol

from ..models import DocumentMeta, Proposal


class Extractor(Protocol):
    """Anything that turns one document into proposed record changes.

    Extractors only propose. They never write to the record, never compute
    deadlines, and never decide what is material. The pipeline does that.
    """

    name: str

    def extract(self, meta: DocumentMeta, text: str) -> list[Proposal]:
        ...
