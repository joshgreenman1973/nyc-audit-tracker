#!/usr/bin/env python3
"""Verify that every quote and number in each summary appears in the scraped
source text of its audit. Curly/straight quote and dash differences are
normalized before matching. Exits nonzero listing any unverifiable item."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
raw = {a["url"].rstrip("/").split("/")[-1]: a for a in json.loads((ROOT / "data" / "audits_raw.json").read_text())}


def norm(s):
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-").replace(" ", " ")
    return re.sub(r"\s+", " ", s).lower()


fails = []
for f in sorted((ROOT / "data" / "summaries").glob("*.json")):
    s = json.loads(f.read_text())
    slug = s["url"].rstrip("/").split("/")[-1]
    if slug not in raw:
        fails.append(f"{f.name}: url slug {slug} not in audits_raw.json")
        continue
    src = norm(" ".join(raw[slug]["sections"].values()))
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
print(f"OK: all quotes and numbers verified across {len(list((ROOT / 'data' / 'summaries').glob('*.json')))} summaries")
