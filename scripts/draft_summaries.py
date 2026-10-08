#!/usr/bin/env python3
"""Draft plain-language summaries of new reports with the Claude API.

Works the same backlog a person would: comptroller audits in
data/audits_raw.json that have no summary yet (--comptroller) and outside
reports on the ingest worklist (--outside). For each one it

  1. gets the source text: the scraped comptroller page text, or for outside
     reports the landing page plus the report PDF where one can be downloaded;
  2. asks Claude for a summary to data/SUMMARY_SPEC.md (plus
     SUMMARY_SPEC_OUTSIDE.md for outside reports), as structured JSON;
  3. runs mechanical checks: every quote and every listed number must be
     verbatim in the source (the same check as scripts/verify_summaries.py),
     every figure in the prose must appear in the source, field limits and
     topics follow the spec, and for city comptroller audits already in the
     comptroller's tracker the recommendation count must match;
  4. asks Claude, in a separate call, to check the draft against the source
     for unsupported statements, missing or merged recommendations,
     editorializing and unexpanded acronyms; up to two revisions are allowed;
  5. publishes only drafts that clear every check. Anything else is left for a
     person: failed drafts go to data/drafts/<slug>.json with the problems
     found, and outside reports the model would rule out (no recommendations,
     not about city government, not a report) or could not judge from the
     available text go to data/outside_triage.json as suggestions. Nothing is
     ruled out automatically.

Published drafts carry "ai_draft": {"model", "drafted", "human_reviewed": false}
so the site can label them. Set human_reviewed to true after reading one
against the source.

Needs ANTHROPIC_API_KEY. Without it the script prints a notice and exits 0
without changing anything, so scheduled jobs skip cleanly.

Usage:
  python3 scripts/draft_summaries.py --comptroller
  python3 scripts/draft_summaries.py --outside [--max-cost 3]
  python3 scripts/draft_summaries.py --outside --fetch-only DIR   # no API calls
  python3 scripts/draft_summaries.py --comptroller --only SLUG --out DIR  # test run
"""
from __future__ import annotations

import argparse
import html as htmllib
import io
import json
import os
import re
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path
from urllib.parse import urljoin, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import verify_summaries as vs  # noqa: E402
import ingest_outside as ingest  # noqa: E402
from build_site import AUDITNUM, load_rec_statuses, norm_title  # noqa: E402

DATA = ROOT / "data"
RAW = DATA / "audits_raw.json"
SUMDIR = DATA / "summaries"
RAWEXTRA = DATA / "raw_extra"
DRAFTS = DATA / "drafts"
TRIAGE = DATA / "outside_triage.json"
REG = DATA / "publishers.json"

MODEL = "claude-sonnet-5-5"
EFFORT = "medium"
MAX_TOKENS = 32000
# Dollars per million tokens for claude-sonnet-5-5 (the server-side fallback,
# claude-sonnet-5, is priced the same).
PRICE = {"input": 2.00, "output": 10.00, "cache_write": 2.50, "cache_read": 0.20}
MIN_SOURCE_CHARS = 1500       # less than this is a blurb, not a report
MAX_SOURCE_CHARS = 1_200_000  # never truncate; longer sources go to a person
MAX_REVISIONS = 2

TOPICS = ["education", "health", "housing", "homelessness", "social services",
          "small business", "environment", "public safety", "technology",
          "money and contracts", "seniors", "children and youth", "transparency",
          "transportation", "labor"]
AUDITORS = {"nyc": "New York City Comptroller", "osc": "New York State Comptroller"}
RULE_OUTS = {"no_recommendations": "No recommendations",
             "not_nyc_government": "Not NYC government",
             "not_a_report": "Not a report"}

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36",
      "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
      "Accept-Language": "en-US,en;q=0.9"}

SYSTEM = (
    "You write and check plain-language summaries of official and outside reports about "
    "New York City government for a public tracker called The audit files. You work only "
    "from the source text supplied in the user's message, which is the text of the report "
    "itself. You never add a fact, name, number or characterization that is not in that "
    "text, and you never draw on outside knowledge about the report, its authors or the "
    "agency. When the text does not settle a question, you say so rather than guess."
)


# ---------------------------------------------------------------- fetching

def http_get(url, binary=False, tries=3, timeout=60):
    """GET with retries. Raises when every attempt fails; never returns a sentinel."""
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
                return data if binary else data.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (401, 403, 404, 410):
                break   # blocked or gone; retrying will not help
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(3 * (i + 1))
    raise RuntimeError(f"GET {url} failed: {last}")


