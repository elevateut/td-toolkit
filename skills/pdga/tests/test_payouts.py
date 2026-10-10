"""python3 -m unittest discover -s pdga/tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import payouts as P  # noqa: E402


class CashLine(unittest.TestCase):
    def test_forty_percent_rounded_up(self):
        for n, want in [(1, 1), (2, 1), (3, 2), (4, 2), (7, 3), (12, 5), (20, 8), (400, 160)]:
            self.assertEqual(P.cash_line(n), want, n)


class Division(unittest.TestCase):
    def test_sample_event_matches_tm_to_the_dollar(self):
        # Anonymised sample event 1062 in tests/fixtures/tm_payouts_sample.json
        self.assertEqual(P.division_payouts(12, 1152, 322), [531, 361, 251, 184, 147])  # MPO purse 1474
        self.assertEqual(P.division_payouts(12, 1152, 321), [531, 361, 251, 184, 146])  # MP40 purse 1473
        self.assertEqual(P.division_payouts(3, 288, 80), [230, 138])                    # MP50 purse 368

    def test_small_fields(self):
        self.assertEqual(P.division_payouts(7, 308), [147, 92, 69])
        self.assertEqual(P.division_payouts(12, 528), [190, 129, 90, 66, 53])
        self.assertEqual(P.division_payouts(4, 176), [110, 66])

    def test_always_sums_to_purse(self):
        for n in range(1, 60):
            for fees in (44 * n, 65 * n + 7):
                self.assertEqual(sum(P.division_payouts(n, fees, 123)), fees + 123)


class Ties(unittest.TestCase):
    def test_tie_for_first_splits_first_and_second(self):
        out = P.split_ties([{"place": 1, "name": "A"}, {"place": 1, "name": "B"}, {"place": 3, "name": "C"}],
                           [190, 129, 90])
        self.assertEqual([o["amount"] for o in out], [159.5, 159.5, 90.0])
        self.assertEqual(out[0]["tied_places"], [1, 2])

    def test_tie_straddling_cash_line_shares_only_paid_places(self):
        out = P.split_ties([{"place": 1, "name": "A"}] + [{"place": 2, "name": x} for x in "BCD"], [50, 30, 20])
        self.assertEqual([o["amount"] for o in out], [50.0, 16.67, 16.67, 16.66])
        self.assertAlmostEqual(sum(o["amount"] for o in out), 100.0)

    def test_players_below_cash_line_get_nothing(self):
        out = P.split_ties([{"place": 1, "name": "A"}, {"place": 2, "name": "B"}, {"place": 3, "name": "C"}], [110, 66])
        self.assertEqual([o["name"] for o in out], ["A", "B"])


class VersusTM(unittest.TestCase):
    def test_small_diffs_pay_tm(self):
        ok, reasons, _ = P.compare_to_tm([190, 129, 90, 66, 53], [191, 128, 90, 66, 53], 5, 5)
        self.assertTrue(ok, reasons)

    def test_tm_whole_dollar_tie_split_pays_tm(self):
        # TM Publish splits a 190+129 tie as 160/160 and drops 5th from 53 to 52.
        ours = [w["amount"] for w in P.split_ties(
            [{"place": 1, "name": "A"}, {"place": 1, "name": "B"}] + [{"place": p, "name": str(p)} for p in (3, 4, 5)],
            [190, 129, 90, 66, 53])]
        self.assertTrue(P.compare_to_tm(ours, [160, 160, 90, 66, 52], 5, 5)[0])

    def test_tm_unsplit_tie_is_a_hard_stop(self):
        ours = [w["amount"] for w in P.split_ties([{"place": 1, "name": "A"}, {"place": 1, "name": "B"}], [110, 66])]
        self.assertFalse(P.compare_to_tm(ours, [110, 66], 2, 2)[0])  # $22 off per player
        self.assertTrue(P.compare_to_tm(ours, [88, 88], 2, 2)[0])

    def test_hard_stops(self):
        self.assertFalse(P.compare_to_tm([190, 129, 90, 66, 53], [190, 129, 90, 66, 50], 5, 5)[0])  # total
        self.assertFalse(P.compare_to_tm([190, 129, 90, 66, 53], [197, 122, 90, 66, 53], 5, 5)[0])  # >$5
        self.assertFalse(P.compare_to_tm([110, 66], [110, 66], 2, 3)[0])                             # cash line


class Regression(unittest.TestCase):
    def test_anchor_divisions_match_sampled_tm(self):
        fixture = Path(__file__).resolve().parent / "fixtures" / "tm_payouts_sample.json"
        exact, total, fails = P.regression(fixture)
        self.assertEqual(fails, [])
        self.assertGreater(exact, 0)


if __name__ == "__main__":
    unittest.main()
