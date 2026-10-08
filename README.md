# The audit files

Tracker of official watchdog reports on New York City government since January 1, 2025 — city comptroller and state comptroller audits, Department of Investigation reports, court monitor reports and independent oversight board reports — restated in plain language with implementation status and links to official sources.

Live: https://joshgreenman1973.github.io/nyc-audit-tracker/

## How it works

- `scripts/fetch_audits.py` — scrapes both comptrollers' sites for audits issued on or after 2025-01-01 into `data/audits_raw.json`. State comptroller audits are filtered to city-government audited entities (no MTA, no state agencies). Fails loudly on empty results.
- `scripts/fetch_rec_status.py` — pulls per-recommendation implementation statuses from the NYC Comptroller's official Audit Recommendations Tracker (public Power BI API) into `data/nyc_rec_status.json`.
- `data/summaries/*.json` — one plain-language summary per report, written only from the official text per `data/SUMMARY_SPEC.md` (and `SUMMARY_SPEC_EXTRA.md` for DOI/monitor sources). DOI and monitor source text is preserved in `data/raw_extra/`.
- `scripts/verify_summaries.py` — verifies every quote and number in every summary against its source text.
- `scripts/draft_summaries.py` — drafts summaries for new comptroller audits (`--comptroller`) and outside reports on the ingest worklist (`--outside`) with the Claude API (`claude-sonnet-5-5`), to the same specs. A draft is published only if it passes the verifier's quote and number check, a check that every figure in the prose is in the source, the spec's field rules, the comptroller tracker's recommendation count where available, and a separate Claude review pass for unsupported statements, missing recommendations, editorializing and acronyms (up to two revisions). Failures go to `data/drafts/<slug>.json` with the problems found; outside reports the model would rule out go to `data/outside_triage.json` as suggestions only. Published drafts carry `"ai_draft": {"model", "drafted", "human_reviewed": false}`, and the site labels those cards until `human_reviewed` is set to true. Needs the `ANTHROPIC_API_KEY` repository secret; without it the step exits 0 and changes nothing. Spend is capped per run (`--max-cost`, default $3).
- `scripts/build_site.py` — merges summaries into `docs/audits.json`, joining implementation statuses by audit number; fails if any scraped comptroller audit lacks a summary.
- `data/sources_*.json` — per-body indexes of the non-comptroller reports folded in: `sources_doi`, `sources_floyd` (NYPD stop and frisk monitor), `sources_nunez` (Rikers jails monitor), `sources_nycha` (NYCHA federal co-monitors), `sources_lv` (L.V. v. DOE special master and independent auditor), `sources_boc` (Board of Correction) and `sources_ccpc` (Commission to Combat Police Corruption).
- `docs/` — the static site, served by GitHub Pages.
- `.github/workflows/check-new-audits.yml` — weekly: refreshes audits and implementation statuses, drafts summaries for new audits, verifies, rebuilds and commits; opens a GitHub issue when new audits still need summaries.
- `.github/workflows/outside-ingest.yml` — on the 1st and 15th: re-crawls outside publishers, drafts summaries for new reports, rebuilds the worklist (`data/outside_new.md`) and opens an issue when reports still need a person.

## Updating by hand

```bash
python3 scripts/fetch_audits.py
python3 scripts/fetch_rec_status.py
# draft summaries for new reports (or write them by hand into data/summaries/)
ANTHROPIC_API_KEY=... python3 scripts/draft_summaries.py --comptroller --outside
python3 scripts/verify_summaries.py
python3 scripts/build_site.py
```
