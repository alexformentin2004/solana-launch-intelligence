import unittest
from coverage_report import classify

def launch():
    return {"created_at": "2026-01-01T00:00:00+00:00"}

def sample(second, price=1):
    return {"observed_at": "2026-01-01T00:%02d:%02d+00:00" % divmod(second, 60),
            "price_usd": price}

class CoverageTests(unittest.TestCase):
    def test_missing_entry(self):
        self.assertEqual(classify(launch(), [sample(10), sample(110)]), "missing_entry_30_90s")
    def test_entry_without_followup(self):
        self.assertEqual(classify(launch(), [sample(60)]), "entry_without_followup")
    def test_replay_candidate(self):
        self.assertEqual(classify(launch(), [sample(60), sample(80)]), "replay_candidate")
    def test_gap(self):
        self.assertEqual(classify(launch(), [sample(60), sample(180)]), "followup_gap_over_90s")

if __name__ == "__main__":
    unittest.main()