def html_to_text(h):
    h = re.sub(r"<!--.*?-->", " ", h, flags=re.S)
    h = re.sub(r"<(script|style|noscript|svg|template|iframe|form)\b[^>]*>.*?</\1>", " ",
               h, flags=re.S | re.I)
    h = re.sub(r"<(nav|footer)\b[^>]*>.*?</\1>", " ", h, flags=re.S | re.I)
    h = re.sub(r"<br\s*/?>", "\n", h, flags=re.I)
    h = re.sub(r"</(p|div|li|h[1-6]|tr|section|article|blockquote|figcaption)>", "\n", h,
               flags=re.I)
    h = re.sub(r"<li[^>]*>", "• ", h, flags=re.I)
    h = re.sub(r"<[^>]+>", " ", h)
    h = htmllib.unescape(h)
    h = re.sub(r"[ \t\r\f\v]+", " ", h)
    h = re.sub(r" *\n[ \n]*", "\n", h)
    return h.strip()


def main_html(h):
    """The page's <main> or <article> when it holds the body text, else the body."""
    for tag in ("main", "article"):
        m = re.search(rf"<{tag}\b[^>]*>(.*)</{tag}>", h, re.S | re.I)
        if m and len(html_to_text(m.group(1))) > 1500:
            return m.group(1)
    m = re.search(r"<body\b[^>]*>(.*)</body>", h, re.S | re.I)
    return m.group(1) if m else h


