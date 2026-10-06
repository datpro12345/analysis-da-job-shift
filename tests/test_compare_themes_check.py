"""compare_eras, themes and us_instrument_check on tiny fictional inputs."""
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import common  # noqa: E402
import compare_eras as ce  # noqa: E402
import extract_deterministic as ed  # noqa: E402
import themes  # noqa: E402
import us_instrument_check as uic  # noqa: E402

TAX = common.load_taxonomy()


def prev_rows(cell, rows):
    return ed.prevalence_rows(rows, TAX, "cells", cell)


def fake_rows(n, sql_k, source):
    """Document-level rows (as read back from extracted.csv: strings) with `sql_k` of n mentioning SQL."""
    base = {s["id"]: "False" for s in TAX["skills"]}
    out = []
    for i in range(n):
        r = {"source": source, "era": "2022", "region": "US", "seniority": "senior" if i % 2 else "unspecified", "da_family": "True", "any_ai": "False",
             **{f"skill__{k}": v for k, v in base.items()}}
        r["skill__sql"] = "True" if i < sql_k else "False"
        out.append(r)
    return out


class CompareTests(unittest.TestCase):
    def test_skill_comparison_rows_and_columns(self):
        a, b = fake_rows(40, 10, "gsearch_us_2022"), fake_rows(60, 45, "us_open_2026")
        prev = [{k: str(v) for k, v in r.items()} for r in prev_rows("US_2022", [{**r, "any_ai": False, **{k: v == "True" for k, v in r.items() if k.startswith("skill__")}} for r in a])]
        prev += [{k: str(v) for k, v in r.items()} for r in prev_rows("US_2026", [{**r, "any_ai": False, **{k: v == "True" for k, v in r.items() if k.startswith("skill__")}} for r in b])]
        rows = ce.skill_comparison(prev, a + b, "P1", ed.PANELS["P1_us_2022_vs_2026"], TAX)
        sql = next(r for r in rows if r["skill_id"] == "sql")
        self.assertEqual((sql["k_a"], sql["n_a"], sql["k_b"], sql["n_b"]), (10, 40, 45, 60))
        self.assertEqual(sql["risk_difference_pp"], 50.0)
        self.assertEqual(sql["significant_q10"], True)
        self.assertEqual(rows[0]["skill_id"], "sql")          # sorted by q, the real change first
        self.assertTrue(all(0 <= float(r["bh_q"]) <= 1 for r in rows))

    def test_power_rows_three_base_rates_per_panel_and_skips_empty(self):
        rows = ce.power_rows({"X": {"a": "A", "b": "B", "n_a": 100, "n_b": 100}, "Y": {"a": "A", "b": "B", "n_a": 0, "n_b": 5}})
        self.assertEqual([r["base_rate_a"] for r in rows], [0.05, 0.2, 0.5])
        self.assertTrue(all(r["panel"] == "X" for r in rows))

    def test_word_log_odds_ranks_the_distinctive_word(self):
        def doc(source, era, text):
            return {"source": source, "era": era, "da_family": True, "language": "en", "title": "Data Analyst", "text": text, "region": "US"}
        corpus = [doc("gsearch_us_2022", "2022", "analyst remote covid reports") for _ in range(8)] + [doc("us_open_2026", "2026", "analyst generative copilot reports") for _ in range(8)]
        rows = ce.word_log_odds(corpus, ed.PANELS["P1_us_2022_vs_2026"], "P1")
        newer = [r["term"] for r in rows if r["side"] == "more_in_US_2026"]
        older = [r["term"] for r in rows if r["side"] == "more_in_US_2022"]
        self.assertIn("copilot", newer)
        self.assertIn("covid", older)
        self.assertTrue(all(int(r["docs_a"]) + int(r["docs_b"]) >= ce.MIN_DF_WORDS for r in rows))


class ThemeTests(unittest.TestCase):
    def test_tokenize_keeps_letters_only_lowercase_unicode(self):
        self.assertEqual(themes.tokenize("SQL 2022, Power-BI và Phân tích"), ["sql", "power", "bi", "và", "phân", "tích"])

    def test_stability_is_one_for_identical_fits_and_lower_for_different(self):
        comp = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
        for score in themes.stability([comp, comp.copy()]):
            self.assertAlmostEqual(score, 1.0, places=6)
        other = np.array([[1.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
        self.assertLess(min(themes.stability([comp, other])), 1.0)

    def test_run_language_skips_tiny_input_and_writes_files_otherwise(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            themes.run_language([{"title": "x", "text": "y", "cell": "A"}] * 3, "en", 4, out)
            self.assertEqual(list(out.iterdir()), [])
            docs = [{"title": "Data Analyst", "text": f"sql dashboards report {w} {w} finance {w}", "cell": "A" if i % 2 else "B"}
                    for i, w in enumerate(["alpha", "beta", "gamma", "delta"] * 8)]
            themes.run_language(docs, "en", 2, out, suffix="_T")
            self.assertTrue((out / "themes_en_T.csv").exists() and (out / "themes_en_T_stability.csv").exists())


class UsInstrumentTests(unittest.TestCase):
    def test_load_2022_reads_tokens_and_filters_family_and_year(self):
        import pandas as pd

        rows = [
            {"job_id": "a", "title": "Data Analyst", "date_time": "2022-11-05", "description_tokens": "['sql', 'Excel']"},
            {"job_id": "a", "title": "Data Analyst", "date_time": "2022-11-05", "description_tokens": "['sql']"},      # same job id twice
            {"job_id": "b", "title": "Data Engineer", "date_time": "2022-11-05", "description_tokens": "['sql']"},     # outside the family
            {"job_id": "c", "title": "Data Analyst", "date_time": "2023-01-05", "description_tokens": "['sql']"},      # other year
            {"job_id": "d", "title": "BI Analyst", "date_time": "2022-12-01", "description_tokens": "not a list"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "g.csv"
            pd.DataFrame(rows).to_csv(path, index=False)
            docs, meta = uic.load_2022(path)
        self.assertEqual(docs, [{"sql", "excel"}, set()])
        self.assertEqual((meta["n_docs"], meta["months"]), (2, ["2022-11", "2022-12"]))

    def test_load_2026_joins_skills_and_keeps_us_rows(self):
        import pandas as pd

        postings = pd.DataFrame([
            {"job_id": "x1", "job_title": "Data Analyst", "search_location": "Springfield, United States", "search_date": "2026-02-01", "error": False},
            {"job_id": "x2", "job_title": "Data Analyst", "search_location": "Paris, France", "search_date": "2026-02-01", "error": False},
            {"job_id": "x3", "job_title": "Data Analyst", "search_location": "Austin, United States", "search_date": "2026-03-01", "error": True},
        ])
        skills = pd.DataFrame([{"job_id": "x1", "skill_keyword": "SQL"}, {"job_id": "x1", "skill_keyword": "python"}, {"job_id": "x2", "skill_keyword": "sql"}])
        with tempfile.TemporaryDirectory() as tmp:
            postings.to_parquet(Path(tmp) / "raw_job_postings_2026-02.parquet")
            skills.to_parquet(Path(tmp) / "raw_job_skills.parquet")
            docs, meta = uic.load_2026(Path(tmp))
        self.assertEqual(docs, [{"sql", "python"}])
        self.assertEqual((meta["n_docs"], meta["months"]), (1, ["2026-02"]))


if __name__ == "__main__":
    unittest.main()
