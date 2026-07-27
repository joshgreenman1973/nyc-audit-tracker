#!/usr/bin/env python3
"""Fetch per-recommendation implementation statuses from the NYC Comptroller's
official Audit Recommendations Tracker (a public Power BI report embedded at
comptroller.nyc.gov/services/for-the-public/audit/audit-recommendations-tracker).

Queries the Power BI public API and decodes the DSR response into
data/nyc_rec_status.json:
  [{title, audit_num, agency, issued, recommendation, response,
    response_status, status_date}]

Fails loud on empty or malformed responses.
"""
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "nyc_rec_status.json"

KEY = "4546776d-3619-4744-bd0f-57e6814c4e66"
BASE = "https://wabi-us-gov-iowa-api.analysis.usgovcloudapi.net"
MODEL_ID = 525533
DATASET = "ce8abe5a-5d15-444f-8868-9205c2d4e578"
COLS = ["Title", "AuditNum", "AgencyDescription", "FinalRptIssueDate",
        "Recommendation", "Response", "ResponseStatus", "StatusDate"]
NAMES = ["title", "audit_num", "agency", "issued_ms", "recommendation",
         "response", "response_status", "status_date_ms"]


def query():
    sel = [{"Column": {"Expression": {"SourceRef": {"Source": "r"}}, "Property": c},
            "Name": f"Recommendations.{c}"} for c in COLS]
    body = {
        "version": "1.0.0",
        "queries": [{"Query": {"Commands": [{"SemanticQueryDataShapeCommand": {
            "Query": {"Version": 2,
                      "From": [{"Name": "r", "Entity": "Recommendations", "Type": 0}],
                      "Select": sel},
            "Binding": {"Primary": {"Groupings": [{"Projections": list(range(len(COLS)))}]},
                        "DataReduction": {"DataVolume": 6, "Primary": {"Window": {"Count": 30000}}},
                        "Version": 1},
            "ExecutionMetricsKind": 1}}]},
            "CacheKey": "", "QueryId": "",
            "ApplicationContext": {"DatasetId": DATASET}}],
        "cancelQueries": [], "modelId": MODEL_ID,
    }
    req = urllib.request.Request(
        f"{BASE}/public/reports/querydata?synchronous=true",
        data=json.dumps(body).encode(),
        headers={"X-PowerBI-ResourceKey": KEY, "Content-Type": "application/json",
                 "User-Agent": "Mozilla/5.0 (audit-tracker)"})
    return json.loads(urllib.request.urlopen(req, timeout=120).read())


def decode(d):
    dsr = d["results"][0]["result"]["data"]["dsr"]
    if "DS" not in dsr:
        sys.exit(f"FAIL: Power BI returned an error: {json.dumps(dsr)[:400]}")
    DS = dsr["DS"][0]
    rows = DS["PH"][0]["DM0"]
    schema = [(s.get("T"), s.get("DN")) for s in rows[0]["S"]]
    dicts = DS.get("ValueDicts", {})
    ncol = len(schema)
    out, prev = [], [None] * ncol
    for r in rows:
        C, Rbits, ci, vals = r.get("C", []), r.get("R", 0), 0, []
        for i in range(ncol):
            if Rbits & (1 << i):
                vals.append(prev[i])
            else:
                vals.append(C[ci]); ci += 1
        prev = vals[:]
        rec = {}
        for i, (name, (T, DN)) in enumerate(zip(NAMES, schema)):
            v = vals[i]
            if DN and isinstance(v, int):
                v = dicts[DN][v]
            if name.endswith("_ms") and isinstance(v, (int, float)):
                v = datetime.fromtimestamp(v / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
            rec[name.replace("_ms", "")] = v
        out.append(rec)
    return out


def main():
    rows = decode(query())
    if len(rows) < 500:
        sys.exit(f"FAIL: only {len(rows)} tracker rows returned; expected 1,000+")
    statuses = {r["response_status"] for r in rows}
    if "Implemented" not in statuses:
        sys.exit(f"FAIL: unexpected status values: {statuses}")
    OUT.write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    print(f"Wrote {len(rows)} recommendation statuses ({len({r['audit_num'] for r in rows})} audits) -> {OUT}")


if __name__ == "__main__":
    main()