def anchors(h, base):
    out = []
    for href, text in re.findall(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', h, re.S | re.I):
        out.append((urljoin(base, htmllib.unescape(href.strip())),
                    re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", text))).strip()))
    return out


def same_site(url, pub):
    host = urlparse(url).netloc.lower().removeprefix("www.")
    base = urlparse(pub.get("url", "")).netloc.lower().removeprefix("www.")
    return bool(base) and (host == base or host.endswith("." + base)
                           or host.endswith("squarespace.com")
                           or host.endswith("squarespace-cdn.com"))


def pick_pdf(links, pub, title):
    """The publisher's own full-report PDF among a page's links, if any."""
    title_words = set(re.findall(r"[a-z]{4,}", title.lower()))
    best, best_score = None, 0
    seen = set()
    for url, text in links:
        if not re.search(r"\.pdf($|\?)", url, re.I) or url in seen or not same_site(url, pub):
            continue
        seen.add(url)
        t = text.lower()
        score = 1
        if re.search(r"full report|download the (report|paper)|read the report|working paper", t):
            score += 4
        elif re.search(r"report|download|paper|brief|read", t):
            score += 2
        if re.search(r"exec(utive)?[-_ ]summary", url + " " + t, re.I):
            score -= 2
        fname_words = set(re.findall(r"[a-z]{4,}", urlparse(url).path.lower()))
        score += min(3, len(fname_words & title_words))
        if score > best_score:
            best, best_score = url, score
    return best


LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"}


def pdf_text(data):
    import logging
    logging.getLogger("pypdf").setLevel(logging.ERROR)   # font-encoding chatter
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    text = "\n".join((p.extract_text() or "") for p in reader.pages).strip()
    # Typeset ligatures ("ﬁscal") would make every quote containing them fail
    # the verbatim check; spell them out in the saved text.
    for lig, plain in LIGATURES.items():
        text = text.replace(lig, plain)
    return text


def wp_post(pub, url):
    """WordPress publishers whose HTML pages are bot-blocked (Furman) still serve
    the post through the REST route the crawl already uses."""
    slug = urlparse(url).path.rstrip("/").split("/")[-1]
    rows = json.loads(http_get(f"{pub['feed_url']}?slug={slug}"))
    if not rows:
        raise RuntimeError(f"no REST post for slug {slug}")
    return rows[0]


def outside_source(item):
    """Returns (saved_text, pdf_url, notes_for_the_model)."""
    pub = item["pub"]
    notes = []
    if pub.get("fetch") == "wp-json":
        post = wp_post(pub, item["url"])
        body = post.get("content", {}).get("rendered", "")
        landing = html_to_text(body)
        links = anchors(body, item["url"])
        for ln in (post.get("acf") or {}).get("links") or []:
            link = (ln or {}).get("link") or {}
            if link.get("url"):
                links.append((link["url"], link.get("title", "")))
    else:
        page = http_get(item["url"])
        landing = html_to_text(main_html(page))
        links = anchors(page, item["url"])

    pdf_url = pick_pdf(links, pub, item["title"])
    pdf_body = ""
    if pdf_url:
        try:
            pdf_body = pdf_text(http_get(pdf_url, binary=True, timeout=120))
            if len(pdf_body) < 500:
                notes.append(f"The report PDF ({pdf_url}) has no extractable text, so only "
                             "the landing page is included.")
                pdf_body = ""
        except Exception as e:  # noqa: BLE001
            notes.append(f"The landing page links a report PDF ({pdf_url}) that could not be "
                         f"downloaded ({e}), so only the landing page text is included.")
    text = "===== SOURCE: landing page =====\n" + landing + "\n"
    if pdf_body:
        text += "\n===== SOURCE: report PDF =====\n" + pdf_body + "\n"
    return text, (pdf_url if pdf_body else ""), notes


def comptroller_source(a):
    parts = []
    for k, v in a["sections"].items():
        parts.append(v if k.startswith("_") else f"{k}\n{v}")
    return "\n\n".join(parts)


# ---------------------------------------------------------------- worklists

STOP = {"a", "an", "the", "of", "for", "to", "and", "in", "on", "at", "by", "with", "its",
        "how", "from", "into", "nyc", "nycs", "new", "york", "city", "citys", "is", "all"}


def outside_slug(it):
    words = re.findall(r"[a-z0-9]+", re.sub(r"[’']", "", it["title"].lower()))
    keep = [w for w in words if w not in STOP][:6] or words[:6]
    slug = f"{it['issued']}-{it['publisher']}-" + "-".join(keep)
    slug = slug[:80].rstrip("-")
    n = 2
    base = slug
    while (SUMDIR / f"{slug}.json").exists():
        slug = f"{base[:77]}-{n}"
        n += 1
    return slug


def load_json(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def failed_draft_urls():
    urls = set()
    if DRAFTS.exists():
        for f in DRAFTS.glob("*.json"):
            d = json.loads(f.read_text())
            urls.add(((d.get("summary") or {}).get("url") or d.get("url") or "").rstrip("/"))
    return urls


def comptroller_items(only, retry):
    out = []
    failed = failed_draft_urls()
    for a in json.loads(RAW.read_text()):
        slug = vs.slug_of(a["url"])
        if only and slug not in only:
            continue
        if not only and (SUMDIR / f"{slug}.json").exists():
            continue
        if not retry and not only and a["url"].rstrip("/") in failed:
            continue
        out.append({"kind": "comptroller", "slug": slug, "source": a["source"],
                    "auditor": AUDITORS[a["source"]], "title": a.get("title", ""),
                    "issued": a["issued"], "url": a["url"], "pdf": a.get("pdf", ""), "raw": a})
    return out


def outside_items(only, retry):
    reg = {p["id"]: p for p in json.loads(REG.read_text())}
    triaged = {t["url"].rstrip("/") for t in load_json(TRIAGE, [])}
    failed = failed_draft_urls()
    out = []
    for it in ingest.pending():
        u = it["url"].rstrip("/")
        if only and u not in only and outside_slug(it) not in only:
            continue
        if not retry and not only and (u in triaged or u in failed):
            continue
        out.append({"kind": "outside", "slug": outside_slug(it), "source": "outside",
                    "auditor": it.get("publisher_name") or it["publisher"],
                    "title": it["title"], "issued": it["issued"], "url": it["url"], "pdf": "",
                    "publisher": it["publisher"], "pub": reg.get(it["publisher"], {})})
    return out


# ---------------------------------------------------------------- schemas

def draft_schema(kind):
    decisions = (["summarize", "source_incomplete"] if kind == "comptroller" else
                 ["summarize", "no_recommendations", "not_nyc_government", "not_a_report",
                  "source_incomplete"])
    s = {"type": "string"}
    return {
        "type": "object",
        "properties": {
            "decision": {"type": "string", "enum": decisions},
            "decision_reason": s,
            "plain_title": s,
            "agency": s,
            "what_they_audited": s,
            "background": s,
            "findings": {"type": "array", "items": {
                "type": "object",
                "properties": {"plain": s, "quote": s},
                "required": ["plain", "quote"], "additionalProperties": False}},
            "numbers": {"type": "array", "items": {
                "type": "object",
                "properties": {"value": s, "label": s},
                "required": ["value", "label"], "additionalProperties": False}},
            "recommendations": {"type": "array", "items": s},
            "agency_response": s,
            "implementation_note": s,
            "topics": {"type": "array", "items": {"type": "string", "enum": TOPICS}},
        },
        "required": ["decision", "decision_reason", "plain_title", "agency",
                     "what_they_audited", "background", "findings", "numbers",
                     "recommendations", "agency_response", "implementation_note", "topics"],
        "additionalProperties": False,
    }


REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "problems": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": [
                    "unsupported", "recommendations", "findings", "neutrality",
                    "acronyms", "style"]},
                "field": {"type": "string"},
                "excerpt": {"type": "string"},
                "explanation": {"type": "string"},
                # Last, so the model decides after writing out its reasoning;
                # items it marks false are dropped.
                "confirmed": {"type": "boolean"},
            },
            "required": ["category", "field", "excerpt", "explanation", "confirmed"],
            "additionalProperties": False}},
    },
    "required": ["problems"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------- prompts

def spec_text(kind):
    text = (DATA / "SUMMARY_SPEC.md").read_text()
    if kind == "outside":
        text += "\n\n" + (DATA / "SUMMARY_SPEC_OUTSIDE.md").read_text()
    return text


def metadata_block(item):
    lines = [f"- Official title: {item['title']}",
             f"- Issued: {item['issued']}",
             f"- Published by: {item['auditor']}",
             f"- Report page: {item['url']}"]
    if item.get("pdf"):
        lines.append(f"- Report PDF: {item['pdf']}")
    return "\n".join(lines)


def decision_rules(kind):
    if kind == "comptroller":
        return (
            '- "summarize": the text contains the audit\'s findings and recommendations.\n'
            '- "source_incomplete": the text is cut off or lacks the findings or the '
            "recommendations, so a faithful summary is impossible. Explain in decision_reason.")
    return (
        '- "summarize": a report, white paper, study or substantial policy brief that makes '
        "at least one recommendation to New York City government (a city agency, the mayor "
        "or the City Council).\n"
        '- "no_recommendations": research or data reporting that makes no recommendations '
        "of its own.\n"
        '- "not_nyc_government": its recommendations are not addressed to New York City '
        "government (for example, only to the state, Congress or the private sector), or it "
        "is not substantially about New York City.\n"
        '- "not_a_report": testimony, a letter, a statement, a press release, an op-ed, a '
        "blog post, an event page or an interactive tool. A voter guide that analyzes New "
        "York City ballot or charter proposals and takes a position on each is a report, "
        "and its positions are its recommendations.\n"
        '- "source_incomplete": the text is only an abstract, a landing-page blurb or an '
        "excerpt, so you cannot tell what the report finds or recommends. Prefer this over "
        "guessing.\n"
        "Explain the decision in one sentence in decision_reason, citing what the text "
        "shows. When the decision is not \"summarize\", leave every other field empty.")


def draft_task(item, notes):
    kind = item["kind"]
    extra_notes = ("\n\nNotes from the pipeline about the source text:\n" +
                   "\n".join(f"- {n}" for n in notes)) if notes else ""
    return f"""Task: write the summary of the report in <source_document> above.

Report metadata (the pipeline fills in id, source, auditor, title, issued, url, pdf and is_followup itself; do not return them):
{metadata_block(item)}{extra_notes}

The house rules follow in <spec>. They were written for an agent that works with files, so ignore every workflow step about batches, reading or writing files and reporting back; the pipeline does those. Follow the schema field definitions, the hard rules and any layer-specific rules exactly.

<spec>
{spec_text(kind)}
</spec>

Rules that are checked mechanically after you answer:
- Every quote must be copied character for character from <source_document>: one sentence or phrase, ideally under 40 words. You may trim with "..." only at the start or end, never in the middle.
- Every numbers value must appear in <source_document> exactly as printed ("$11.8 million", "42 percent", "1,057"). Pick the figures that matter most, at most seven.
- Every figure anywhere in your prose must also appear in <source_document> exactly as printed. Do not round, convert, add up or reformat figures (never turn "1,200,000" into "1.2 million"). Write a figure out in words only where the source does.
- plain_title is at most 70 characters; each numbers label is at most 60.
- No em dashes in your own prose. Straight apostrophes and quotation marks in your own prose.
- Never comment on the source text or on your own drafting inside the summary (no notes such as "the source does not spell this out"). If the source never spells out an acronym, write the full name only if the source gives it somewhere; otherwise rephrase so the acronym is not needed.
- In your own prose write "city" and "state" in lowercase unless they are part of a proper name (New York City, the City Council, the State Comptroller).
- topics: one to three from the allowed list.
- findings: three to seven, fewer only if the report itself has fewer.

Decide first which case applies and set decision:
{decision_rules(kind)}"""


def review_task(item, summary):
    shown = {k: v for k, v in summary.items() if k != "ai_draft"}
    return f"""Task: check the draft summary below against the report in <source_document> above. This is the last check before the summary is published without a person reading it, so be strict about substance and do not invent problems.

Report metadata:
{metadata_block(item)}

<draft>
{json.dumps(shown, indent=2, ensure_ascii=False)}
</draft>

The rules the draft must follow:
<spec>
{spec_text(item["kind"])}
</spec>

<source_document> may hold several parts, each headed "===== SOURCE: ... =====" (for example the landing page and the report PDF). All of them are the report's own text, and a quote or figure from any part is fine.

Report one problem per issue, using these categories:
- unsupported (error): any statement in the draft (a fact, figure, name, date, cause or characterization) that <source_document> does not support, or that overstates, understates or changes what it says. Includes statements attributed to the wrong entity and figures paired with the wrong label.
- recommendations (error): a recommendation in the report that the draft leaves out, merges with another or splits; one the report does not make; or recommendations out of the report's order. For government audits the count must equal the report's own count.
- findings (error): a finding that is not one of the report's main findings, or a quote that is unrelated to the finding it is attached to (a quote that supports part of the finding is fine).
- neutrality (error): opinion or editorializing in the draft's own prose, or the publisher's rhetoric outside a quote.
- acronyms (error): an acronym in the draft's own prose (outside quotes) not spelled out at its first use in the draft, or spelled out differently from the source.
- style (minor): em dashes, a serial (Oxford) comma before "and" or "or" in a list of three or more, title case in plain_title, or curly apostrophes outside quotes.
Settle each possible issue in your own reasoning first, checking the source text, and list only the ones you confirm. Never list an item only to say it is fine; if you do list one and then find the draft is right, set confirmed to false. For each confirmed problem give the field (for example "findings[2].plain"), a short excerpt of the draft text at issue, and a one-sentence explanation that cites what the source says. A faithful draft gets an empty list."""


def revise_task(item, model_fields, problems):
    plist = "\n".join(f"- {p}" for p in problems)
    return f"""Task: revise the draft summary below so that it fixes every problem listed, then return the complete corrected summary. Keep everything that is not affected. Every rule from the original task still applies (verbatim quotes, figures exactly as printed in the source, the spec in <spec>).

Report metadata:
{metadata_block(item)}

<draft>
{json.dumps(model_fields, indent=2, ensure_ascii=False)}
</draft>

<problems>
{plist}
</problems>

<spec>
{spec_text(item["kind"])}
</spec>

Keep decision as "summarize" unless the problems show the source cannot support a summary, in which case set the decision that applies:
{decision_rules(item["kind"])}"""


# ---------------------------------------------------------------- API

class Declined(Exception):
    pass


class BudgetExceeded(Exception):
    pass


class Ledger:
    def __init__(self, cap):
        self.cap = cap
        self.spent = 0.0
        self.calls = 0
        self.tokens = {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0}

    def add(self, usage):
        rows = list(usage.iterations) if getattr(usage, "iterations", None) else [usage]
        cost = 0.0
        for u in rows:
            t = {"input": u.input_tokens or 0, "output": u.output_tokens or 0,
                 "cache_write": u.cache_creation_input_tokens or 0,
                 "cache_read": u.cache_read_input_tokens or 0}
            for k, v in t.items():
                self.tokens[k] += v
                cost += v * PRICE[k] / 1e6
        self.spent += cost
        self.calls += 1
        return cost


def ask(client, ledger, source_text, task, schema):
    """One structured call. The source document is the cached prefix, so the
    review and revision calls for the same report reread it at cache prices."""
    if ledger.spent >= ledger.cap:
        raise BudgetExceeded(f"spend cap ${ledger.cap:.2f} reached")
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=SYSTEM,
        output_config={"effort": EFFORT,
                       "format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": [
            {"type": "text",
             "text": f"<source_document>\n{source_text}\n</source_document>",
             "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": task},
        ]}],
    ) as stream:
        msg = stream.get_final_message()
    ledger.add(msg.usage)
    if msg.stop_reason == "refusal":
        cat = getattr(msg.stop_details, "category", None) if msg.stop_details else None
        raise Declined(f"model declined (category {cat})")
    if msg.stop_reason != "end_turn":
        raise Declined(f"response ended with stop_reason={msg.stop_reason}")
    text = next((b.text for b in msg.content if b.type == "text"), None)
    if text is None:
        raise Declined("response had no text block")
    return json.loads(text), msg.model


