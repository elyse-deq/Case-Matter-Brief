# From demo to real matters

This repository runs on synthetic documents. Real matters need more than the pipeline.

## Sources

| Source | Why | Notes |
| --- | --- | --- |
| Document management (iManage, NetDocuments) | Filings, orders, drafts, correspondence | New or changed document is the natural trigger for an update |
| Email and calendar (Microsoft 365) | Extensions, requests, and agreements often live only in email | Highest value and highest noise, so filter to matter-tagged threads |
| Court dockets | Orders and deadlines set by the court | Treat the docket as authoritative for court dates |
| Billing and matter intake | Matter number, client, team | Gives the matter its identity and its permissions |

## Where Harvey fits

For a firm that licenses Harvey, Vault and Workflow Builder can perform the extraction step. Implement `extractors/harvey_stub.py` so a workflow's structured output becomes proposals. Confirm three things first: whether workflow and Vault outputs are available through an API or export, whether a workflow can be triggered by a new document, and whether every extracted value carries a source passage. If values arrive without a source passage, the validation gate will reject them, which is the intended behavior.

Everything downstream of extraction (validation, change log, review queue, deadline engine, brief) stays the same. The brief can then be surfaced in Word, Teams, or a dashboard such as a legal operations view that already shows matter status.

## Non-negotiables before a pilot

- **Permissions and ethical walls.** A brief must never show a person something they cannot see in the source system. Inherit access from the document management system, and treat a wall as a hard filter, not a UI hint.
- **Privilege and confidentiality.** Decide where documents and extracted text are stored, who can read the record, and whether a local model is required for the most sensitive matters.
- **Audit.** The change log and rejection log are the audit trail. Keep them, and keep who approved what.
- **Human sign-off on deadlines.** The brief supports a docketing process. It does not replace one.
- **Retention.** Follow the firm's retention and deletion rules for the record and the logs.

## Pilot shape

Start with one matter type and one friendly team. Measure the time saved building and refreshing a matter status, the number of extractions a lawyer corrected, and the number of proposals the validation gate rejected. Expand only when the correction rate is low and stable.
