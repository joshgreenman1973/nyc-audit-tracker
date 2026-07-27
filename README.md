# The audit files

Tracker of every New York City Comptroller and New York State Comptroller audit of New York City agencies, programs and spending since January 1, 2026, restated in plain language with links to official sources.

## How it works

- `scripts/fetch_audits.py` — scrapes both comptrollers' sites for audits issued on or after 2026-01-01 and saves full page text to `data/audits_raw.json`. Fails loudly on empty results.
- `data/summaries/*.json` — one plain-language summary per audit, written only from the official page text (see `docs/methodology.html`).
- `scripts/build_site.py` — merges summaries into `docs/audits.json`; fails if any scraped audit lacks a summary.
- `docs/` — the static site, served by GitHub Pages.
- `.github/workflows/check-new-audits.yml` — weekly check that opens a GitHub issue when new audits appear that are not yet summarized.

## Updating

```bash
python3 scripts/fetch_audits.py
# write summaries for any new audits into data/summaries/
python3 scripts/build_site.py
```
