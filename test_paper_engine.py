import unittest
from datetime import datetime,timezone,timedelta
from paper_engine import entry_allowed

class PaperEngineTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime.now(timezone.utc)
    def samples(self,gap=40,age=10):
        end=self.now-timedelta(seconds=age)
        return [{"observed_at":(end-timedelta(seconds=gap)).isoformat(),"price_usd":"0.01"},
                {"observed_at":end.isoformat(),"price_usd":"0.011"}]
    def test_reject_never_enters(self):
        self.assertEqual(entry_allowed({"decision":"reject"},self.samples(),self.now)[1],"not_candidate")
    def test_candidate_needs_two_prices(self):
        self.assertEqual(entry_allowed({"decision":"candidate"},self.samples()[:1],self.now)[1],"need_two_quotes")
    def test_candidate_requires_fresh_prices(self):
        self.assertEqual(entry_allowed({"decision":"candidate"},self.samples(age=100),self.now)[1],"stale_quote")
    def test_candidate_refuses_gap(self):
        self.assertEqual(entry_allowed({"decision":"candidate"},self.samples(gap=300),self.now)[1],"sampling_gap")
    def test_candidate_eligible(self):
        self.assertEqual(entry_allowed({"decision":"candidate"},self.samples(),self.now)[1],"eligible")

if __name__=="__main__":unittest.main()
