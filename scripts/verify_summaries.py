#!/usr/bin/env python3
"""Verify that every quote and number in each summary appears in its source
text: the scraped comptroller page text (data/audits_raw.json) or, for DOI,
monitor and outside reports, the saved extraction (data/raw_extra/<slug>.txt).
Curly/straight quote and dash differences are normalized. Exits nonzero
listing any unverifiable item.

check_summary() is also imported by scripts/draft_summaries.py, so automated
drafts pass through exactly the same test before they are written."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_RAW = None


def slug_of(url):
    u = url.rstrip("/")
    m = re.search(r"/audits/(\d{4})/(\d\d)/(\d\d)/([a-z0-9-]+)$", u)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}-{m.group(4)}"
    return u.split("/")[-1]


def raw_by_slug():
    global _RAW
    if _RAW is None:
        _RAW = {slug_of(a["url"]): a
                for a in json.loads((ROOT / "data" / "audits_raw.json").read_text())}
    return _RAW


def norm(s):
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-").replace(" ", " ").replace("­", "")
    return re.sub(r"\s+", " ", s).lower()


def source_text(slug):
    raw = raw_by_slug()
    if slug in raw:
        return norm(" ".join(raw[slug]["sections"].values()))
    extra = ROOT / "data" / "raw_extra" / f"{slug}.txt"
    if extra.exists():
        return norm(extra.read_text(errors="replace"))
    return None


def despace(src):
    """PDF text extraction often splits digits ("12 0 of 2 38"), so numbers get a
    second pass against a copy with spaces inside digit runs removed."""
    return re.sub(r"(?<=\d)[ ,]?\s+(?=\d)", "", src)


def check_summary(s, src, name):
    """Return a list of failure strings for one summary against normalized src."""
    fails = []
    for i, fd in enumerate(s["findings"]):
        q = fd.get("quote", "")
        if q:
            core = norm(q).strip(". ").replace("...", "\x00")
            parts = [p.strip(" .") for p in core.split("\x00") if p.strip(" .")]
            for p in parts:
                if p not in src:
                    fails.append(f"{name}: finding {i+1} quote not verbatim: {q[:80]}")
                    break
    src_despaced = despace(src)
    for n in s.get("numbers", []):
        v = norm(n["value"])
        if v not in src and re.sub(r"\s+", "", v) not in src_despaced:
            fails.append(f"{name}: number not in source: {n['value']}")
    return fails


def main():
    fails = []
    checked = 0
    for f in sorted((ROOT / "data" / "summaries").glob("*.json")):
        s = json.loads(f.read_text())
        src = source_text(f.stem)
        if src is None:
            fails.append(f"{f.name}: no source text (not in audits_raw.json and no raw_extra txt)")
            continue
        checked += 1
        fails.extend(check_summary(s, src, f.name))

    if fails:
        print("FAIL:", len(fails), "unverifiable items")
        print("\n".join(fails))
        sys.exit(1)
    print(f"OK: all quotes and numbers verified across {checked} summaries")


if __name__ == "__main__":
    main()
