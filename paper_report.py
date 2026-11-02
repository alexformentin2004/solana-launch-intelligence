"""Read-only paper replay diagnostics using historical Supabase snapshots.

This does NOT create trades, orders, or performance claims. Only an entry
sample 30-90 seconds after pool creation is eligible for a launch-entry replay.
"""
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from urllib.parse import quote
from collector import request_json
from paper_strategy import replay
from execution_costs import apply_costs

URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

def parse_time(value):
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))

def evaluate(launch, snapshots):
    created = launch.get("created_at")
    if not created:
        return {"status": "insufficient_data", "reason": "unknown_pool_creation_time"}
    try:
        born = parse_time(created)
    except (ValueError, TypeError):
        return {"status": "insufficient_data", "reason": "invalid_pool_creation_time"}
    samples = sorted(snapshots, key=lambda r: r["observed_at"])
    entry_index = None
    for index, sample in enumerate(samples):
        try:
            delay = (parse_time(sample["observed_at"]) - born).total_seconds()
        except (ValueError, TypeError):
            continue
        if 30 <= delay <= 90:
            entry_index = index
            break
    if entry_index is None:
        return {"status": "insufficient_data", "reason": "no_entry_sample_30_to_90_seconds"}
    return replay(samples[entry_index:])

def main():
    if not URL or not KEY:
        print("Missing Supabase credentials", file=sys.stderr)
        return 2
    headers = {"apikey": KEY, "Authorization": "Bearer " + KEY}
    launches = request_json(URL + "/rest/v1/launches?select=mint,created_at"
                            "&order=first_seen_at.desc&limit=100", headers) or []
    if not launches:
        print("PAPER_DIAGNOSTIC no_launches")
        return 0
    mints = ",".join(quote(r["mint"], safe="") for r in launches)
    path = "/rest/v1/token_snapshots?select=mint,observed_at,price_usd&mint=in.(" + mints + ")&order=observed_at.asc&limit=5000"
    rows = request_json(URL + path, headers) or []
    by_mint = defaultdict(list)
    for row in rows:
        by_mint[row["mint"]].append(row)
    counts = defaultdict(int)
    examples = []
    for launch in launches:
        result = evaluate(launch, by_mint[launch["mint"]])
        key = result.get("reason") or result["status"]
        counts[key] += 1
        if len(examples) < 5 and result["status"] == "approximate":
            adjusted = apply_costs(result)
            examples.append({"mint_prefix": launch["mint"][:8],
                             "status": result["status"],
                             "marked_return_pct": result["total_marked_return_pct"],
                             "estimated_net_marked_return_pct": adjusted["estimated_net_marked_return_pct"],
                             "events": len(result["events"])})
    print("PAPER_DIAGNOSTIC", json.dumps({"launches": len(launches),
          "snapshots": len(rows), "classification": dict(counts),
          "illustrative_replays": examples, "live_trades": 0,
          "note": "hypothetical fees/slippage only; no actual execution or liquidity impact model"}, sort_keys=True))
    return 0

if __name__ == "__main__":
    sys.exit(main())
