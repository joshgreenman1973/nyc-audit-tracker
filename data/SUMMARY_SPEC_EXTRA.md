# Spec extension for non-comptroller sources (DOI, court monitors)

Read data/SUMMARY_SPEC.md first. Everything there applies except where amended here.

## Scope
Only reports issued on or after 2025-01-01 that examine New York City government operations and contain findings plus recommendations (or, for court monitors, compliance assessments). Skip press releases about arrests or indictments with no report attached.

## Workflow differences
1. You are fetching from live websites, not audits_raw.json. For each report: fetch the listing page, then download the report PDF to the scratchpad, extract text with python3 + pypdf (or pymupdf), and work from that extracted text.
2. Save the extracted text of each report you summarize to `data/raw_extra/<slug>.txt` (create the dir; full text, or the first 300k characters for very long reports — always including the executive summary, findings/compliance and recommendations sections). Quotes and numbers in your summary must be verbatim substrings of this saved file.
3. Also append an entry per report to your own index file `data/sources_<name>.json` (array of {title, issued, url, pdf}) where <name> is given in your task prompt.
4. Slug: `<yyyy-mm-dd>-<shortened-kebab-title>` (max 80 chars).

## Schema amendments
- "source": use the value given in your task prompt (e.g. "doi" or "monitor").
- "auditor": use the display string given in your task prompt.
- "url": the report's landing page if one exists, else the PDF URL. "pdf": the PDF URL.
- Add optional key "compliance_note" after "implementation_note": for court monitor reports, 1-2 plain sentences stating the monitor's overall compliance assessment from the report text; else "".
- For monitor reports whose structure is compliance ratings rather than recommendations: findings = the report's principal assessments; recommendations = any recommendations or required actions the report states (if it states none, use the single entry "The report makes no new formal recommendations.").
- "agency" = the government entity being overseen (e.g. "New York City Police Department", "New York City Department of Correction").

## Honesty rules (unchanged and critical)
Every fact from the report text only. Verify every quote and number against the saved txt file before finishing. If a PDF cannot be downloaded or parsed, skip it and say so in your final report rather than summarizing from memory or from news coverage.
