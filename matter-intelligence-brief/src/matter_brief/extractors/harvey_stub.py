"""Where Harvey would plug in.

Harvey Vault and Workflow Builder can perform the extraction step for a firm that
licenses them: run a workflow over the new document, take the structured output,
and convert each row into a Proposal (kind, key, data, verbatim quote).

Not implemented, on purpose. Before building this adapter, confirm with Harvey:
  1. Does the platform expose an API or export for workflow and Vault outputs?
  2. Can a workflow run be triggered by an event such as a new DMS document?
  3. Does each extracted value carry a source passage you can quote verbatim?

If the answer to (3) is no, the validation gate will reject the output, which is
the correct behavior: an unsourced fact should not reach the matter record.

Everything downstream (validation, change log, review queue, brief) is unchanged.
"""
from __future__ import annotations

from ..models import DocumentMeta, Proposal


class HarveyExtractor:
    name = "harvey"

    def extract(self, meta: DocumentMeta, text: str) -> list[Proposal]:
        raise NotImplementedError(
            "Harvey adapter is a stub. See the module docstring for what to confirm first."
        )
