"""Read-only live scanner health report; never submits trades."""
import json
import os
from datetime import datetime, timezone
from urllib.parse import quote
from collector import request_json

def get(table, select, extra=""):
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/" + table
    url += "?select=" + quote(select, safe=",()*") + extra
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return request_json(url, {"apikey": key, "Authorization": "Bearer " + key}) or []

def main():
    launches = get("launches", "mint,created_at,first_seen_at", "&order=first_seen_at.desc&limit=500")
    snapshots = get("token_snapshots", "mint,observed_at,price_usd,liquidity_usd,volume_5m_usd,buys_5m,sells_5m", "&order=observed_at.desc&limit=1000")
    runs = get("collection_runs", "started_at,status,items_seen", "&order=started_at.desc&limit=10")
    now = datetime.now(timezone.utc)
    def parse(s):
        return datetime.fromisoformat(s.replace("Z","+00:00"))
    recent = [x for x in launches if x.get("first_seen_at") and (now-parse(x["first_seen_at"])).total_seconds() <= 3600]
    delays = [max(0,(parse(x["first_seen_at"])-parse(x["created_at"])).total_seconds())
              for x in launches if x.get("created_at") and x.get("first_seen_at")]
    delays.sort()
    print("SCANNER_HEALTH", json.dumps({
        "checked_at":now.isoformat(), "launches_last_hour":len(recent),
        "recent_launches_sampled":len(launches), "snapshots_sampled":len(snapshots),
        "launch_detection_delay_median_seconds":round(delays[len(delays)//2]) if delays else None,
        "launch_detection_delay_p90_seconds":round(delays[int(.9*(len(delays)-1))]) if delays else None,
        "last_collection_status":runs[0]["status"] if runs else None,
        "last_collection_at":runs[0]["started_at"] if runs else None,
        "runs_last_10_success":sum(x["status"]=="success" for x in runs),
        "trades_executed":0,
        "note":"5-minute scheduled polling cannot validate second-level entry timing."
    },sort_keys=True))

if __name__=="__main__":
    main()
