import unittest
from datetime import datetime,timezone,timedelta
from paper_signal_worker import decide

class SignalDecisionTests(unittest.TestCase):
    def setUp(self):
        self.t=datetime.now(timezone.utc)
        self.launch={"mint":"example","created_at":self.t.isoformat()}
        self.snap={"observed_at":(self.t+timedelta(seconds=75)).isoformat(),
            "liquidity_usd":15000,"volume_5m_usd":4000,
            "buys_5m":20,"sells_5m":5,"price_usd":0.01}
    def test_medium_risk_is_research_candidate(self):
        x=decide(self.launch,self.snap,{"risk_level":"medium"})
        self.assertEqual(x["decision"],"candidate")
        self.assertFalse(x["simulated_order"])
        self.assertIn("unverified_risk",x["strategy_version"])
    def test_high_risk_rejected(self):
        self.assertEqual(decide(self.launch,self.snap,{"risk_level":"high"})["decision"],"reject")
    def test_unknown_risk_rejected(self):
        self.assertEqual(decide(self.launch,self.snap,None)["decision"],"reject")
    def test_older_launch_watch_only_if_other_checks_pass(self):
        s={**self.snap,"observed_at":(self.t+timedelta(seconds=350)).isoformat()}
        self.assertEqual(decide(self.launch,s,{"risk_level":"medium"})["decision"],"watch")
    def test_weak_liquidity_rejected(self):
        s={**self.snap,"liquidity_usd":500}
        self.assertEqual(decide(self.launch,s,{"risk_level":"medium"})["decision"],"reject")

if __name__=="__main__":unittest.main()
