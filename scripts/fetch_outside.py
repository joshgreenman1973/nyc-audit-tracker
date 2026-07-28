#!/usr/bin/env python3
"""Discovery crawl for outside-government publishers: think tanks, research
centers and civic watchdogs that publish papers, reports and testimony making
recommendations to New York City government.

Reads data/publishers.json (merged registry), fetches each publisher's listing
by its declared method, applies the inclusion bar and writes candidate items to
data/outside_index.json. Fetching the full text of each item is a separate
step (fetch_outside_text.py) so volume can be reviewed first.

Fails loud: a publisher that yields zero items is reported as a failure rather
than silently skipped.
"""
import html as htmllib
import json
import re
import sys
import time
import urllib.request
from datetime import date, datetime
from pathlib import Path

CUTOFF = date(2025, 1, 1)
ROOT = Path(__file__).resolve().parent.parent
REG = ROOT / "data" / "publishers.json"
OUT = ROOT / "data" / "outside_index.json"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}

# The bar: white papers, reports, studies and substantial policy briefs.
# Testimony, letters, memos, commentary, op-eds, press statements, events,
# newsletters and dashboards do not qualify.
EXCLUDE_TITLE = re.compile(
    r"\b(op-?ed|opinion|newsletter|press release|statement on|event|webinar|"
    r"podcast|video|announc\w+|in the news|media advisory|obituary|"
    r"job posting|we're hiring|save the date|"
    r"testimony|testifies|public comment|comments? on the proposed|"
    r"letter to|joint letter|memo of (support|opposition)|bill memo|"
    r"calls on|urges|responds? to)\b", re.I)


def get(url, tries=3, timeout=45):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(3 * (i + 1))


def strip_tags(s):
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", htmllib.unescape(s)).strip()


def qualifies(title):
    return bool(title) and not EXCLUDE_TITLE.search(title)


# ---------------- adapters ----------------

def from_rss(pub):
    """RSS/Atom feed (Squarespace, WordPress, generic)."""
    xml = get(pub["feed_url"])
    items = []
    for m in re.finditer(r"<item>(.*?)</item>", xml, re.S):
        block = m.group(1)
        title = strip_tags(re.search(r"<title>(.*?)</title>", block, re.S).group(1)) if re.search(r"<title>(.*?)</title>", block, re.S) else ""
        link = re.search(r"<link>(.*?)</link>", block, re.S)
        pub_date = re.search(r"<pubDate>(.*?)</pubDate>", block, re.S)
        d = parse_rss_date(strip_tags(pub_date.group(1))) if pub_date else None
        items.append({"title": title, "url": strip_tags(link.group(1)) if link else "", "issued": d})
    return items


RSS_FMTS = ["%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S"]


def parse_rss_date(s):
    s = s.strip()
    for f in RSS_FMTS:
        try:
            return datetime.strptime(s, f).date().isoformat()
        except ValueError:
            continue
    m = re.search(r"(\d{4})-(\d\d)-(\d\d)", s)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def from_wpjson(pub):
    """WordPress REST API, paged until before the cutoff."""
    items = []
    for page in range(1, 12):
        url = f"{pub['feed_url']}?per_page=100&page={page}&_fields=title,link,date"
        try:
            rows = json.loads(get(url))
        except Exception:
            break
        if not rows:
            break
        for r in rows:
            title = strip_tags(r.get("title", {}).get("rendered", ""))
            d = (r.get("date") or "")[:10]
            items.append({"title": title, "url": r.get("link", ""), "issued": d or None})
        if any((r.get("date") or "")[:10] < CUTOFF.isoformat() for r in rows):
            break
        time.sleep(0.5)
    return items


def from_ghost(pub):
    """Vital City runs Ghost; the Content API needs the site's public key."""
    key = pub.get("ghost_key")
    if not key:
        return []
    items = []
    for page in range(1, 12):
        url = (f"{pub['feed_url']}?key={key}&limit=100&page={page}"
               "&fields=title,url,published_at&order=published_at%20desc")
        data = json.loads(get(url))
        posts = data.get("posts", [])
        if not posts:
            break
        for p in posts:
            items.append({"title": p.get("title", ""), "url": p.get("url", ""),
                          "issued": (p.get("published_at") or "")[:10] or None})
        if any((p.get("published_at") or "")[:10] < CUTOFF.isoformat() for p in posts):
            break
        time.sleep(0.5)
    return items


