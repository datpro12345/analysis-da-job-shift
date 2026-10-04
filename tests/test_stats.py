"""Unit tests for stats.py. Values checked against textbook examples and scipy."""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import stats  # noqa: E402


class WilsonTests(unittest.TestCase):
    def test_zero_successes_has_positive_upper_bound(self):
        lo, hi = stats.wilson_interval(0, 10)
        self.assertEqual(lo, 0.0)
        self.assertAlmostEqual(hi, 0.2775, places=3)  # Brown, Cai & DasGupta (2001) table

    def test_all_successes_has_upper_bound_one(self):
        lo, hi = stats.wilson_interval(10, 10)
        self.assertAlmostEqual(lo, 0.7225, places=3)
        self.assertAlmostEqual(hi, 1.0, places=9)

    def test_symmetric_half(self):
        lo, hi = stats.wilson_interval(5, 10)
        self.assertAlmostEqual(lo, 0.2366, places=3)
        self.assertAlmostEqual(hi, 0.7634, places=3)

    def test_empty_sample(self):
        self.assertEqual(stats.wilson_interval(0, 0), (0.0, 0.0))

    def test_interval_narrows_with_n(self):
        w_small = stats.wilson_interval(2, 10)
        w_large = stats.wilson_interval(20, 100)
        self.assertLess(w_large[1] - w_large[0], w_small[1] - w_small[0])

    def test_invalid_k(self):
        with self.assertRaises(ValueError):
            stats.wilson_interval(11, 10)


class FisherAndBHTests(unittest.TestCase):
    def test_fisher_matches_known_table(self):
        # Agresti's tea-tasting table [[3,1],[1,3]]: two-sided p = 0.4857
        _, p = stats.fisher_exact(3, 4, 1, 4)
        self.assertAlmostEqual(p, 0.4857, places=3)

    def test_fisher_identical_rates_gives_p_one(self):
        _, p = stats.fisher_exact(5, 10, 50, 100)
        self.assertAlmostEqual(p, 1.0, places=6)

    def test_bh_monotone_and_bounded(self):
        q = stats.benjamini_hochberg([0.01, 0.04, 0.03, 0.5])
        self.assertEqual([round(x, 4) for x in q], [0.04, 0.0533, 0.0533, 0.5])
        self.assertTrue(all(0 <= x <= 1 for x in q))

    def test_bh_keeps_input_order(self):
        q = stats.benjamini_hochberg([0.5, 0.001])
        self.assertLess(q[1], q[0])

    def test_bh_empty(self):
        self.assertEqual(stats.benjamini_hochberg([]), [])


class EffectSizeTests(unittest.TestCase):
    def test_risk_difference_and_ratio(self):
        self.assertAlmostEqual(stats.risk_difference(10, 100, 30, 100), 0.2)
        self.assertAlmostEqual(stats.risk_ratio(10, 100, 30, 100), 3.0)
        self.assertEqual(stats.risk_ratio(0, 100, 30, 100), math.inf)
        self.assertTrue(math.isnan(stats.risk_ratio(0, 100, 0, 100)))

    def test_odds_ratio_plain(self):
        orr, lo, hi = stats.odds_ratio_ci(10, 100, 30, 100)
        self.assertAlmostEqual(orr, (30 * 90) / (70 * 10), places=6)
        self.assertLess(lo, orr); self.assertGreater(hi, orr)

    def test_odds_ratio_zero_cell_is_finite(self):
        orr, lo, hi = stats.odds_ratio_ci(0, 30, 10, 100)
        self.assertTrue(math.isfinite(orr) and math.isfinite(lo) and math.isfinite(hi))
        self.assertGreater(orr, 1)

    def test_cohens_h(self):
        self.assertAlmostEqual(stats.cohens_h(0.2, 0.4), 0.4421, places=3)
        self.assertEqual(stats.cohens_h(0.3, 0.3), 0.0)

    def test_compare_prevalence_fields(self):
        c = stats.compare_prevalence(5, 50, 20, 50)
        self.assertEqual((c.k1, c.n1, c.k2, c.n2), (5, 50, 20, 50))
        self.assertAlmostEqual(c.risk_difference, 0.3)
        self.assertLess(c.fisher_p, 0.01)
        self.assertIn("odds_ratio_low", c.as_dict())


class LogOddsTests(unittest.TestCase):
    def test_sign_follows_direction(self):
        lo = stats.log_odds_informative_dirichlet({"ai": 30, "sql": 50, "excel": 10}, {"ai": 2, "sql": 55, "excel": 40})
        self.assertGreater(lo["ai"][2], 2)
        self.assertLess(lo["excel"][2], -2)
        self.assertLess(abs(lo["sql"][2]), 1)

    def test_rare_word_is_shrunk(self):
        # a word seen 2 times in A and 0 in B is not ranked above a frequent, clearly shifted word
        lo = stats.log_odds_informative_dirichlet({"rare": 2, "ai": 40, "x": 200}, {"rare": 0, "ai": 5, "x": 200})
        self.assertGreater(lo["ai"][2], lo["rare"][2])

    def test_symmetry(self):
        a, b = {"w": 10, "v": 5}, {"w": 3, "v": 12}
        ab = stats.log_odds_informative_dirichlet(a, b); ba = stats.log_odds_informative_dirichlet(b, a)
        self.assertAlmostEqual(ab["w"][2], -ba["w"][2])

    def test_zero_prior_rejected(self):
        with self.assertRaises(ValueError):
            stats.log_odds_informative_dirichlet({"a": 0}, {"a": 0})

    def test_document_frequency_counts(self):
        self.assertEqual(stats.tokens_to_counts([["a", "a", "b"], ["a"]]), {"a": 2, "b": 1})


