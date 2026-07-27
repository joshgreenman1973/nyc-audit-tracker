#!/usr/bin/env python3
"""Fetch NYC Comptroller and NYS Comptroller (OSC) audits of New York City
agencies issued on or after CUTOFF, with full detail-page text for each.

Fails loud: exits nonzero if either source returns zero audits or any
detail page yields no extractable text.

Outputs data/audits_raw.json:
  [{source, title, url, agency, issued, pdf, sections: {heading: text}}]
"""
import html as htmllib
import json
import re
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

CUTOFF = date(2026, 1, 1)
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "audits_raw.json"
UA = {"User-Agent": "Mozilla/5.0 (audit-tracker; contact josh.greenman@gmail.com)"}


def get(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:
            if i == tries - 1:
                raise
            time.sleep(3 * (i + 1))
    raise RuntimeError(f"unreachable: {url}")


def strip_tags(s):
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"</(p|div|li|h[1-6]|tr)>", "\n", s)
    s = re.sub(r"<li[^>]*>", "• ", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = htmllib.unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n\n", s)
    return s.strip()


# ---------------- NYC Comptroller ----------------

def nyc_listing():
    """Walk the FacetWP-filtered listing until dates fall before CUTOFF."""
    audits = []
    for page in range(1, 8):
        html = get(f"https://comptroller.nyc.gov/reports/?_type=audit&_paged={page}")
        m = re.search(r"facetwp-template.*", html, re.S)
        if not m:
            sys.exit(f"FAIL: NYC listing page {page} has no facetwp-template block")
        sec = m.group(0)
        cards = re.findall(
            r'href="(https://comptroller\.nyc\.gov/reports/[^"]+)"[^>]*>.{0,2000}?(\w{3} \d{1,2}, \d{4})',
            sec, re.S)
        if not cards:
            break
        done = False
        for url, dstr in cards:
            d = parse_us_date(dstr)
            if d < CUTOFF:
                done = True
                break
            if not any(a["url"] == url for a in audits):
                audits.append({"source": "nyc", "url": url, "issued": d.isoformat()})
        if done:
            break
        time.sleep(1)
    return audits


MONTHS = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}


def parse_us_date(s):
    mo, day, yr = re.match(r"(\w{3}) (\d{1,2}), (\d{4})", s).groups()
    return date(int(yr), MONTHS[mo], int(day))


def nyc_detail(a):
    html = get(a["url"])
    t = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    a["title"] = strip_tags(t.group(1)) if t else ""
    pdf = re.search(r'href="(https://comptroller\.nyc\.gov/[^"]+\.pdf)"', html)
    a["pdf"] = pdf.group(1) if pdf else ""
    ag = re.findall(r'/reports/\?(?:fwp_|_)agency=[^"]*"[^>]*>([^<]+)<', html)
    a["agency"] = "; ".join(dict.fromkeys(strip_tags(x) for x in ag)) if ag else ""
    body = re.search(r'<div[^>]*class="[^"]*(?:entry-content|report-content|the-content)[^"]*"[^>]*>(.*?)<(?:footer|aside)', html, re.S)
    raw = body.group(1) if body else html
    a["sections"] = split_sections(raw)
    return a


# ---------------- NYS Comptroller (OSC) ----------------

NYC_AGENCY_PAT = re.compile(
    r"New York City|NYC |NYPD|"
    r"Health \+ Hospitals|Health and Hospitals|"
    r"School Construction Authority|"
    r"(?<!State )Housing Authority",
    re.I)