# ---------------------------------------------------------------- checks

def straighten(s):
    return s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')


def assemble(item, d, model):
    comp = item["kind"] == "comptroller"
    s = {
        "id": item["slug"],
        "source": item["source"],
        "auditor": item["auditor"],
        "title": item["title"],
        "plain_title": straighten(d["plain_title"]).strip(),
        "agency": straighten(d["agency"]).strip(),
        "issued": item["issued"],
        "url": item["url"],
        "pdf": item["pdf"],
        "what_they_audited": straighten(d["what_they_audited"]).strip(),
        "background": straighten(d["background"]).strip(),
        "findings": [{"plain": straighten(f["plain"]).strip(), "quote": f["quote"].strip()}
                     for f in d["findings"]],
        "numbers": [{"value": n["value"].strip(), "label": straighten(n["label"]).strip()}
                    for n in d["numbers"]],
        "recommendations": [straighten(r).strip() for r in d["recommendations"]],
        "agency_response": straighten(d["agency_response"]).strip() if comp else "",
        "implementation_note": straighten(d["implementation_note"]).strip() if comp else "",
    }
    if not comp:
        s["compliance_note"] = ""
    s["topics"] = list(dict.fromkeys(d["topics"]))
    s["is_followup"] = bool(comp and re.search(r"follow[- ]?up", item["title"], re.I))
    s["ai_draft"] = {"model": model, "drafted": date.today().isoformat(),
                     "human_reviewed": False}
    return s


