# Harvey sample rows

Synthetic review table rows for the demo matter, in the shape of the `get_row` response in Harvey's public developer docs (`response.cells[]` with `column_name`, `summary`, `citations[].citation_quote`, and verification flags).

These are **assumed, not exported from a real Harvey workspace**. The column names are invented for this demo. They exist so the Harvey adapter can be run and tested offline.

- `DOC-003.row.json`: scheduling order (dates and deadlines)
- `DOC-004.row.json`: first requests for production (request, trigger date, period). One citation quote is deliberately cut off mid-word, as Harvey's can be.
- `DOC-007.row.json`: third-party complaint (new party, answer deadline). One cell is "Not found" and is skipped.
- `column_map.json`: which column feeds which field of the matter record

Run it: `matter-brief demo --extractor harvey-sample`
