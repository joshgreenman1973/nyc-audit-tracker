# The audit files

Tracker of official watchdog reports on New York City government since January 1, 2025 — city comptroller and state comptroller audits, Department of Investigation reports and federal court monitor reports — restated in plain language with implementation status and links to official sources.

Live: https://joshgreenman1973.github.io/nyc-audit-tracker/

## How it works

- `scripts/fetch_audits.py` — scrapes both comptrollers' sites for audits issued on or after 2025-01-01 into `data/audits_raw.json`. State comptroller audits are filtered to city-government audited entities (no MTA, no state agencies). Fails loudly on empty results.
- `scripts/fetch_rec_status.py` — pulls per-recommendation implementation statuses from the NYC Comptroller's official Audit Recommendations Tracker (public Power BI API) into `data/nyc_rec_status.json`.
- `data/summaries/*.json` — one plain-language summary per report, written only from the official text per `data/SUMMARY_SPEC.md` (and `SUMMARY_SPEC_EXTRA.md` for DOI/monitor sources). DOI and monitor source text is preserved in `data/raw_extra/`.
- `scripts/verify_summaries.py` — verifies every quote and number in every summary against its source text.
- `scripts/build_site.py` — merges summaries into `docs/audits.json`, joining implementation statuses by audit number; fails if any scraped comptroller audit lacks a summary.
- `docs/` — the static site, served by GitHub Pages.
- `.github/workflows/check-new-audits.yml` — weekly: refreshes audits and implementation statuses, rebuilds and commits; opens a GitHub issue when new audits need summaries.

## Updating by hand

```bash
python3 scripts/fetch_audits.py
python3 scripts/fetch_rec_status.py
# write summaries for any new reports into data/summaries/
python3 scripts/verify_summaries.py
python3 scripts/build_site.py
```