def from_html(pub):
    """Generic listing crawl driven by per-publisher patterns in the registry."""
    items = []
    pages = pub.get("page_urls") or [pub["listing_url"]]
    item_pat = re.compile(pub["item_pattern"], re.S) if pub.get("item_pattern") else None
    if not item_pat:
        raise RuntimeError(f"{pub['id']}: html adapter needs an item_pattern in the registry")
    for url in pages:
        html = get(url)
        for m in item_pat.finditer(html):
            g = m.groupdict()
            link = g.get("url", "")
            if link.startswith("/"):
                link = pub["url"].rstrip("/") + link
            items.append({"title": strip_tags(g.get("title", "")),
                          "url": link,
                          "issued": normalize_date(g.get("date", "")),
                          "kind": strip_tags(g.get("kind", "")) if g.get("kind") else ""})
        time.sleep(1)
    return items


MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def normalize_date(s):
    s = strip_tags(s or "")
    m = re.search(r"(\d{4})-(\d\d)-(\d\d)", s)
    if m:
        return m.group(0)
    m = re.search(r"([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})", s)
    if m and m.group(1)[:3].lower() in MONTHS:
        return f"{m.group(3)}-{MONTHS[m.group(1)[:3].lower()]:02d}-{int(m.group(2)):02d}"
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3,9})\.?\s+(\d{4})", s)
    if m and m.group(2)[:3].lower() in MONTHS:
        return f"{m.group(3)}-{MONTHS[m.group(2)[:3].lower()]:02d}-{int(m.group(1)):02d}"
    m = re.search(r"([A-Za-z]{3,9})\.?\s+(\d{4})", s)
    if m and m.group(1)[:3].lower() in MONTHS:
        return f"{m.group(2)}-{MONTHS[m.group(1)[:3].lower()]:02d}-01"
    return None


ADAPTERS = {"rss": from_rss, "wp-json": from_wpjson, "ghost": from_ghost, "html": from_html}


def main():
    if not REG.exists():
        sys.exit(f"FAIL: no registry at {REG}. Merge the publisher research first.")
    pubs = [p for p in json.loads(REG.read_text()) if p.get("verdict") in ("include", "borderline")]
    if not pubs:
        sys.exit("FAIL: registry has no publishers marked include")

    out, failures, skipped = [], [], []
    for pub in pubs:
        method = pub.get("fetch")
        if method == "browser":
            # Cloudflare-blocked; handled by the browser-driven collector.
            skipped.append(f"{pub['id']} (browser fetch required)")
            continue
        fn = ADAPTERS.get(method)
        if not fn:
            failures.append(f"{pub['id']}: unknown fetch method {method!r}")
            continue
        try:
            items = fn(pub)
        except Exception as e:
            failures.append(f"{pub['id']}: {type(e).__name__} {e}")
            continue
        kept = []
        for it in items:
            if not it.get("issued") or it["issued"] < CUTOFF.isoformat():
                continue
            if not qualifies(it["title"]):
                continue
            if pub.get("include_types") and it.get("kind") and it["kind"] not in pub["include_types"]:
                continue
            it["publisher"] = pub["id"]
            it["publisher_name"] = pub["name"]
            kept.append(it)
        if not kept:
            failures.append(f"{pub['id']}: zero qualifying items since {CUTOFF}")
        print(f"{pub['id']:16s} {len(kept):4d} candidates  ({len(items)} raw)")
        out.extend(kept)

    seen, deduped = set(), []
    for it in sorted(out, key=lambda x: x["issued"], reverse=True):
        if it["url"] in seen:
            continue
        seen.add(it["url"])
        deduped.append(it)

    OUT.write_text(json.dumps(deduped, indent=1, ensure_ascii=False))
    print(f"\nWrote {len(deduped)} candidate items -> {OUT}")
    if skipped:
        print("Needs browser collector: " + ", ".join(skipped))
    if failures:
        print("\nFAILURES:")
        for f in failures:
            print("  " + f)
        sys.exit(1)


if __name__ == "__main__":
    main()