# Notes to the reader about the source text or the drafting ("the source does not
# spell out ...") must never reach the published summary.
META = re.compile(r"\bsource (text|document)\b|\bthe source (does|did|doesn't|didn't|says|gives|"
                  r"provides|only)\b|\(the source\b|\bnot spelled out\b", re.I)


def prose_fields(s):
    for k in ("plain_title", "agency", "what_they_audited", "background",
              "agency_response", "implementation_note"):
        yield k, s.get(k, "")
    for i, f in enumerate(s["findings"]):
        yield f"findings[{i}].plain", f["plain"]
    for i, n in enumerate(s["numbers"]):
        yield f"numbers[{i}].label", n["label"]
    for i, r in enumerate(s["recommendations"]):
        yield f"recommendations[{i}]", r


def tracker_rec_count(item):
    """Number of recommendations the city comptroller's tracker lists, if any."""
    if item["source"] != "nyc":
        return None
    by_num, by_title = load_rec_statuses()
    raw = item["raw"]
    blob = (raw.get("pdf") or "") + " " + json.dumps(raw.get("sections", {}))[:200000]
    m = AUDITNUM.search(blob)
    rows = by_num.get(m.group(1)) if m else None
    rows = rows or by_title.get(norm_title(item["title"]))
    nums = [r["_n"] for r in rows or [] if r.get("_n")]
    return max(nums) if nums else None


