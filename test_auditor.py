import unittest
from onchain import _base58, SPL_TOKEN, TOKEN_2022
from auditor import audit
from unittest.mock import patch
from concentration import concentration
from rpc_worker import eligible
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
