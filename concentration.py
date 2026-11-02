"""Best-effort top token ACCOUNT concentration (not unique wallet owners)."""
import json
import os
import urllib.request

RPC=os.environ.get("SOLANA_RPC_URL","https://api.mainnet-beta.solana.com")

def call(method,params):
    body=json.dumps({"jsonrpc":"2.0","id":1,"method":method,"params":params}).encode()
    req=urllib.request.Request(RPC,body,{"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=12) as response:
        result=json.load(response)
    if result.get("error"):
        raise ValueError("RPC error in "+method)
    return result["result"]

def concentration(mint):
    supply=call("getTokenSupply",[mint,{"commitment":"confirmed"}])
    accounts=call("getTokenLargestAccounts",[mint,{"commitment":"confirmed"}])
    total=int(supply["value"]["amount"])
    if total<=0:
        return {"status":"unavailable","reason":"zero_supply"}
    amounts=[int(x["amount"]) for x in accounts["value"]]
    if not amounts:
        return {"status":"unavailable","reason":"no_token_accounts_returned"}
    return {"status":"verified","unit":"token_accounts_not_unique_wallets",
            "top1_pct":round(100*sum(amounts[:1])/total,2),
            "top10_pct":round(100*sum(amounts[:10])/total,2),
            "top20_pct":round(100*sum(amounts[:20])/total,2),
            "account_count":len(amounts)}
