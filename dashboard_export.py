"""Generate public-safe aggregate dashboard data; never export credentials or wallets."""
import json,os
from datetime import datetime,timezone,timedelta
from urllib.parse import quote
from collector import request_json
URL=os.environ["SUPABASE_URL"].rstrip("/")
KEY=os.environ["SUPABASE_SERVICE_ROLE_KEY"]
HEAD={"apikey":KEY,"Authorization":"Bearer "+KEY}
def fetch(table,columns,extra=""):
    return request_json(URL+"/rest/v1/"+table+"?select="+quote(columns,safe=",()*")+extra,HEAD) or []
def main():
    signals=fetch("paper_signals","mint,decided_at,decision,reason,age_seconds,liquidity_usd,volume_5m_usd,buys_5m,sells_5m,risk_level","&order=decided_at.desc&limit=500")
    runs=fetch("collection_runs","started_at,status,items_seen","&order=started_at.desc&limit=20")
    launches=fetch("launches","mint,first_seen_at","&order=first_seen_at.desc&limit=500")
    now=datetime.now(timezone.utc)
    cutoff=now-timedelta(hours=1)
    def recent(t):
        try:return datetime.fromisoformat(t.replace("Z","+00:00"))>=cutoff
        except (AttributeError,ValueError):return False
    counts={k:sum(x["decision"]==k for x in signals) for k in ("candidate","watch","reject")}
    delays=sorted(x["age_seconds"] for x in signals if x.get("age_seconds") is not None and x["age_seconds"]>=0)
    public=[{k:x.get(k) for k in ("decided_at","decision","reason","age_seconds","liquidity_usd","volume_5m_usd","buys_5m","sells_5m","risk_level")} for x in signals[:60]]
    output={"updated_at":now.isoformat(),"last_run":runs[0] if runs else None,
        "recent_runs_success":sum(x.get("status")=="success" for x in runs),
        "launches_last_hour":sum(recent(x.get("first_seen_at")) for x in launches),
        "sample_size":len(signals),"decision_counts":counts,
        "median_detection_seconds":delays[len(delays)//2] if delays else None,
        "signals":public,"trading_mode":"observation_only","orders":0,
        "sampling_note":"Sample limited to latest 500 signals. No live executions."}
    os.makedirs("dashboard",exist_ok=True)
    with open("dashboard/data.json","w") as f:json.dump(output,f,separators=(",",":"))
    print("DASHBOARD_EXPORT",json.dumps({"signals":len(signals),"counts":counts,"orders":0}))
if __name__=="__main__":main()
