#!/usr/bin/env python3
"""Merge data/summaries/*.json into docs/audits.json for the site.

Fails loud: every audit in data/audits_raw.json must have a summary file,
and every summary must pass basic completeness checks.
"""
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "audits_raw.json"
SUMDIR = ROOT / "data" / "summaries"
OUT = ROOT / "docs" / "audits.json"

REQUIRED = ["id", "source", "auditor", "title", "plain_title", "agency", "issued",
            "url", "pdf", "what_they_audited", "background", "findings",
            "numbers", "recommendations", "agency_response", "topics", "is_followup"]


def slug_of(url):
    return url.rstrip("/").split("/")[-1]


def main():
    raw = json.loads(RAW.read_text())
    missing = [slug_of(a["url"]) for a in raw
               if not (SUMDIR / f"{slug_of(a['url'])}.json").exists()]
    if missing:
        sys.exit("FAIL: audits scraped but not yet summarized: " + ", ".join(missing))

    audits = []
    for f in sorted(SUMDIR.glob("*.json")):
        s = json.loads(f.read_text())
        gaps = [k for k in REQUIRED if k not in s]
        if gaps:
            sys.exit(f"FAIL: {f.name} missing keys: {gaps}")
        if not s["findings"] or not s["recommendations"]:
            sys.exit(f"FAIL: {f.name} has empty findings or recommendations")
        audits.append(s)

    audits.sort(key=lambda a: a["issued"], reverse=True)
    payload = {
        "generated": date.today().isoformat(),
        "cutoff": "2026-01-01",
        "audits": audits,
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=1, ensure_ascii=False))
    n_f = sum(len(a["findings"]) for a in audits)
    n_r = sum(len(a["recommendations"]) for a in audits)
    print(f"Wrote {len(audits)} audits, {n_f} findings, {n_r} recommendations -> {OUT}")


if __name__ == "__main__":
    main()
