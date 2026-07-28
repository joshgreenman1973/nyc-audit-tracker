#!/usr/bin/env python3
"""Fortnightly ingest for the outside-groups layer.

Re-crawls every registered outside publisher, applies the inclusion bar, and
reports which reports are new since the last run — that is, present in the
crawl but with no summary in data/summaries/.

Writes data/outside_new.md (a human-readable worklist) and exits nonzero when
there is new work, so the scheduled job can open an issue.

Publishers marked "fetch": "browser" (Cloudflare-blocked) cannot run headless.
They are listed separately in the report as needing a browser pass, so they
fail visibly rather than silently going stale.
"""
import json
import re
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REG = ROOT / "data" / "publishers.json"
SUMDIR = ROOT / "data" / "summaries"
INDEX = ROOT / "data" / "outside_index.json"
NORECS = ROOT / "data" / "outside_no_recs.json"
OUT = ROOT / "data" / "outside_new.md"

# Only look back a window; the backfill is already done.
LOOKBACK_DAYS = 120


def known_urls():
    """Every outside URL already summarized or already ruled out."""
    urls = set()
    for f in SUMDIR.glob("*.json"):
        s = json.loads(f.read_text())
        if s.get("source") == "outside":
            urls.add(s.get("url", "").rstrip("/"))
            if s.get("pdf"):
                urls.add(s["pdf"].rstrip("/"))
    if NORECS.exists():
        for r in json.loads(NORECS.read_text()):
            if r.get("url"):
                urls.add(r["url"].rstrip("/"))
    return urls


def main():
    if not REG.exists():
        sys.exit(f"FAIL: no publisher registry at {REG}")

    # Reuse the discovery crawl; it already handles every adapter.
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "fetch_outside.py")],
                          capture_output=True, text=True)
    print(proc.stdout)
    if proc.stderr.strip():
        print(proc.stderr, file=sys.stderr)
    if not INDEX.exists():
        sys.exit("FAIL: crawl produced no index")

    items = json.loads(INDEX.read_text())
    if not items:
        sys.exit("FAIL: crawl returned zero candidates across all publishers")

    cutoff = (date.today() - timedelta(days=LOOKBACK_DAYS)).isoformat()
    seen = known_urls()
    reg = json.loads(REG.read_text())

    # Some publishers mix reports and commentary in one undifferentiated stream,
    # so a crawl cannot tell which items clear the reports-only bar. Listing
    # every item would bury the real work, so they are named for a manual pass
    # instead of padding the worklist.
    manual = {p["id"] for p in reg if p.get("auto_ingest") is False}
    browser_pubs = [p["id"] for p in reg
                    if p.get("fetch") == "browser" and p.get("verdict") in ("include", "borderline")]

    fresh = [i for i in items
             if i.get("issued", "") >= cutoff
             and i.get("url", "").rstrip("/") not in seen
             and i.get("publisher") not in manual]

    lines = [f"# Outside reports needing review ({date.today().isoformat()})", ""]
    if fresh:
        lines.append(f"{len(fresh)} candidate reports published since {cutoff} are not yet "
                     "summarized or ruled out:\n")
        by_pub = {}
        for i in fresh:
            by_pub.setdefault(i.get("publisher_name") or i.get("publisher"), []).append(i)
        for pub, rows in sorted(by_pub.items(), key=lambda kv: -len(kv[1])):
            lines.append(f"## {pub} ({len(rows)})")
            for r in sorted(rows, key=lambda x: x["issued"], reverse=True):
                lines.append(f"- {r['issued']} [{r['title']}]({r['url']})")
            lines.append("")
    else:
        lines.append("No new outside reports in the window.\n")

    if browser_pubs:
        lines.append("## Needs a browser pass (Cloudflare-blocked, not crawled here)")
        lines.append(", ".join(browser_pubs))
        lines.append("")
        lines.append("These cannot be fetched headlessly, so they go stale silently unless "
                     "checked by hand. Run the browser collector for them.")
        lines.append("")

    if manual:
        lines.append("## Needs a manual pass (reports not mechanically separable)")
        lines.append(", ".join(sorted(manual)))
        lines.append("")
        lines.append("These publishers mix reports with commentary in one stream, so the crawl "
                     "cannot tell which items clear the reports-only bar. Review their listings "
                     "by hand rather than trusting an empty worklist here.")

    OUT.write_text("\n".join(lines))
    print(f"\n{len(fresh)} new candidates -> {OUT}")
    if fresh:
        sys.exit(1)   # signal the scheduled job to open an issue


if __name__ == "__main__":
    main()