def osc_listing():
    rows = []
    pages = ["https://www.osc.ny.gov/state-agencies/audits/new-releases"]
    pages += [f"https://www.osc.ny.gov/state-agencies/audits/by-date-older?page={p}" for p in range(0, 6)]
    stop = False
    for url in pages:
        if stop:
            break
        html = get(url)
        entries = re.findall(
            r'<a href="(/state-agencies/audits/\d{4}/\d\d/\d\d/[^"]+)"[^>]*>(.*?)</a>\s*<br\s*/?>\s*(.*?)\s*Issued:\s*(\d\d/\d\d/\d\d)',
            html, re.S)
        if not entries and "new-releases" in url:
            sys.exit("FAIL: OSC new-releases page had no audit entries")
        for path, title, agency, dstr in entries:
            mm, dd, yy = dstr.split("/")
            d = date(2000 + int(yy), int(mm), int(dd))
            if d < CUTOFF:
                stop = True
                continue
            agency = strip_tags(agency).replace("\n", " ").strip()
            agency = re.sub(r"\s+", " ", agency)
            rows.append({
                "source": "osc",
                "url": "https://www.osc.ny.gov" + path,
                "title": strip_tags(title),
                "agency": agency,
                "issued": d.isoformat(),
            })
        time.sleep(1)
    # de-dupe (new-releases overlaps by-date-older)
    seen, out = set(), []
    for r in rows:
        if r["url"] not in seen:
            seen.add(r["url"])
            out.append(r)
    out = [r for r in out if NYC_AGENCY_PAT.search(r["agency"]) or NYC_AGENCY_PAT.search(r["title"])]
    # Audits of programs explicitly outside the city are out of scope even
    # when the title mentions New York City.
    return [r for r in out if "outside new york city" not in r["title"].lower()]


def osc_detail(a):
    html = get(a["url"])
    pdf = re.search(r'href="(/files/[^"]+\.pdf|https://www\.osc\.ny\.gov/files/[^"]+\.pdf)"', html)
    a["pdf"] = ("https://www.osc.ny.gov" + pdf.group(1)) if pdf and pdf.group(1).startswith("/") else (pdf.group(1) if pdf else "")
    body = re.search(r'<div[^>]*class="[^"]*(?:field--name-body|node__content|main-content)[^"]*"[^>]*>(.*?)(?:<footer|<div class="region region-footer)', html, re.S)
    raw = body.group(1) if body else html
    a["sections"] = split_sections(raw)
    # OSC pages end with a press-contact block headed by a staff name; drop it.
    for k in list(a["sections"]):
        if re.search(r"Division of|@osc\.ny\.gov|Press Office", a["sections"][k]) and len(a["sections"][k]) < 600:
            del a["sections"][k]
    return a


# ---------------- shared ----------------

def split_sections(raw_html):
    """Split article HTML into {heading: text} by h2/h3/h4/strong-para headings."""
    parts = re.split(r"<h([234])[^>]*>(.*?)</h\1>", raw_html, flags=re.S)
    sections = {}
    if len(parts) > 1:
        intro = strip_tags(parts[0])
        if intro:
            sections["_intro"] = intro
        junk = re.compile(r"Investor Relations|Mailing List|Related Reports|Stay Connected|Share This|Contact the|Sign [Uu]p", re.I)
        for i in range(1, len(parts), 3):
            heading = strip_tags(parts[i + 1])[:120]
            if junk.search(heading):
                break
            text = strip_tags(parts[i + 2])
            if heading and text:
                sections[heading] = sections.get(heading, "") + ("\n\n" if heading in sections else "") + text
    else:
        sections["_body"] = strip_tags(raw_html)
    return sections


def main():
    nyc = nyc_listing()
    if not nyc:
        sys.exit("FAIL: zero NYC Comptroller audits found since cutoff")
    print(f"NYC listing: {len(nyc)} audits since {CUTOFF}")
    for a in nyc:
        nyc_detail(a)
        print("  ", a["issued"], a["title"][:80])
        time.sleep(1)

    osc = osc_listing()
    if not osc:
        sys.exit("FAIL: zero OSC NYC-related audits found since cutoff")
    print(f"OSC listing: {len(osc)} NYC-related audits since {CUTOFF}")
    for a in osc:
        osc_detail(a)
        print("  ", a["issued"], a["title"][:80])
        time.sleep(1)

    allaud = nyc + osc
    empties = [a["url"] for a in allaud if not any(v.strip() for v in a["sections"].values())]
    if empties:
        sys.exit(f"FAIL: {len(empties)} audits had no extractable text: {empties[:3]}")

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(allaud, indent=1, ensure_ascii=False))
    print(f"Wrote {len(allaud)} audits -> {OUT}")


if __name__ == "__main__":
    main()