def mechanical(s, src, item):
    p = []
    if not s["plain_title"] or len(s["plain_title"]) > 70:
        p.append(f"plain_title must be 1-70 characters (has {len(s['plain_title'])})")
    if not 1 <= len(s["findings"]) <= 7:
        p.append(f"findings: {len(s['findings'])} given; the spec allows at most 7. Keep the "
                 "report's main findings by merging related ones or dropping the least important")
    if not s["recommendations"] or any(not r for r in s["recommendations"]):
        p.append("recommendations: empty list or empty item")
    if not 1 <= len(s["topics"]) <= 3:
        p.append(f"topics: {len(s['topics'])} given; the spec allows 1-3")
    for i, n in enumerate(s["numbers"]):
        if len(n["label"]) > 60:
            p.append(f"numbers[{i}].label is over 60 characters")
    for field, text in prose_fields(s):
        if "—" in text:
            p.append(f"{field}: em dash in own prose")
        if META.search(text):
            p.append(f"{field}: comments on the source or the drafting process instead of "
                     "summarizing the report; rephrase without the note")
    p.extend(vs.check_summary(s, src, item["slug"]))
    nospace = vs.despace(src).replace(",", "")
    for field, text in prose_fields(s):
        for m in re.finditer(r"\d[\d,.]*", text):
            tok = m.group(0).rstrip(".,")
            if tok and tok not in src and tok.replace(",", "") not in nospace:
                p.append(f"{field}: figure {tok!r} does not appear in the source text")
    if item["kind"] == "comptroller":
        n = tracker_rec_count(item)
        if n and n != len(s["recommendations"]):
            p.append(f"recommendations: the comptroller's tracker lists {n} for this audit; "
                     f"the draft has {len(s['recommendations'])}")
    return p


