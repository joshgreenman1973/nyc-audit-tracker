#!/usr/bin/env python3
"""Merge data/summaries/*.json into docs/audits.json.

- Fails loud if any comptroller audit in data/audits_raw.json lacks a summary.
- Joins NYC Comptroller recommendation implementation statuses
  (data/nyc_rec_status.json, from the comptroller's official tracker)
  by audit number, with normalized-title fallback.
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "audits_raw.json"
SUMDIR = ROOT / "data" / "summaries"
RECSTATUS = ROOT / "data" / "nyc_rec_status.json"
OUT = ROOT / "docs" / "audits.json"

REQUIRED = ["id", "source", "auditor", "title", "plain_title", "agency", "issued",
            "url", "pdf", "what_they_audited", "background", "findings",
            "numbers", "recommendations", "agency_response", "topics", "is_followup"]

AUDITNUM = re.compile(r"([A-Z]{2}\d{2}-\d{3}[A-Z]{0,2})")


def slug_of(url):
    u = url.rstrip("/")
    m = re.search(r"/audits/(\d{4})/(\d\d)/(\d\d)/([a-z0-9-]+)$", u)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}-{m.group(4)}"
    return u.split("/")[-1]


def norm_title(t):
    t = t.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    t = re.sub(r"[^a-z0-9 ]", " ", t.lower().replace("–", "-").replace("—", "-"))
    return re.sub(r"\s+", " ", t).strip()


def load_rec_statuses():
    """Group official tracker rows by audit_num and by normalized title."""
    if not RECSTATUS.exists():
        return {}, {}
    rows = json.loads(RECSTATUS.read_text())
    by_num, by_title = {}, {}
    for r in rows:
        n = re.match(r"Recommendation\s+(\d+)", r["recommendation"] or "")
        r["_n"] = int(n.group(1)) if n else None
        by_num.setdefault(r["audit_num"], []).append(r)
        by_title.setdefault(norm_title(r["title"]), []).append(r)
    return by_num, by_title


def attach_status(summary, raw_entry, by_num, by_title):
    """Attach official implementation statuses to a NYC comptroller summary."""
    rows = None
    if raw_entry:
        blob = (raw_entry.get("pdf") or "") + " " + json.dumps(raw_entry.get("sections", {}))[:200000]
        m = AUDITNUM.search(blob)
        if m and m.group(1) in by_num:
            rows = by_num[m.group(1)]
    if rows is None:
        rows = by_title.get(norm_title(summary["title"]))
    if not rows:
        return
    statuses = []
    for r in sorted(rows, key=lambda x: (x["_n"] is None, x["_n"] or 0)):
        statuses.append({
            "n": r["_n"],
            "status": r["response_status"],
            "status_date": r.get("status_date") or "",
            "agency_response": r.get("response") or "",
        })
    summary["rec_statuses"] = statuses
    tally = {}
    for s in statuses:
        tally[s["status"]] = tally.get(s["status"], 0) + 1
    summary["status_tally"] = tally
    dates = [s["status_date"] for s in statuses if s["status_date"]]
    summary["status_as_of"] = max(dates) if dates else ""


# Some watchdogs number their items ("Obligation 16b, parent notifications: ...").
# The report card keeps that wording; the recommendations list leads with the idea.
PREFIX = re.compile(r"^\s*(?:Obligation|Recommendation|Provision|Item)\s*\d+[a-z]?\s*(?:,\s*[^:]{1,70})?:\s*", re.I)
CROSSREF = re.compile(r"^\s*(?:see|same as)\s+obligation\s+\d+[a-z]?\s*,?\s*(?:and\s+)?", re.I)
# Items that record the absence of a recommendation are not reform ideas.
PLACEHOLDER = re.compile(
    r"^\s*(?:the report makes no(?: new)? formal recommendations|"
    r"no (?:separate )?recommendation stated|"
    r"(?:see|same as) obligation \d+[a-z]?\.?\s*$)", re.I)


def display_recs(summary):
    """Idea-first recommendation text, with non-recommendations dropped."""
    out = []
    for i, r in enumerate(summary["recommendations"], 1):
        body = PREFIX.sub("", r).strip()
        if PLACEHOLDER.match(body) or "to be determined" in body.lower():
            continue
        body = CROSSREF.sub("", body).strip()
        if not body or PLACEHOLDER.match(body):
            continue
        body = body[0].upper() + body[1:]
        out.append({"n": i, "text": body})
    return out


def main():
    raw = json.loads(RAW.read_text())
    raw_by_slug = {slug_of(a["url"]): a for a in raw}
    missing = [s for s in raw_by_slug if not (SUMDIR / f"{s}.json").exists()]
    if missing:
        sys.exit("FAIL: audits scraped but not yet summarized: " + ", ".join(sorted(missing)))

    by_num, by_title = load_rec_statuses()
    audits = []
    for f in sorted(SUMDIR.glob("*.json")):
        s = json.loads(f.read_text())
        gaps = [k for k in REQUIRED if k not in s]
        if gaps:
            sys.exit(f"FAIL: {f.name} missing keys: {gaps}")
        if not s["findings"] or not s["recommendations"]:
            sys.exit(f"FAIL: {f.name} has empty findings or recommendations")
        s.setdefault("implementation_note", "")
        s.setdefault("compliance_note", "")
        if s["source"] == "nyc":
            attach_status(s, raw_by_slug.get(f.stem), by_num, by_title)
        s["rec_display"] = display_recs(s)
        audits.append(s)

    audits.sort(key=lambda a: a["issued"], reverse=True)
    n_status = sum(1 for a in audits if a.get("rec_statuses"))
    payload = {
        "generated": date.today().isoformat(),
        "cutoff": "2025-01-01",
        "audits": audits,
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=1, ensure_ascii=False))
    n_f = sum(len(a["findings"]) for a in audits)
    n_r = sum(len(a["rec_display"]) for a in audits)
    dropped = sum(len(a["recommendations"]) - len(a["rec_display"]) for a in audits)
    print(f"Wrote {len(audits)} reports, {n_f} findings, {n_r} recommendations "
          f"({dropped} placeholder items excluded), "
          f"{n_status} with official implementation statuses -> {OUT}")


if __name__ == "__main__":
    main()
