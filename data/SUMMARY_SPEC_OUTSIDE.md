# Summary spec for outside groups (think tanks, research centers, civic organizations)

Read data/SUMMARY_SPEC.md first. Everything there applies — grounding, verbatim quotes, plain language, sentence case, no Oxford comma, no em dashes in your own prose — except where amended here.

## What belongs in this layer

White papers, reports, studies and substantial policy briefs from non-governmental organizations that make recommendations to New York City government. **Not testimony, letters, bill memos, op-eds, press releases, blog posts or commentary.**

These organizations have no standing over any agency. Nothing here carries an implementation status, and nothing here should be worded as though an agency failed a duty.

## Workflow per report

1. Your batch file lists items as {title, url, issued, publisher, publisher_name}.
2. Fetch the report. Many are PDFs: download and extract text with python3 + pypdf. Some are HTML pages.
3. Save the extracted text to `data/raw_extra/<slug>.txt` (full text, or the first 300k characters always including the executive summary and the recommendations section). Every quote and number you write must be a verbatim substring of this file.
4. Write `data/summaries/<slug>.json`. Slug: `<yyyy-mm-dd>-<publisher-id>-<short-kebab-title>`, max 80 characters.

## Schema (exact keys, in this order)

```json
{
  "id": "<slug>",
  "source": "outside",
  "auditor": "<publisher_name, e.g. Citizens Budget Commission>",
  "title": "<official title>",
  "plain_title": "<short plain-language restatement, sentence case, max 70 chars>",
  "agency": "<who the proposals are addressed to: a specific agency where the report names one (e.g. 'New York City Department of Housing Preservation and Development'), otherwise 'New York City government' or 'New York City Council'>",
  "issued": "<from the batch>",
  "url": "<landing page, else the PDF URL>",
  "pdf": "<PDF URL if there is one, else empty string>",
  "what_they_audited": "<1-2 sentences: what the report examines and what kind of document it is, e.g. 'A report from ... examining ...'>",
  "background": "<1-2 sentences of factual context from the report itself>",
  "findings": [ {"plain": "<one of the report's main factual findings, 1-2 sentences>", "quote": "<short VERBATIM supporting phrase, or empty string>"} ],
  "numbers": [ {"value": "<figure exactly as printed>", "label": "<plain label, max 60 chars>"} ],
  "recommendations": [ "<each proposal restated plainly, one per string, in the report's own order>" ],
  "agency_response": "",
  "implementation_note": "",
  "compliance_note": "",
  "topics": [ "1-3 from: education, health, housing, homelessness, social services, small business, environment, public safety, technology, money and contracts, seniors, children and youth, transparency, transportation, labor" ],
  "is_followup": false
}
```

## Rules specific to this layer

- **Neutrality is the whole game.** Restate what the organization proposes, in its own terms, without endorsing or undercutting it. Never write that a proposal is sensible, overdue, ideological or controversial. Never compare it to a government finding. The reader decides.
- Do not import the organization's rhetoric either: if a report says a policy is "disastrous," that belongs only inside a verbatim quote, not in your plain-language restatement.
- `agency_response` and `implementation_note` are always empty strings — no agency answers these.
- If a report turns out to make no actual recommendations (pure empirical research), do NOT write a summary. Add its url and title to `data/outside_no_recs.json` with a one-line reason and move on.
- If a report is not substantially about New York City government, do the same and note "not NYC government."
- Recommendations lead with the idea, in the imperative, without the report's own numbering ("Expand the Fair Fares program to ...", not "Recommendation 3: ...").

Report at the end: files written with finding/recommendation counts, plus anything skipped and why.
