#!/usr/bin/env python3
"""Verify that every quote and number in each summary appears in its source
text: the scraped comptroller page text (data/audits_raw.json) or, for DOI
and monitor reports, the saved PDF extraction (data/raw_extra/<slug>.txt).
Curly/straight quote and dash differences are normalized. Exits nonzero
listing any unverifiable item."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def slug_of(url):
    u = url.rstrip("/")
    m = re.search(r"/audits/(\d{4})/(\d\d)/(\d\d)/([a-z0-9-]+)$", u)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}-{m.group(4)}"
    return u.split("/")[-1]


raw = {slug_of(a["url"]): a for a in json.loads((ROOT / "data" / "audits_raw.json").read_text())}


def norm(s):
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-").replace(" ", " ").replace("­", "")
    return re.sub(r"\s+", " ", s).lower()


def source_text(slug):
    if slug in raw:
        return norm(" ".join(raw[slug]["sections"].values()))
    extra = ROOT / "data" / "raw_extra" / f"{slug}.txt"
    if extra.exists():
        return norm(extra.read_text(errors="replace"))
    return None


fails = []
checked = 0
for f in sorted((ROOT / "data" / "summaries").glob("*.json")):
    s = json.loads(f.read_text())
    src = source_text(f.stem)
    if src is None:
        fails.append(f"{f.name}: no source text (not in audits_raw.json and no raw_extra txt)")
        continue
    checked += 1
    for i, fd in enumerate(s["findings"]):
        q = fd.get("quote", "")
        if q:
            core = norm(q).strip(". ").replace("...", "\x00")
            parts = [p.strip(" .") for p in core.split("\x00") if p.strip(" .")]
            for p in parts:
                if p not in src:
                    fails.append(f"{f.name}: finding {i+1} quote not verbatim: {q[:80]}")
                    break
    for n in s.get("numbers", []):
        if norm(n["value"]) not in src:
            fails.append(f"{f.name}: number not in source: {n['value']}")

if fails:
    print("FAIL:", len(fails), "unverifiable items")
    print("\n".join(fails))
    sys.exit(1)
print(f"OK: all quotes and numbers verified across {checked} summaries")