def model_fields(d):
    return {k: d[k] for k in ("plain_title", "agency", "what_they_audited", "background",
                              "findings", "numbers", "recommendations", "agency_response",
                              "implementation_note", "topics")}


# ---------------------------------------------------------------- per item

def process(client, ledger, item, out, resume=False):
    """Returns (outcome, detail). Writes files under `out` (normally data/)."""
    notes = []
    if item["kind"] == "comptroller":
        source = comptroller_source(item["raw"])
        src_norm = vs.norm(" ".join(item["raw"]["sections"].values()))
    else:
        try:
            source, pdf_url, notes = outside_source(item)
        except Exception as e:  # noqa: BLE001
            return "fetch_failed", str(e)
        item["pdf"] = pdf_url
        src_norm = vs.norm(source)
    if len(source) < MIN_SOURCE_CHARS:
        return leave_triage(item, out, "source_incomplete",
                            f"only {len(source)} characters of text could be fetched")
    if len(source) > MAX_SOURCE_CHARS:
        return leave_draft(item, out, None, [f"source is {len(source)} characters, over the "
                                             f"{MAX_SOURCE_CHARS} limit; summarize by hand"],
                           source)

    schema = draft_schema(item["kind"])
    saved = load_json(out / "drafts" / f"{item['slug']}.json", None) if resume else None
    if saved and saved.get("summary"):
        # Retrying a failed draft starts from it and the problems found, rather
        # than paying for a fresh draft and review.
        d = model_fields(saved["summary"])
        d, model = ask(client, ledger, source, revise_task(item, d, saved["problems"]), schema)
    else:
        d, model = ask(client, ledger, source, draft_task(item, notes), schema)
    if d["decision"] != "summarize":
        return leave_triage(item, out, d["decision"], d["decision_reason"])

    for attempt in range(MAX_REVISIONS + 1):
        s = assemble(item, d, model)
        problems = mechanical(s, src_norm, item)
        if not problems:
            r, _ = ask(client, ledger, source, review_task(item, s), REVIEW_SCHEMA)
            # Severity follows the category, not the model's own label: only style
            # issues are minor.
            problems = [f"[{'minor' if x['category'] == 'style' else 'error'}/{x['category']}] "
                        f"{x['field']}: \"{x['excerpt']}\" {x['explanation']}"
                        for x in r["problems"] if x["confirmed"]]
        errors = [p for p in problems if not p.startswith("[minor/")]
        if not problems or (not errors and attempt == MAX_REVISIONS):
            write_summary(item, s, source, out)
            return "published", f"{len(s['findings'])} findings, " \
                                 f"{len(s['recommendations'])} recommendations" + \
                                 (f"; {len(problems)} minor notes" if problems else "")
        if attempt == MAX_REVISIONS:
            return leave_draft(item, out, s, problems, source)
        d, model = ask(client, ledger, source, revise_task(item, model_fields(d), problems),
                       schema)
        if d["decision"] != "summarize":
            return leave_triage(item, out, d["decision"], d["decision_reason"])
    raise AssertionError("unreachable")


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def write_summary(item, s, source, out):
    write_json(out / "summaries" / f"{item['slug']}.json", s)
    if item["kind"] == "outside":
        (out / "raw_extra").mkdir(parents=True, exist_ok=True)
        (out / "raw_extra" / f"{item['slug']}.txt").write_text(source)
    for ext in ("json", "txt"):   # a passing retry clears the earlier failed draft
        stale = out / "drafts" / f"{item['slug']}.{ext}"
        if stale.exists():
            stale.unlink()


def leave_draft(item, out, s, problems, source):
    write_json(out / "drafts" / f"{item['slug']}.json",
               {"slug": item["slug"], "url": item["url"], "title": item["title"],
                "problems": problems, "summary": s})
    if item["kind"] == "outside" and source:
        (out / "drafts" / f"{item['slug']}.txt").write_text(source)
    return "left_for_person", f"{len(problems)} problems; see drafts/{item['slug']}.json"


