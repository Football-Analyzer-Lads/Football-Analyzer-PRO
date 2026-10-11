"""Regression tests for internally consistent football market probabilities.

The app assembles its source chunks at runtime, so import only the numerical
functions needed by these tests from the assembled source AST. No API calls.
"""
import ast
import math
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARTS = sorted(ROOT.glob("app_source_*.py"))
SOURCE = "\n".join(p.read_text(encoding="utf-8").rstrip("\n") for p in PARTS) + "\n"
TREE = ast.parse(SOURCE)
NEEDED = {"pois", "score_matrix", "markets", "_poisson_tail_over", "_count_market_prob"}
FUNCTIONS = {
    node.name: node
    for node in ast.walk(TREE)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in NEEDED
}
if FUNCTIONS.keys() != NEEDED:
    raise RuntimeError(f"Missing numerical model functions: {NEEDED - FUNCTIONS.keys()}")

module = ast.Module(
    body=[ast.Import(names=[ast.alias(name="math")])]
    + [FUNCTIONS[name] for name in ("pois", "score_matrix", "markets", "_poisson_tail_over", "_count_market_prob")],
    type_ignores=[],
)
ast.fix_missing_locations(module)
NS = {}
exec(compile(module, "market_math.py", "exec"), NS)
score_matrix = NS["score_matrix"]
markets = NS["markets"]
count_market_prob = NS["_count_market_prob"]


class MarketProbabilityTests(unittest.TestCase):
    def test_home_and_away_multigoal_use_the_correct_marginal(self):
        home_xg, away_xg = 2.4, 0.65
        matrix = score_matrix(home_xg, away_xg)
        p = markets(home_xg, away_xg)
        expected_home = sum(sum(matrix[g]) for g in range(2, 5))
        expected_away = sum(sum(matrix[h][g] for h in range(len(matrix))) for g in range(2, 5))
        self.assertAlmostEqual(p["MGH2-4"], expected_home, places=10)
        self.assertAlmostEqual(p["MGA2-4"], expected_away, places=10)
        self.assertGreater(p["MGH2-4"], p["MGA2-4"])

    def test_swapping_expected_goals_swaps_home_and_away_multigoal(self):
        p_home_strong = markets(2.5, 0.6)
        p_away_strong = markets(0.6, 2.5)
        self.assertAlmostEqual(p_home_strong["MGH2-4"], p_away_strong["MGA2-4"], places=10)
        self.assertAlmostEqual(p_home_strong["MGA2-4"], p_away_strong["MGH2-4"], places=10)

    def test_probability_partitions_sum_to_one(self):
        for home_xg, away_xg in ((0.4, 0.7), (1.25, 1.1), (2.4, 0.65), (4.5, 4.0)):
            with self.subTest(home_xg=home_xg, away_xg=away_xg):
                p = markets(home_xg, away_xg)
                self.assertAlmostEqual(p["1"] + p["X"] + p["2"], 1.0, places=9)
                self.assertAlmostEqual(p["GG"] + p["NG"], 1.0, places=9)
                self.assertAlmostEqual(p["O2.5"] + p["U2.5"], 1.0, places=9)
                self.assertTrue(all(0.0 <= v <= 1.0 for v in p.values()))

    def test_shot_volume_probabilities_are_complements_and_monotone(self):
        for mean in (4.5, 13.0, 22.5, 30.0):
            for line in (8.5, 15.5, 22.5, 30.5):
                over = count_market_prob(mean, line, True)
                under = count_market_prob(mean, line, False)
                self.assertTrue(0.0 <= over <= 1.0)
                self.assertTrue(0.0 <= under <= 1.0)
                self.assertAlmostEqual(over + under, 1.0, places=10)
            self.assertGreaterEqual(count_market_prob(mean, 10.5, True),
                                    count_market_prob(mean, 20.5, True))
            self.assertGreaterEqual(count_market_prob(mean, 30.5, False),
                                    count_market_prob(mean, 20.5, False))

    def test_goal_over_probabilities_are_monotone(self):
        p = markets(1.7, 1.15)
        self.assertGreaterEqual(p["O1.5"], p["O2.5"])
        self.assertGreaterEqual(p["O2.5"], p["O3.5"])


if __name__ == "__main__":
    unittest.main()
