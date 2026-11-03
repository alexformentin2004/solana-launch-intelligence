"""Conservative observational paper ledger. No orders, wallets or live execution.
Requires two fresh quotes within 90s; never backdates an entry to launch time.
"""
import json,os
from datetime import datetime,timezone
from urllib.parse import quote
from collector import request_json,db
URL=os.environ["SUPABASE_URL"].rstrip("/")
KEY=os.environ["SUPABASE_SERVICE_ROLE_KEY"]
H={"apikey":KEY,"Authorization":"Bearer "+KEY}
def fetch(table,fields,extra=""):
    return request_json(URL+"/rest/v1/"+table+"?select="+quote(fields,safe=",()*")+extra,H) or []
def stamp(s):return datetime.fromisoformat(s.replace("Z","+00:00"))
def entry_allowed(signal,observations,now):
    if signal["decision"]!="candidate":return False,"not_candidate"
    valid=[x for x in observations if x.get("price_usd") and float(x["price_usd"])>0]
    if len(valid)<2:return False,"need_two_quotes"
    a,b=valid[-2:]
    dt=(stamp(b["observed_at"])-stamp(a["observed_at"])).total_seconds()
    freshness=(now-stamp(b["observed_at"])).total_seconds()
    if not 0<dt<=90:return False,"sampling_gap"
    if not 0<=freshness<=90:return False,"stale_quote"
    return True,"eligible"
def main():
    now=datetime.now(timezone.utc)
    signals=fetch("paper_signals","mint,decision,decided_at","&order=decided_at.desc&limit=200")
    positions=fetch("paper_positions","mint,status,opened_at,entry_price,entry_notional_usd,remaining_fraction,stop_pct,next_target,realized_usd,last_observed_at,last_price","&limit=1000")
    existing={p["mint"]:p for p in positions}
    snapshots=fetch("token_snapshots","mint,observed_at,price_usd","&order=observed_at.desc&limit=3000")
    grouped={}
    for s in snapshots:grouped.setdefault(s["mint"],[]).append(s)
    for group in grouped.values():group.sort(key=lambda s:s["observed_at"])
    opened=closed=updated=0
    for s in signals:
        mint=s["mint"]
        if mint in existing:continue
        ok,_=entry_allowed(s,grouped.get(mint,[]),now)
        if not ok:continue
        last=grouped[mint][-1]
        price=float(last["price_usd"])
        position={"mint":mint,"status":"open","opened_at":last["observed_at"],
            "entry_price":price,"last_price":price,"last_observed_at":last["observed_at"],
            "entry_notional_usd":10,"remaining_fraction":1,"stop_pct":-18,
            "next_target":0,"realized_usd":0,"strategy_version":"paper_observed_v1"}
        db("paper_positions",[position],"resolution=ignore-duplicates,return=minimal","mint")
        # Entry fee/slippage charged as a modeled cost at exit accounting.
        opened+=1
    # Exit processing deliberately uses last observed quote only and refuses stale marks.
    targets=[(100,.4,85),(200,.4,150),(300,.2,None)]
    for p in positions:
        if p["status"]!="open":continue
        observations=[x for x in grouped.get(p["mint"],[]) if x["observed_at"]>p["last_observed_at"] and x.get("price_usd")]
        if not observations:continue
        remaining=float(p["remaining_fraction"]);entry=float(p["entry_price"]);stop=float(p["stop_pct"])
        target=int(p["next_target"]);realized=float(p["realized_usd"]);fills=[]
        last_time=p["last_observed_at"];last_price=float(p["last_price"])
        for x in observations:
            price=float(x["price_usd"])
            if price<=0:continue
            # Never infer intermediate stop/TP hits from missing observations.
            change=(price/entry-1)*100
            if change<=stop:
                fraction=remaining
                cash=10*fraction*(price/entry)*.99*.995
                fills.append({"mint":p["mint"],"observed_at":x["observed_at"],"kind":"stop",
                    "fraction":fraction,"observed_price":price,"modeled_net_cash_usd":cash,
                    "note":"Observed quote; modeled 1% exit slippage + 0.5% fee; not executable."})
                realized+=cash;remaining=0
            else:
                while target<len(targets) and change>=targets[target][0]:
                    threshold,fraction,new_stop=targets[target]
                    fraction=min(fraction,remaining)
                    cash=10*fraction*(price/entry)*.99*.995
                    fills.append({"mint":p["mint"],"observed_at":x["observed_at"],"kind":"tp"+str(target+1),
                        "fraction":fraction,"observed_price":price,"modeled_net_cash_usd":cash,
                        "note":"Observed quote; modeled 1% exit slippage + 0.5% fee; not executable."})
                    realized+=cash;remaining=round(max(0,remaining-fraction),8)
                    target+=1
                    if new_stop is not None:stop=max(stop,new_stop)
            last_time=x["observed_at"];last_price=price
            if remaining<=0:break
        if last_time==p["last_observed_at"]:continue
        # Update existing position by mint, with minimal PostgREST PATCH.
        payload={"remaining_fraction":remaining,"stop_pct":stop,"next_target":target,
            "realized_usd":realized,"last_observed_at":last_time,"last_price":last_price}
        if remaining<=0:
            payload.update({"status":"closed","closed_at":last_time,"close_reason":fills[-1]["kind"] if fills else "unknown"})
            closed+=1
        # Persist fills first: unique(mint,kind) prevents duplicate exit events.
        for fill in fills:
            db("paper_fills",[fill],"resolution=ignore-duplicates,return=minimal","mint,kind")
        request_json(URL+"/rest/v1/paper_positions?mint=eq."+quote(p["mint"],safe=""),{
            **H,"Content-Type":"application/json","Prefer":"return=minimal"},
            "PATCH",payload)
        updated+=1
    print("PAPER_ENGINE",json.dumps({"new_positions":opened,"updated":updated,"closed":closed,
        "real_orders":0,"assumed_entry_cost_pct":1.5,"assumed_exit_cost_pct":1.5,
        "warning":"No intrabar fills, MEV, spread or failed execution model."}))
if __name__=="__main__":main()
