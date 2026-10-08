#!/usr/bin/env python3
"""Fortnightly ingest for the outside-groups layer.

Re-crawls every registered outside publisher, applies the inclusion bar, and
reports which reports are still open work: present in the crawl but neither
summarized in data/summaries/ nor ruled out in data/outside_no_recs.json.

Writes data/outside_new.md (a human-readable worklist) and exits nonzero when
there is open work or when any publisher's crawl failed, so the scheduled job
can open (or update) an issue.

Publishers marked "fetch": "browser" (Cloudflare-blocked) cannot run headless.
They are listed separately in the report as needing a browser pass, so they
fail visibly rather than silently going stale.

  --no-crawl   rebuild the worklist from the existing outside_index.json
               (used after scripts/draft_summaries.py has cleared items)
"""
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REG = ROOT / "data" / "publishers.json"
SUMDIR = ROOT / "data" / "summaries"
INDEX = ROOT / "data" / "outside_index.json"
NORECS = ROOT / "data" / "outside_no_recs.json"
TRIAGE = ROOT / "data" / "outside_triage.json"
DRAFTS = ROOT / "data" / "drafts"
OUT = ROOT / "data" / "outside_new.md"

# The backfill covered everything issued before the first fortnightly run's
# window. Anything issued on or after this date stays on the worklist until it
# is summarized or ruled out. (This used to be a rolling 120-day window, which
# let unworked reports age off the list without anyone deciding on them.)
FLOOR = "2026-03-30"


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


def manual_publishers(reg):
    """Publishers that mix reports and commentary in one stream."""
    return {p["id"] for p in reg if p.get("auto_ingest") is False}


def pending(items=None, reg=None):
    """Outside candidates that still need a human or automated decision."""
    if items is None:
        items = json.loads(INDEX.read_text())
    if reg is None:
        reg = json.loads(REG.read_text())
    seen = known_urls()
    manual = manual_publishers(reg)
    return [i for i in items
            if i.get("issued", "") >= FLOOR
            and i.get("url", "").rstrip("/") not in seen
            and i.get("publisher") not in manual]


def automation_notes():
    """url -> note from the automated drafter (suggested rule-out or failed draft)."""
    notes = {}
    if TRIAGE.exists():
        for t in json.loads(TRIAGE.read_text()):
            if t["decision"] == "source_incomplete":
                note = (f"automated drafting could not judge it from the text it could fetch: "
                        f"{t['reason']}")
            else:
                note = (f"automated triage suggests ruling out "
                        f"({t['decision'].replace('_', ' ')}): {t['reason']} To confirm, move "
                        f"the entry from data/outside_triage.json to data/outside_no_recs.json.")
            notes[t["url"].rstrip("/")] = note
    if DRAFTS.exists():
        for f in DRAFTS.glob("*.json"):
            d = json.loads(f.read_text())
            url = (d.get("url") or (d.get("summary") or {}).get("url") or "").rstrip("/")
            if url:
                notes[url] = (f"automated draft failed its checks; draft and problems in "
                              f"data/drafts/{f.name}")
    return notes


def fail(msg):
    """Exit nonzero, leaving a worklist that says why, so a later --no-crawl
    rebuild (and the issue) carries the failure instead of masking it."""
    OUT.write_text(f"# Outside reports needing review ({date.today().isoformat()})\n\n"
                   f"## Crawl failures\n- {msg}\n")
    sys.exit(f"FAIL: {msg}")


def previous_failures():
    """Crawl failures listed in the existing worklist (used with --no-crawl)."""
    if not OUT.exists():
        return []
    m = re.search(r"^## Crawl failures\n(.*?)(?=^## |\Z)", OUT.read_text(), re.S | re.M)
    return [ln[2:].strip() for ln in m.group(1).splitlines() if ln.startswith("- ")] if m else []


def crawl():
    """Run the discovery crawl. Returns the list of per-publisher failures."""
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "fetch_outside.py")],
                          capture_output=True, text=True)
    print(proc.stdout)
    if proc.stderr.strip():
        print(proc.stderr, file=sys.stderr)
    failures = []
    if proc.returncode != 0:
        block = proc.stdout.split("FAILURES:", 1)
        if len(block) == 2:
            failures = [ln.strip() for ln in block[1].splitlines() if ln.strip()]
        else:
            tail = (proc.stderr.strip() or proc.stdout.strip()).splitlines()[-3:]
            failures = ["fetch_outside.py exited %d: %s" % (proc.returncode, " / ".join(tail))]
    return failures


def main():
    no_crawl = "--no-crawl" in sys.argv[1:]
    if not REG.exists():
        sys.exit(f"FAIL: no publisher registry at {REG}")
    # Without a crawl, the last crawl's failures still stand; carry them over.
    failures = previous_failures() if no_crawl else []
    # A stale worklist from a previous run must never be mistaken for this run's.
    if OUT.exists():
        OUT.unlink()

    if not no_crawl:
        failures = crawl()
    if not INDEX.exists():
        fail("crawl produced no index")
    items = json.loads(INDEX.read_text())
    if not items:
        fail("crawl returned zero candidates across all publishers")

    reg = json.loads(REG.read_text())
    manual = manual_publishers(reg)
    browser_pubs = [p["id"] for p in reg
                    if p.get("fetch") == "browser" and p.get("verdict") in ("include", "borderline")]
    fresh = pending(items, reg)
    notes = automation_notes()

    lines = [f"# Outside reports needing review ({date.today().isoformat()})", ""]
    if failures:
        lines.append("## Crawl failures")
        lines.append("These publishers could not be crawled this run, so their new reports "
                     "(if any) are missing from the list below:\n")
        lines.extend(f"- {f}" for f in failures)
        lines.append("")
    if fresh:
        lines.append(f"{len(fresh)} candidate reports published since {FLOOR} are not yet "
                     "summarized or ruled out:\n")
        by_pub = {}
        for i in fresh:
            by_pub.setdefault(i.get("publisher_name") or i.get("publisher"), []).append(i)
        for pub, rows in sorted(by_pub.items(), key=lambda kv: -len(kv[1])):
            lines.append(f"## {pub} ({len(rows)})")
            for r in sorted(rows, key=lambda x: x["issued"], reverse=True):
                line = f"- {r['issued']} [{r['title']}]({r['url']})"
                note = notes.get(r["url"].rstrip("/"))
                if note:
                    line += f"\n  - {note}"
                lines.append(line)
            lines.append("")
    else:
        lines.append("No new outside reports awaiting review.\n")

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

    OUT.write_text("\n".join(lines) + "\n")
    print(f"\n{len(fresh)} open candidates, {len(failures)} crawl failures -> {OUT}")
    if fresh or failures:
        sys.exit(1)   # signal the scheduled job to open or update the issue


if __name__ == "__main__":
    main()
