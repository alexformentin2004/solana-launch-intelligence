"""Read-only diagnostics for coverage of early-launch price histories.

Run locally with Supabase credentials; no orders, writes, or external packages.
"""
import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from urllib.parse import quote
from collector import request_json

def seconds(a, b):
    return (datetime.fromisoformat(str(a).replace("Z", "+00:00")) -
            datetime.fromisoformat(str(b).replace("Z", "+00:00"))).total_seconds()

def classify(launch, samples):
    created = launch.get("created_at")
    valid = sorted((s for s in samples if s.get("price_usd") is not None
                    and float(s["price_usd"]) > 0), key=lambda x: x["observed_at"])
    if not created:
        return "unknown_creation"
    entry = next((i for i, s in enumerate(valid)
                  if 30 <= seconds(s["observed_at"], created) <= 90), None)
    if entry is None:
        return "missing_entry_30_90s"
    if entry == len(valid) - 1:
        return "entry_without_followup"
    gaps = [seconds(b["observed_at"], a["observed_at"])
            for a, b in zip(valid[entry:], valid[entry+1:])]
    if any(g <= 0 or g > 90 for g in gaps):
        return "followup_gap_over_90s"
    return "replay_candidate"

def main():
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        print("Missing Supabase credentials", file=sys.stderr)
        return 2
    headers = {"apikey": key, "Authorization": "Bearer " + key}
    launches = request_json(url + "/rest/v1/launches?select=mint,created_at"
                            "&order=first_seen_at.desc&limit=500", headers) or []
    groups = defaultdict(list)
    # Batch to keep URLs short and avoid one oversized query.
    for start in range(0, len(launches), 40):
        batch = launches[start:start+40]
        mints = ",".join(quote(x["mint"], safe="") for x in batch)
        rows = request_json(url + "/rest/v1/token_snapshots?"
                            "select=mint,observed_at,price_usd&mint=in.(" + mints +
                            ")&order=observed_at.asc&limit=10000", headers) or []
        for row in rows:
            groups[row["mint"]].append(row)
    counts = defaultdict(int)
    for launch in launches:
        try:
            counts[classify(launch, groups[launch["mint"]])] += 1
        except (ValueError, TypeError, OverflowError):
            counts["invalid_observation"] += 1
    print("COVERAGE_REPORT", json.dumps({"launches_checked": len(launches),
          "classifications": dict(counts), "note": "replay candidates are not validated trades"},
          sort_keys=True))
    return 0

if __name__ == "__main__":
    sys.exit(main())
