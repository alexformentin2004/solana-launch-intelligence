"""Publish public-safe paper portfolio metrics from server-side Supabase credentials."""
import json
import os
from collector import request_json

def main():
    url=os.environ["SUPABASE_URL"].rstrip("/")
    key=os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    headers={"apikey":key,"Authorization":"Bearer "+key}
    positions=request_json(url+"/rest/v1/paper_positions?select=status,opened_at,entry_price,entry_notional_usd,remaining_fraction,realized_usd,last_price,close_reason&order=opened_at.desc&limit=500",headers) or []
    def modeled_pnl(p):
        principal=float(p["entry_notional_usd"])
        entry=float(p["entry_price"])
        remaining=float(p["remaining_fraction"])
        marked=principal*remaining*float(p["last_price"])/entry*0.99*0.995 if entry>0 else 0
        return float(p["realized_usd"])+marked-principal*1.015
    with open("dashboard/data.json",encoding="utf-8") as file:
        data=json.load(file)
    data["paper_open"]=sum(p["status"]=="open" for p in positions)
    data["paper_closed"]=sum(p["status"]=="closed" for p in positions)
    data["paper_total"]=len(positions)
    data["paper_modeled_pnl_usd"]=round(sum(modeled_pnl(p) for p in positions),2)
    data["paper_positions"]=[{"status":p["status"],"opened_at":p["opened_at"],
        "modeled_pnl_usd":round(modeled_pnl(p),2),"close_reason":p.get("close_reason")}
        for p in positions[:30]]
    data["paper_disclaimer"]="Observational estimates only; not executable quotes or real trades."
    with open("dashboard/data.json","w",encoding="utf-8") as file:
        json.dump(data,file,separators=(",",":"))
    print("PAPER_DASHBOARD",json.dumps({"open":data["paper_open"],"closed":data["paper_closed"],"total":len(positions)}))

if __name__=="__main__":
    main()
