# Design principles

1. **The model is not the system of record.** Models propose. A structured record holds the truth. Evidence-graph designs follow the same idea: the model reasons over verified records and never becomes the record.
2. **No source, no fact.** A proposal without a verbatim quote that appears in the document is rejected and logged. A model that infers a date the document never states is rejected the same way.
3. **Deadlines are code.** Extractors capture the trigger date and the period. A deterministic engine computes the due date, so it is the same every time and easy to audit.
4. **Humans approve what matters.** New or moved deadlines and new adverse parties go to a lawyer before they reach the brief. The rest is applied and logged.
5. **Show what changed.** Every brief opens with what the latest document changed. A brief that silently rewrites itself cannot be trusted.
6. **Keep the model swappable.** The extractor is an interface. The same pipeline runs with rules, a local model, a hosted model, or a firm's existing legal AI platform.
7. **Evaluate against labels.** `eval/` scores any extractor on precision, recall, and due-date accuracy, so a change of model or prompt is a measurement and not a guess.
