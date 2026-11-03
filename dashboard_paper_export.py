"""Enrich existing dashboard JSON with read-only modeled paper metrics."""
import json,os
from urllib.parse import quote
from collector import request_json
url=os.environ.get("SUPABASE_URL","").rstrip("/")
key=os.environ.get("SUPABASE_SERVICE_ROLE_KEY","")
def main():
    headers={"apikey":key,"Authorization":"Bearer "+key}
    rows=request_json(url+"/rest/v1/paper_positions?select=status,opened_at,entry_price,remaining_fraction,realized_usd,last_price,close_reason&order=opened_at.desc&limit=500",headers) or []
    def profit(p):
        entry=float(p["entry_price"])
        remaining=float(p["remaining_fraction"])
        return float(p["realized_usd"])+10*remaining*float(p["last_price"])/entry*.99*.995-10*1.015 if entry>0 else 0
    with open("dashboard/data.json") as f:data=json.load(f)
    data["paper_open"]=sum(p["status"]=="open" for p in rows)
    data["paper_closed"]=sum(p["status"]=="closed" for p in rows)
    data["paper_total"]=len(rows)
    data["paper_modeled_pnl_usd"]=round(sum(profit(p) for p in rows),2)
    data["paper_positions"]=[{"status":p["status"],"opened_at":p["opened_at"],"modeled_pnl_usd":round(profit(p),2),"close_reason":p.get("close_reason")} for p in rows[:30]]
    data["paper_disclaimer"]="Hypothetical observed-price positions, not executable fills; modeled 1.5% entry and 1.5% exit costs."
    with open("dashboard/data.json","w") as f:json.dump(data,f,separators=(",",":"))
    print("PAPER_DASHBOARD",json.dumps({"open":data["paper_open"],"closed":data["paper_closed"],"positions":len(rows)}))
if __name__=="__main__":main()
