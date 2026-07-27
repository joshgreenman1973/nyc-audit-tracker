# Summary spec for The audit files

You are writing grounded plain-language summaries of official watchdog audits of New York City government for a public tracker. Your batch is defined in `data/batches.json` (array index given in your task prompt): each item is `[url, slug]`.

## Workflow per audit
1. Extract that audit's entry from `data/audits_raw.json` (match the `url` field). Use a short python3 command to write the single entry to a temp file, then Read it. Do NOT read the whole audits_raw.json (it is very large).
2. Write `data/summaries/<slug>.json` using the exact slug given in the batch (never derive your own).

## Schema (exact keys, in this order)
```json
{
  "id": "<slug>",
  "source": "nyc" | "osc",
  "auditor": "New York City Comptroller" | "New York State Comptroller",
  "title": "<official title from data>",
  "plain_title": "<short plain-language restatement, sentence case, max 70 chars>",
  "agency": "<audited agency in natural word order, e.g. 'New York City Department for the Aging'>",
  "issued": "<from data>",
  "url": "<from data>",
  "pdf": "<from data>",
  "what_they_audited": "<1-2 sentences, plain language>",
  "background": "<1-2 sentences of factual context from the report's own background/about sections>",
  "findings": [ {"plain": "<one finding in plain language, 1-2 sentences>", "quote": "<short VERBATIM supporting sentence or phrase from the source text, or empty string>"} ],
  "numbers": [ {"value": "<figure exactly as in the text, e.g. '$11.8 million'>", "label": "<plain label, max 60 chars>"} ],
  "recommendations": [ "<each recommendation restated plainly, one string each, in the report's own order and count — if the report numbers them, item 1 = recommendation 1, etc.>" ],
  "agency_response": "<1-2 sentences on the audited agency's response if the text states one; else \"\">",
  "implementation_note": "<ONLY for follow-up audits or when the text states the status of earlier recommendations: one plain sentence with the counts, e.g. 'Of the 6 recommendations in the 2022 audit, the follow-up found 4 implemented and 2 partially implemented.' Else \"\">",
  "topics": [ "1-3 from: education, health, housing, homelessness, social services, small business, environment, public safety, technology, money and contracts, seniors, children and youth, transparency, transportation, labor" ],
  "is_followup": true | false
}
```

## Hard rules
- Ground every statement in the entry's `sections` text. Never add a fact, name or number that is not in the source. Every `numbers` value must appear VERBATIM in the source text.
- Quotes must be exact substrings of the source text (you may trim with `...` at either end). Verify each one by searching the text before writing it.
- Plain language: explain like a smart friend would. Spell out every acronym on first use within that summary, using only expansions the source itself provides.
- Neutral, factual tone. No opinions or editorializing. Sentence case. Never use the Oxford comma. No em dashes in your own prose. Straight apostrophes in your own prose; keep the source's curly characters inside verbatim quotes.
- 3-7 findings covering the audit's main findings (fewer only if the report itself has fewer). Cover ALL recommendations, same order and count as the report.
- For NYC "Review" or "Letter report" documents: treat key takeaways as findings and suggestions as recommendations, and note the document type in `what_they_audited`. If a letter report genuinely contains no recommendations, use a single recommendations entry: "The report makes no formal recommendations."
- `is_followup`: true when the title says Follow-up/Follow-Up.
- After writing all files in your batch, verify each parses as JSON (python3 json.load) and report file paths + finding/recommendation counts as your final text.