class BootstrapKappaPowerTests(unittest.TestCase):
    def test_bootstrap_is_deterministic_and_brackets_point(self):
        a, b = [0] * 20 + [1] * 10, [0] * 10 + [1] * 20
        r1 = stats.bootstrap_ci(a, b, n_boot=300, seed=1); r2 = stats.bootstrap_ci(a, b, n_boot=300, seed=1)
        self.assertEqual(r1, r2)
        point, lo, hi = r1
        self.assertAlmostEqual(point, 1 / 3)
        self.assertLess(lo, point); self.assertGreater(hi, point)

    def test_bootstrap_rejects_empty(self):
        with self.assertRaises(ValueError):
            stats.bootstrap_ci([], [1])

    def test_kappa_values(self):
        self.assertEqual(stats.cohens_kappa(["a", "b", "a"], ["a", "b", "a"]), 1.0)
        self.assertAlmostEqual(stats.cohens_kappa(["a", "b", "a", "a"], ["a", "b", "b", "a"]), 0.5)
        # chance-level agreement with independent labels is about 0
        self.assertAlmostEqual(stats.cohens_kappa(["a", "a", "b", "b"], ["a", "b", "a", "b"]), 0.0)
        self.assertEqual(stats.cohens_kappa(["x", "x"], ["x", "x"]), 1.0)

    def test_kappa_length_mismatch(self):
        with self.assertRaises(ValueError):
            stats.cohens_kappa(["a"], ["a", "b"])

    def test_minimum_detectable_difference_shrinks_with_n(self):
        small = stats.minimum_detectable_difference(30, 100, 0.2)
        large = stats.minimum_detectable_difference(300, 1000, 0.2)
        self.assertGreater(small, 0.2)   # with 30 vs 100 docs a 20 % skill must more than double
        self.assertLess(large, 0.1)
        self.assertLess(large, small)


class WeightingAndMatchingTests(unittest.TestCase):
    def test_post_stratified_rate_equalises_mix(self):
        # cell b is 80 % senior; seniors mention the skill 50 %, juniors 10 %.
        ind = [1] * 40 + [0] * 40 + [1] * 2 + [0] * 18
        strata = ["senior"] * 80 + ["junior"] * 20
        raw = sum(ind) / len(ind)
        weighted, coverage = stats.post_stratified_rate(ind, strata, {"senior": 0.5, "junior": 0.5})
        self.assertAlmostEqual(raw, 0.42)
        self.assertAlmostEqual(weighted, 0.30)   # 0.5*0.5 + 0.5*0.1
        self.assertEqual(coverage, 1.0)

    def test_post_stratified_rate_reports_missing_strata(self):
        weighted, coverage = stats.post_stratified_rate([1, 0], ["a", "a"], {"a": 0.6, "b": 0.4})
        self.assertAlmostEqual(weighted, 0.5); self.assertAlmostEqual(coverage, 0.6)
        self.assertTrue(math.isnan(stats.post_stratified_rate([1], ["a"], {"b": 1.0})[0]))
        with self.assertRaises(ValueError):
            stats.post_stratified_rate([1, 0], ["a"], {"a": 1.0})

    def test_strata_shares(self):
        self.assertEqual(stats.strata_shares(["a", "a", "b", "c"]), {"a": 0.5, "b": 0.25, "c": 0.25})
        self.assertEqual(stats.strata_shares([]), {})

    def test_size_matched_replication_is_deterministic_and_sensible(self):
        small = [0] * 16 + [1] * 4
        large = [0] * 200 + [1] * 800     # 80 % vs 20 %: a real difference
        r1 = stats.size_matched_replication(small, large, n_rep=100, seed=3)
        r2 = stats.size_matched_replication(small, large, n_rep=100, seed=3)
        self.assertEqual(r1, r2)
        med, share_sig, share_sign = r1
        self.assertGreater(med, 0.4); self.assertGreater(share_sig, 0.8); self.assertGreater(share_sign, 0.95)
        none = stats.size_matched_replication([0] * 5 + [1] * 5, [0] * 500 + [1] * 500, n_rep=50, seed=0)
        self.assertLess(none[1], 0.3)        # no real difference: rarely significant
        with self.assertRaises(ValueError):
            stats.size_matched_replication([], [1])


if __name__ == "__main__":
    unittest.main()
