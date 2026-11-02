"""Top token-account concentration with per-method RPC diagnostics."""
import json
import os
import time
import urllib.error
import urllib.request

RPC = os.environ.get("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
FALLBACK_RPC = os.environ.get("SOLANA_FALLBACK_RPC_URL", "https://rpc.magicblock.app/mainnet").strip()\nPROBE_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"  # USDC mainnet

class RPCMethodError(Exception):
    def __init__(self, method, kind, detail="", retryable=True, provider="primary"):
        super().__init__(method + ": " + kind)
        self.method = method
        self.kind = kind
        self.detail = str(detail)[:150]
        self.retryable = retryable
        self.provider = provider

def call(method, params, endpoint=None):
    body = json.dumps({"jsonrpc":"2.0","id":1,"method":method,"params":params}).encode()
    req = urllib.request.Request(endpoint or RPC, body, {"Content-Type":"application/json"})
    provider = "fallback" if endpoint and endpoint != RPC else "primary"
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RPCMethodError(method, "rate_limited" if exc.code == 429 else "http_error",
                             "HTTP " + str(exc.code), exc.code in (429, 500, 502, 503, 504), provider) from exc
    except (OSError, ValueError) as exc:
        raise RPCMethodError(method, "transport_error", type(exc).__name__, provider=provider) from exc
    if result.get("error"):
        error = result["error"]
        code = error.get("code") if isinstance(error, dict) else None
        raise RPCMethodError(method, "rpc_error", "RPC code " + str(code), code in (-32005, -32004, -32603), provider)
    if "result" not in result:
        raise RPCMethodError(method, "invalid_response", "missing result", provider=provider)
    return result["result"]

def fallback_preflight():
    """Probe the exact method required, using a known mainnet SPL mint."""
    if not FALLBACK_RPC or FALLBACK_RPC == RPC:
        return False
    try:
        result = call("getTokenLargestAccounts",
                      [PROBE_MINT, {"commitment":"confirmed"}], endpoint=FALLBACK_RPC)
        return (isinstance(result, dict) and isinstance(result.get("value"), list)
                and len(result["value"]) > 0
                and all(isinstance(x, dict) and str(x.get("amount", "")).isdigit()
                        for x in result["value"]))
    except RPCMethodError:
        return False

def concentration(mint):
    supply = call("getTokenSupply", [mint, {"commitment":"confirmed"}])
    try:
        total = int(supply["value"]["amount"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RPCMethodError("getTokenSupply", "invalid_response", "missing amount") from exc
    if total <= 0:
        return {"status":"unavailable","reason":"zero_supply",
                "supply_check":"verified"}
    provider = "primary"
    try:
        accounts = call("getTokenLargestAccounts", [mint, {"commitment":"confirmed"}])
    except RPCMethodError as exc:
        if exc.kind != "rate_limited":
            raise
        time.sleep(2)
        try:
            accounts = call("getTokenLargestAccounts", [mint, {"commitment":"confirmed"}])
        except RPCMethodError as second:
            if second.kind != "rate_limited" or not FALLBACK_RPC or FALLBACK_RPC == RPC:
                raise
            if not fallback_preflight():
                raise second
            accounts = call("getTokenLargestAccounts", [mint, {"commitment":"confirmed"}], endpoint=FALLBACK_RPC)
            provider = "fallback"
    try:
        amounts = [int(x["amount"]) for x in accounts["value"]]
    except (KeyError, TypeError, ValueError) as exc:
        raise RPCMethodError("getTokenLargestAccounts", "invalid_response", "invalid accounts") from exc
    if not amounts:
        return {"status":"unavailable","reason":"no_token_accounts_returned",
                "supply_check":"verified","largest_accounts_check":"verified","largest_accounts_provider":provider}
    return {"status":"verified","unit":"token_accounts_not_unique_wallets",
            "supply_check":"verified","largest_accounts_check":"verified",
            "largest_accounts_provider":provider,
            "top1_pct":round(100*sum(amounts[:1])/total,2),
            "top10_pct":round(100*sum(amounts[:10])/total,2),
            "top20_pct":round(100*sum(amounts[:20])/total,2),
            "account_count":len(amounts)}
