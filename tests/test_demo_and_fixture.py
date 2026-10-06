"""The synthetic fixture and the demo run: no downloads, no network."""
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))
import make_synthetic  # noqa: E402
import run_demo  # noqa: E402


class FixtureTests(unittest.TestCase):
    def test_committed_fixture_matches_the_generator(self):
        self.assertEqual(make_synthetic.DEFAULT_OUT.read_text(encoding="utf-8"), make_synthetic.render())

    def test_every_document_is_clearly_fictional_and_short(self):
        docs = [json.loads(line) for line in make_synthetic.DEFAULT_OUT.read_text(encoding="utf-8").splitlines()]
        self.assertGreater(len(docs), 200)
        for d in docs:
            self.assertTrue(d["text"].startswith("SYNTHETIC EXAMPLE."))
            self.assertTrue(d["company"].startswith("Example Corp"))
            self.assertLess(len(d["text"]), 400)
            self.assertEqual(d["url"], "")

    def test_fixture_covers_every_cell(self):
        import extract_deterministic as ed  # noqa: E402
        docs = [json.loads(line) for line in make_synthetic.DEFAULT_OUT.read_text(encoding="utf-8").splitlines()]
        for cell, pred in ed.CELLS.items():
            self.assertGreaterEqual(sum(bool(pred(d)) for d in docs), 20, cell)


class DemoTests(unittest.TestCase):
    def test_demo_runs_end_to_end_on_synthetic_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = run_demo.run(Path(tmp), quiet=True)
            names = {p.name for p in results.iterdir()}
            for needed in ("skill_prevalence_by_cell.csv", "skill_shift_P1_us_2022_vs_2026.csv", "word_log_odds_by_panel.csv", "power_check.csv", "panels.json", "figures"):
                self.assertIn(needed, names)
            with (results / "skill_shift_P1_us_2022_vs_2026.csv").open(encoding="utf-8") as fh:
                rows = {r["skill_id"]: r for r in csv.DictReader(fh)}
            # the invented AI mention jumps from about 4 % to about 40 %
            self.assertGreater(float(rows["any_ai"]["risk_difference_pp"]), 20)
            self.assertEqual(rows["any_ai"]["significant_q10"], "True")
            self.assertTrue(any(p.name.startswith("themes_en_P1") for p in results.iterdir()))


if __name__ == "__main__":
    unittest.main()
