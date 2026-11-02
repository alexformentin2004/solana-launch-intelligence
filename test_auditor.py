import unittest
from onchain import _base58, SPL_TOKEN, TOKEN_2022
from auditor import audit
from unittest.mock import patch
from concentration import concentration, RPCMethodError
from rpc_worker import eligible, priority
from datetime import datetime, timedelta, timezone

class AuditTests(unittest.TestCase):
    def test_base58_authority_encoding(self):
        self.assertEqual(_base58(bytes(32)), "1" * 32)
        self.assertEqual(_base58(bytes([0] * 31 + [1])), "1" * 31 + "2")
    def test_token_program_ids(self):
        self.assertNotEqual(SPL_TOKEN, TOKEN_2022)
        self.assertEqual(TOKEN_2022, "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb")
    def test_concentration_top_accounts(self):
        def fake_rpc(method, params):
            if method == "getTokenSupply":
                return {"value":{"amount":"1000"}}
            return {"value":[{"amount":"600"},{"amount":"200"}]}
        with patch("concentration.call", side_effect=fake_rpc):
            result=concentration("mint")
        self.assertEqual(result["top1_pct"],60.0)
        self.assertEqual(result["top10_pct"],80.0)
        self.assertEqual(result["unit"],"token_accounts_not_unique_wallets")
    def test_empty_concentration_unavailable(self):
        with patch("concentration.call",side_effect=[
            {"value":{"amount":"1000"}},{"value":[]}]):
            self.assertEqual(concentration("mint")["status"],"unavailable")
    def test_supply_zero_skips_largest_accounts(self):
        with patch("concentration.call", return_value={"value":{"amount":"0"}}) as rpc:
            result=concentration("mint")
        self.assertEqual(result["reason"],"zero_supply")
        rpc.assert_called_once()
    def test_rpc_error_identifies_method(self):
        with patch("concentration.FALLBACK_RPC", ""), patch("concentration.call", side_effect=[
            {"value":{"amount":"1000"}},
            RPCMethodError("getTokenLargestAccounts","rate_limited","HTTP 429"),
            RPCMethodError("getTokenLargestAccounts","rate_limited","HTTP 429")]) as rpc, patch("concentration.time.sleep") as pause:
            with self.assertRaises(RPCMethodError) as ctx:
                concentration("mint")
        self.assertEqual(rpc.call_count, 3)
        pause.assert_called_once_with(5)
        self.assertEqual(ctx.exception.method,"getTokenLargestAccounts")
        self.assertEqual(ctx.exception.kind,"rate_limited")
    def test_largest_accounts_retry_once(self):
        failure=RPCMethodError("getTokenLargestAccounts","rate_limited","HTTP 429")
        with patch("concentration.call",side_effect=[
            {"value":{"amount":"1000"}},failure,
            {"value":[{"amount":"500"}]}]) as rpc, patch("concentration.time.sleep") as pause:
            result=concentration("mint")
        self.assertEqual(result["status"],"verified")
        self.assertEqual(rpc.call_count,3)
        pause.assert_called_once_with(5)
    def test_largest_accounts_free_fallback(self):
        error=RPCMethodError("getTokenLargestAccounts","rate_limited","HTTP 429")
        with patch("concentration.FALLBACK_RPC","https://solana-rpc.publicnode.com"), patch("concentration.call",side_effect=[
            {"value":{"amount":"1000"}},error,error,{"solana-core":"1.18.0"},{"value":[{"amount":"500"}]}]) as rpc, patch("concentration.time.sleep"):
            result=concentration("mint")
        self.assertEqual(result["largest_accounts_provider"],"fallback")
        self.assertEqual(result["top1_pct"],50)
        self.assertEqual(rpc.call_count,5)
        self.assertEqual(rpc.call_args.kwargs["endpoint"],"https://solana-rpc.publicnode.com")
    def test_fallback_preflight_rejects_403(self):
        from concentration import fallback_preflight
        with patch("concentration.FALLBACK_RPC","https://example.invalid"), patch(
            "concentration.call", side_effect=RPCMethodError("getVersion","http_error","HTTP 403",False,"fallback")):
            self.assertFalse(fallback_preflight())
    def test_rpc_error_provider(self):
        self.assertEqual(RPCMethodError("getTokenLargestAccounts","http_error",
                         "HTTP 403",False,"fallback").provider,"fallback")
        self.assertFalse(RPCMethodError("getTokenLargestAccounts","http_error",
                         "HTTP 403",False,"fallback").retryable)
    def test_rpc_queue_max_attempts(self):
        row={"metrics":{"rpc_queue":{"attempts":5},"onchain":{"status":"error"}}}
        self.assertFalse(eligible(row))
    def test_rpc_queue_cooldown(self):
        future=(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat()
        row={"metrics":{"rpc_queue":{"attempts":1,"next_attempt_at":future}}}
        self.assertFalse(eligible(row))
    def test_rpc_queue_completed(self):
        row={"metrics":{"onchain":{"status":"verified"},"concentration":{"status":"verified"}}}
        self.assertFalse(eligible(row))
    def test_rpc_queue_pending(self):
        row={"metrics":{"onchain":{"status":"verified"},"concentration":{"status":"error"}}}
        self.assertTrue(eligible(row))
    def test_rpc_priority_liquidity_and_volume(self):
        low={"metrics":{"liquidity_usd":100,"volume_5m_usd":10}}
        high={"metrics":{"liquidity_usd":100000,"volume_5m_usd":10000}}
        self.assertGreater(priority(high),priority(low))
    def test_partial_verification_priority(self):
        base={"liquidity_usd":1000,"volume_5m_usd":100}
        pending={"metrics":dict(base)}
        verified={"metrics":{**base,"onchain":{"status":"verified"}}}
        self.assertGreater(priority(verified),priority(pending))
    def test_token_2022_extensions_pending(self):
        chain={"status":"verified","mint_authority_present":False,
               "freeze_authority_present":False,"extensions_checked":False}
        result=audit("mint",{"attributes":{}},chain)
        self.assertIn("token_extensions",result["checks_pending"])
    def test_concentration_is_not_wallet_mapping(self):
        result=audit("mint",{"attributes":{}},concentration={"status":"verified","top10_pct":80})
        self.assertIn("token_account_owner_mapping",result["checks_pending"])
        self.assertIn("holder_concentration",result["checks_pending"])
    def test_low_liquidity(self):
        a = audit("mint", {"attributes":{"reserve_in_usd":"500","transactions":{"m5":{"buys":1,"sells":8}}}})
        self.assertEqual(a["risk_level"], "high")
        self.assertIn("mint_authority", a["checks_pending"])
    def test_missing_data_not_low_risk(self):
        a = audit("mint", {"attributes":{}})
        self.assertNotEqual(a["risk_level"], "low")
        self.assertEqual(a["confidence"], "limited")
    def test_active_authorities_increase_risk(self):
        pool = {"attributes":{"reserve_in_usd":"100000"}}
        safe = audit("mint",pool,{"status":"verified","mint_authority_present":False,"freeze_authority_present":False})
        risky = audit("mint",pool,{"status":"verified","mint_authority_present":True,"freeze_authority_present":True})
        self.assertGreater(risky["risk_score"],safe["risk_score"])
        self.assertNotIn("mint_authority",safe["checks_pending"])
    def test_no_trading_actions(self):
        a = audit("mint", {"attributes":{"reserve_in_usd":"100000"}})
        self.assertEqual(a["risk_level"], "medium")
if __name__ == "__main__":
    unittest.main()
