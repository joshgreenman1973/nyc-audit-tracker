# Scope: adding an outside-government layer

Not built. This is what it would take.

## The hard part is not the scraping

Everything in the tracker today shares three properties that make "implementation status" meaningful:

1. The watchdog has standing — a charter mandate, a state statute or a court order.
2. The audited agency is obliged to respond, and usually does, in writing.
3. For city comptroller audits, someone official publishes whether the fix happened.

Outside groups have none of these. A Manhattan Institute or Fiscal Policy Institute recommendation is an argument addressed to government, not a finding government must answer. If those recommendations sit in the same list as an audit finding with a "Not implemented" chip, the tracker implies a city agency blew off an obligation it never had. That is the whole design problem. Everything below follows from it.

**Recommended treatment:** a separate, clearly labeled layer — a second tab or a toggle ("Official watchdogs" / "Outside proposals"), never merged silently into the same list. Different badge color family, no status chips, and an explicit line on each card saying no agency is obliged to respond. The methodology page gets a new section drawing the line between oversight and advocacy.

## Decisions only Josh can make

These change the product, not just the build:

1. **What qualifies.** Proposed bar: a published report or testimony that makes explicit, addressable recommendations to New York City government. That admits CBC reports and testimony, CUF's "5 ideas" reports, 5BORO policy proposals; it excludes op-eds, press statements, event recaps, data dashboards and general commentary. CBC helpfully types its own items (REPORT, TESTIMONY, STATEMENT, OP ED, PRESENTATION, DATA DASHBOARD), so the filter is mechanical there and editorial elsewhere.
2. **Viewpoint range and labeling.** Manhattan Institute and Fiscal Policy Institute sit at opposite poles; Citizens Budget Commission, Furman and CUF occupy different ground again. A list of "what should change in New York City" that spans them needs a stated stance. Three options: (a) include broadly with a neutral orientation note per organization, (b) include broadly with no label and let the org's name carry it, (c) curate to a defined set. Option (b) is the least editorializing and the most defensible; option (a) invites endless argument about who gets called what.
3. **Vital City.** Your own organization. If it is in the layer it needs a disclosure line on the card and in the methodology, or it stays out. Recommend disclosing and including.
4. **Relationship to the official layer.** The interesting version connects them: on a housing page, show what the comptroller found and separately what outside groups propose. The cheap version keeps them in parallel with no linkage. Thematic linkage would be AI-inferred, which is a different evidentiary standard than anything in the tracker today — if we do it, it should be presented as "related reading," never as a claim that the proposal answers the finding.

## Technical feasibility, checked

| Organization | Access | Notes |
|---|---|---|
| Center for an Urban Future | HTML listing, paginated | `nycfuture.org/research`, typed as Reports / Data / Commentary / Testimony. Clean. ~20+ items over 8 months. |
| Manhattan Institute | RSS (`manhattan.institute/rss.xml`) | Feed carries only ~10 recent items, so it needs a listing crawl for backfill. Heavy national output; needs a New York City filter. |
| Fiscal Policy Institute | WordPress, `/feed` plus `wp-json` REST API | Easiest of the set. State-and-city mix, needs a city filter. |
| 5BORO Institute | WordPress, `fiveboro.nyc/feed/` | Note: 5BORO announced a merger with Citizens Union, so treat as one publisher going forward. |
| Center for New York City Affairs | Squarespace, `?format=rss` | Feed returns 20 items. Straightforward. |
| Citizens Union | HTML library + testimony/letters | Also runs Searchlight, an editorial platform launched June 2026, which is commentary rather than a recommendations database. |
| Vital City | Ghost Content API | Already have the key and a working pattern from other projects. |
| Furman Center | HTML listing at `furmancenter.org/research` | Empirical research more than recommendations; may fail the inclusion bar more often than it passes. Worth a sampling test before committing. |
| Citizens Budget Commission | **Cloudflare-blocked to scripts (403)** | Renders fine in a real browser — verified. Needs a browser-driven fetch step, which is slower and more fragile than the rest. The one genuine engineering wrinkle. |

## Volume and cost

Rough order: 150 to 300 qualifying publications per year across the set, against 122 official reports over 19 months. **The outside layer would be several times larger than the tracker it is being added to** — which is itself an argument for keeping it visually distinct and for a tighter inclusion bar.

Summarizing at current quality (grounded, quote-verified) runs a few dollars of model time per 25 reports; the real cost is the maintenance surface: nine publishers, nine breakage modes, versus the four stable government sources today.

## What the build looks like

- **Phase 1, one session:** publisher registry with per-source adapters (RSS where it exists, HTML where it does not, browser fetch for CBC), the inclusion filter, and a backfill to a chosen cutoff. Deliverable: `data/outside_raw.json`, failing loud like the existing scrapers.
- **Phase 2, one session:** summaries under an extended spec — same grounding rules, plus a "who is asking" field and an explicit no-obligation note. Verification script extends unchanged.
- **Phase 3, one session:** the second layer in the interface, methodology rewrite, disclosure lines, and the weekly job extended to the new sources.
- **Optional Phase 4:** thematic linkage between outside proposals and official findings, presented as related reading only.

Cutoff question: matching the tracker's January 1, 2025 start is consistent, but for advocacy work older proposals go stale faster than audit findings do. A 12-month rolling window may serve readers better, with the freshness sort already built.

## Risks

- **False equivalence.** The main one. Mitigated by separation and labeling, not by disclaimers alone.
- **Maintenance.** Nine publishers on their own redesign schedules. The fail-loud pattern turns silent rot into a visible issue, which is the right trade.
- **Copyright.** Summaries and short quotes with attribution and links, as now. No reproduction of report text.
- **Scope creep.** "Many others" is a long tail — dozens of advocacy organizations publish recommendations. The registry should be an explicit, defensible list with stated criteria, not a best-effort sweep.
