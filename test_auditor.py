import unittest
from auditor import audit

class AuditTests(unittest.TestCase):
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
