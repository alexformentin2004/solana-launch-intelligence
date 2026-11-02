"""Top token-account concentration with per-method RPC diagnostics."""
import json
import os
import time
import urllib.error
import urllib.request

RPC = os.environ.get("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
FALLBACK_RPC = os.environ.get("SOLANA_FALLBACK_RPC_URL", "https://rpc.magicblock.app/mainnet").strip()
PROBE_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"  # USDC mainnet

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
        diagnostic("fallback_probe_skipped", reason="not_configured")
        return False
    try:
        result = call("getTokenLargestAccounts",
                      [PROBE_MINT, {"commitment":"confirmed"}], endpoint=FALLBACK_RPC)
        valid = (isinstance(result, dict) and isinstance(result.get("value"), list)
                and len(result["value"]) > 0
                and all(isinstance(x, dict) and str(x.get("amount", "")).isdigit()
                        for x in result["value"]))
        diagnostic("fallback_probe_result", valid=valid)
        return valid
    except RPCMethodError as exc:
        diagnostic("fallback_probe_failed", kind=exc.kind, provider=exc.provider)
        return False

def diagnostic(stage, **fields):
    """Log only method/status/provider metadata; never endpoints or credentials."""
    print("RPC_DIAGNOSTIC", stage, json.dumps(fields, sort_keys=True), flush=True)

def supply_with_fallback(mint):
    """Try the configured fallback when the primary supply endpoint is throttled."""
    params = [mint, {"commitment":"confirmed"}]
    try:
        result = call("getTokenSupply", params)
        diagnostic("supply_ok", provider="primary")
        return result, "primary"
    except RPCMethodError as exc:
        diagnostic("supply_primary_failed", kind=exc.kind, provider=exc.provider)
        if exc.kind != "rate_limited" or not FALLBACK_RPC or FALLBACK_RPC == RPC:
            raise
        diagnostic("supply_fallback_attempt", configured=True)
        try:
            result = call("getTokenSupply", params, endpoint=FALLBACK_RPC)
            diagnostic("supply_ok", provider="fallback")
            return result, "fallback"
        except RPCMethodError as fallback_error:
            diagnostic("supply_fallback_failed", kind=fallback_error.kind, provider=fallback_error.provider)
            raise fallback_error from exc

def concentration(mint):
    supply, supply_provider = supply_with_fallback(mint)
    try:
        total = int(supply["value"]["amount"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RPCMethodError("getTokenSupply", "invalid_response", "missing amount") from exc
    if total <= 0:
        return {"status":"unavailable","reason":"zero_supply",
                "supply_check":"verified","supply_provider":supply_provider}
    provider = "primary"
    try:
        accounts = call("getTokenLargestAccounts", [mint, {"commitment":"confirmed"}])
        diagnostic("largest_accounts_ok", provider="primary")
    except RPCMethodError as exc:
        diagnostic("largest_accounts_primary_failed", kind=exc.kind)
        if exc.kind != "rate_limited":
            raise
        diagnostic("largest_accounts_retry", delay_seconds=2)
        time.sleep(2)
        try:
            accounts = call("getTokenLargestAccounts", [mint, {"commitment":"confirmed"}])
            diagnostic("largest_accounts_ok", provider="primary_retry")
        except RPCMethodError as second:
            diagnostic("largest_accounts_retry_failed", kind=second.kind)
            if second.kind != "rate_limited" or not FALLBACK_RPC or FALLBACK_RPC == RPC:
                raise
            if not fallback_preflight():
                raise RPCMethodError("getTokenLargestAccounts", "fallback_preflight_failed",
                                     "Fallback did not return valid token accounts for probe mint",
                                     False, "fallback") from second
            diagnostic("largest_accounts_fallback_attempt", configured=True)
            accounts = call("getTokenLargestAccounts", [mint, {"commitment":"confirmed"}], endpoint=FALLBACK_RPC)
            diagnostic("largest_accounts_ok", provider="fallback")
            provider = "fallback"
    try:
        amounts = [int(x["amount"]) for x in accounts["value"]]
    except (KeyError, TypeError, ValueError) as exc:
        raise RPCMethodError("getTokenLargestAccounts", "invalid_response", "invalid accounts") from exc
    if not amounts:
        return {"status":"unavailable","reason":"no_token_accounts_returned",
                "supply_check":"verified","largest_accounts_check":"verified","largest_accounts_provider":provider,"supply_provider":supply_provider}
    return {"status":"verified","unit":"token_accounts_not_unique_wallets",
            "supply_check":"verified","largest_accounts_check":"verified",
            "largest_accounts_provider":provider,"supply_provider":supply_provider,
            "top1_pct":round(100*sum(amounts[:1])/total,2),
            "top10_pct":round(100*sum(amounts[:10])/total,2),
            "top20_pct":round(100*sum(amounts[:20])/total,2),
            "account_count":len(amounts)}