def leave_triage(item, out, decision, reason):
    if item["kind"] == "comptroller":
        return leave_draft(item, out, None, [f"{decision}: {reason}"], "")
    path = out / "outside_triage.json"
    rows = [t for t in load_json(path, []) if t["url"].rstrip("/") != item["url"].rstrip("/")]
    rows.append({"title": item["title"], "url": item["url"], "publisher": item["publisher"],
                 "issued": item["issued"], "decision": decision, "reason": reason,
                 "model": MODEL, "date": date.today().isoformat()})
    write_json(path, rows)
    return f"triage:{decision}", reason


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--comptroller", action="store_true", help="new comptroller audits")
    ap.add_argument("--outside", action="store_true", help="outside reports on the worklist")
    ap.add_argument("--only", nargs="*", default=[], help="slugs or URLs to limit the run to")
    ap.add_argument("--retry-failed", action="store_true",
                    help="retry items already in data/drafts (resuming from the saved draft) "
                         "or data/outside_triage.json")
    ap.add_argument("--max-cost", type=float, default=3.0,
                    help="stop starting new items once estimated spend reaches this (dollars)")
    ap.add_argument("--out", default=str(DATA),
                    help="where to write summaries, raw_extra, drafts and triage (default data/)")
    ap.add_argument("--fetch-only", metavar="DIR",
                    help="fetch outside source texts into DIR and stop; no API calls")
    args = ap.parse_args()
    if not (args.comptroller or args.outside):
        ap.error("choose --comptroller and/or --outside")

    only = {o.rstrip("/") for o in args.only}
    items = []
    if args.comptroller:
        items += comptroller_items(only, args.retry_failed)
    if args.outside:
        items += outside_items(only, args.retry_failed)
    print(f"{len(items)} items to draft")

    if args.fetch_only:
        d = Path(args.fetch_only)
        d.mkdir(parents=True, exist_ok=True)
        for it in items:
            if it["kind"] != "outside":
                continue
            try:
                text, pdf, notes = outside_source(it)
                (d / f"{it['slug']}.txt").write_text(text)
                print(f"  {it['slug']}: {len(text)} chars, pdf={pdf or '-'} {notes}")
            except Exception as e:  # noqa: BLE001
                print(f"  {it['slug']}: FETCH FAILED {e}")
        return

    if not items:
        return
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set; skipping automated drafts. "
              "These items stay on the worklist for a person.")
        return

    import anthropic
    client = anthropic.Anthropic()
    ledger = Ledger(args.max_cost)
    out = Path(args.out)
    results = []
    for it in items:
        start = ledger.spent
        try:
            outcome, detail = process(client, ledger, it, out, resume=args.retry_failed)
        except BudgetExceeded as e:
            results.append((it, "not_started", str(e), 0.0))
            continue
        except Declined as e:
            outcome, detail = leave_draft(it, out, None, [str(e)], "")[0], str(e)
        except anthropic.AuthenticationError as e:
            sys.exit(f"FAIL: the API key was rejected ({e}); fix the ANTHROPIC_API_KEY secret")
        except anthropic.APIStatusError as e:
            outcome, detail = "api_error", f"{e.status_code} {e.message}"
        except anthropic.APIConnectionError as e:
            outcome, detail = "api_error", f"connection: {e}"
        results.append((it, outcome, detail, ledger.spent - start))
        print(f"  {it['slug']}: {outcome} ({detail}) ${ledger.spent - start:.3f}", flush=True)

    t = ledger.tokens
    print(f"\n{ledger.calls} API calls, est. ${ledger.spent:.2f} "
          f"(input {t['input']:,}, cache write {t['cache_write']:,}, "
          f"cache read {t['cache_read']:,}, output {t['output']:,} tokens)")
    published = sum(1 for r in results if r[1] == "published")
    print(f"{published} published, {len(results) - published} left for a person")
    api_errors = [r for r in results if r[1] in ("api_error", "fetch_failed")]

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a") as fh:
            fh.write("### Automated summary drafts\n\n| Report | Outcome | Detail |\n|---|---|---|\n")
            for it, outcome, detail, _ in results:
                fh.write(f"| {it['title'][:80]} | {outcome} | {detail[:200]} |\n")
            fh.write(f"\nEstimated API spend: ${ledger.spent:.2f}\n")
    if api_errors:
        sys.exit(f"FAIL: {len(api_errors)} items hit API or fetch errors; they stay on the "
                 "worklist")


if __name__ == "__main__":
    main()
