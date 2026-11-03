"""Aggregate rejection causes without exposing mint addresses or secrets."""
import json,os
from collections import Counter
from collector import request_json

def main():
    url=os.environ["SUPABASE_URL"].rstrip("/")
    key=os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    headers={"apikey":key,"Authorization":"Bearer "+key}
    signals=request_json(url+"/rest/v1/paper_signals?select=decision,reason,age_seconds,risk_level&order=decided_at.desc&limit=500",headers) or []
    causes=Counter()
    for signal in signals:
        for reason in (signal.get("reason") or "").split(","):
            if reason:causes[reason]+=1
    delays=sorted(x["age_seconds"] for x in signals if isinstance(x.get("age_seconds"),int) and x["age_seconds"]>=0)
    with open("dashboard/data.json",encoding="utf-8") as f:data=json.load(f)
    data["rejection_causes"]=[{"reason":k,"count":v} for k,v in causes.most_common(12)]
    data["signal_delay_p90_seconds"]=delays[int(.9*(len(delays)-1))] if delays else None
    with open("dashboard/data.json","w",encoding="utf-8") as f:json.dump(data,f,separators=(",",":"))
    print("SIGNAL_DIAGNOSTIC",json.dumps({"sample":len(signals),"causes":causes.most_common(8)}))
if __name__=="__main__":main()
