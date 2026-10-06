"""report/index.html: the embedded data must equal the results files, and the page must be self-contained and accessible."""
import csv
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_report as br  # noqa: E402

RESULTS = ROOT / "results"
PAGE = ROOT / "report" / "index.html"
TEMPLATE = ROOT / "scripts" / "report_template.html"
# Fixed numbers that are definitions, not results: the confidence level, the 20 % example rate (the key of the power table), the "per 1,000 characters" unit.
ALLOWED_TYPED = ("95 %", "20 %", "1,000")


def rows(name):
    with (RESULTS / name).open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def embedded(html: str) -> dict:
    m = re.search(r'<script type="application/json" id="report-data">(.*?)</script>', html, re.S)
    assert m, "no embedded data"
    return json.loads(m.group(1))


class DataMatchesResultsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = PAGE.read_text(encoding="utf-8")
        cls.data = embedded(cls.html)

    def test_page_is_up_to_date_with_the_builder(self):
        self.assertEqual(self.html, br.render(br.build_data(RESULTS)), "run: python scripts/build_report.py")

    def test_prevalence_every_cell_and_skill(self):
        seen = 0
        for r in rows("skill_prevalence_by_cell.csv"):
            k, rate, lo, hi = self.data["prev"][r["cell"]][r["skill_id"]]
            self.assertEqual((k, rate, lo, hi), (int(r["k"]), float(r["rate"]), float(r["wilson_low"]), float(r["wilson_high"])), (r["cell"], r["skill_id"]))
            self.assertEqual(self.data["cells"][r["cell"]]["n"], int(r["n_docs"]))
            seen += 1
        self.assertEqual(seen, 6 * 92)

    def test_panel_rows_every_skill(self):
        for panel in br.PANELS:
            csv_rows = rows(f"skill_shift_{panel}.csv")
            self.assertEqual(len(self.data["panels"][panel]["rows"]), len(csv_rows))
            for r in csv_rows:
                got = self.data["panels"][panel]["rows"][r["skill_id"]]
                lo_a, hi_a = (float(x) for x in r["wilson_a"].split("-"))
                lo_b, hi_b = (float(x) for x in r["wilson_b"].split("-"))
                self.assertEqual(got[0:3], [float(r["rate_a"]), lo_a, hi_a], (panel, r["skill_id"]))
                self.assertEqual(got[3:6], [float(r["rate_b"]), lo_b, hi_b], (panel, r["skill_id"]))
                self.assertEqual(got[6], float(r["risk_difference_pp"]))
                self.assertEqual(got[9], float(r["weighted_rd_pp"]) if r["weighted_rd_pp"] else None)
                self.assertAlmostEqual(got[10], float(r["bh_q"]), delta=abs(float(r["bh_q"])) * 1e-9)
                self.assertEqual(got[11], 1 if r["significant_q10"] == "True" else 0)
                self.assertEqual(got[12], float(r["size_matched_share_p_lt_05"]))
            self.assertEqual((self.data["panels"][panel]["n_a"], self.data["panels"][panel]["n_b"]), (int(csv_rows[0]["n_a"]), int(csv_rows[0]["n_b"])))

    def test_power_trend_requirements(self):
        for r in rows("power_check.csv"):
            self.assertEqual(self.data["panels"][r["panel"]]["mde"][r["base_rate_a"]], float(r["min_detectable_increase_pp"]))
        trend = rows("tinix_vn_yearly_trend.csv")
        T = self.data["trend"]
        for sid, series in T["series"].items():
            for year, value in zip(T["years"], series):
                want = [float(r["rate"]) for r in trend if r["skill_id"] == sid and r["cell"] == year]
                self.assertEqual([value], want, (sid, year))
        for year, n in zip(T["years"], T["n"]):
            self.assertEqual(n, int(next(r for r in trend if r["cell"] == year)["n_docs"]))
        for key, per_cell in self.data["requirements"].items():
            field, value = key.split(":")
            for cell, got in per_cell.items():
                want = [float(r["rate"]) for r in rows("requirements_by_cell.csv") if r["cell"] == cell and r["field"] == field and r["value"] == value]
                self.assertEqual([got], want or [None], (key, cell))  # a value that never occurs has no row

    def test_themes_words_and_same_instrument(self):
        for T in self.data["themes"]:
            for it in T["items"]:
                src = next(r for r in rows(f"themes_{T['language']}_{T['panel']}.csv") if int(r["theme"]) == it["id"])
                self.assertEqual((it["share_a"], it["share_b"], it["stability"]), (float(src[f"share_dominant_{T['a']}"]), float(src[f"share_dominant_{T['b']}"]), float(src["stability_cosine"])))
                if it["terms"]:
                    self.assertEqual(it["terms"], src["top_terms"].split(" | ")[: len(it["terms"])])
        words = rows("word_log_odds_by_panel.csv")
        total = 0
        for W in self.data["words"]:
            for side in ("more_a", "more_b"):
                for w in W[side]:
                    src = next(r for r in words if r["panel"] == W["panel"] and r["language"] == W["language"] and r["term"] == w["term"])
                    self.assertEqual((w["docs_a"], w["docs_b"], w["z"]), (int(src["docs_a"]), int(src["docs_b"]), float(src["z"])))
                    total += 1
        self.assertGreater(total, 30)
        shared = {r["keyword"]: r for r in rows("us_same_instrument_skills.csv")}
        for r in self.data["same_instrument"]["shared"]:
            self.assertEqual((r["r22"], r["r26"], r["diff_pp"]), (float(shared[r["keyword"]]["rate_2022"]), float(shared[r["keyword"]]["rate_2026"]), float(shared[r["keyword"]]["risk_difference_pp"])))

    def test_platform_share_note_traces_to_corpus_summary(self):
        for r in rows("corpus_summary.csv"):
            if r["source"] == "tinix_vn":
                got = self.data["platform_share"][r["era"]]
                self.assertEqual((got["n"], got["total"]), (int(r["n_da_family"]), int(r["platform_total_postings_that_year"])))
                self.assertAlmostEqual(got["share"], int(r["n_da_family"]) / int(r["platform_total_postings_that_year"]), places=6)
        ratio = self.data["platform_share"]["2026"]["share"] / self.data["platform_share"]["2025"]["share"]
        self.assertIn(f"{ratio:.1f} times more", self.html)
        self.assertIn(f"{100 * self.data['platform_share']['2026']['share']:.3f} %", self.html)

    def test_limits_box_numbers_trace_to_results(self):
        """The box under the title: every number in it is read from the results files."""
        box = re.search(r'<aside class="limits".*?</aside>', self.html, re.S)
        self.assertIsNotNone(box, "no limits box")
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", box.group(0)))
        self.assertIn("Read this first: limits and risks", text)
        cells = {r["cell"]: int(r["n_docs"]) for r in rows("skill_prevalence_by_cell.csv")}
        want = f"United States: {cells['US_2022']:,} postings in 2022 and {cells['US_2026']:,} in 2026. Vietnam: {cells['VN_2022']:,} in 2022 and {cells['VN_2026']:,} in 2026."
        self.assertIn(want, text)
        share = {r["era"]: int(r["n_da_family"]) / int(r["platform_total_postings_that_year"]) for r in rows("corpus_summary.csv") if r["source"] == "tinix_vn"}
        self.assertIn(f"rose {share['2026'] / share['2025']:.1f} times from 2025 to 2026", text)
        # the "q-value above 0.10" rule is the one the results files use
        for panel in br.PANELS:
            for r in rows(f"skill_shift_{panel}.csv"):
                self.assertEqual(float(r["bh_q"]) <= 0.10, r["significant_q10"] == "True", (panel, r["skill_id"]))
        self.assertIn("q-value above 0.10", text)
        # periods: the US 2022 sample months come from the same-pipeline check metadata
        self.assertEqual(json.loads((RESULTS / "us_same_instrument_meta.json").read_text(encoding="utf-8"))["us_2022"]["months"], ["2022-11", "2022-12"])
        self.assertIn("November to December", text)
        self.assertIn("whole year", text)
        for needed in ("not national statistics", "Mentions, not requirements", "not peer reviewed", "CC BY-NC 4.0", "non-commercial"):
            self.assertIn(needed.lower(), text.lower(), needed)

    def test_limits_box_comes_first(self):
        """Directly under the title and before any chart, section or script."""
        h = self.html
        pos = {k: h.index(k) for k in ('<h1', '<aside class="limits"', '<nav class="jump"', '<section id="shifts"', 'id="headline-cards"', '<script')}
        self.assertEqual(sorted(pos, key=pos.get), ['<h1', '<aside class="limits"', '<nav class="jump"', '<section id="shifts"', 'id="headline-cards"', '<script'])
        between = h[pos["<h1"]:pos['<aside class="limits"']]
        self.assertEqual(re.sub(r"<[^>]+>|How the Data Analyst job changed, 2022 to 2026", "", between).strip(), "")

    def test_footer_names_the_repository(self):
        footer = re.search(r"<footer>.*?</footer>", self.html, re.S).group(0)
        self.assertIn(">analysis-da-job-shift</a>", footer)
        self.assertIn(">my-fork</a>", br.render(br.build_data(RESULTS), "https://github.com/someone/my-fork"))

    def test_only_published_theme_tables_are_used(self):
        self.assertEqual([t["language"] for t in self.data["themes"]], ["en"])
        self.assertNotIn("themes_vi", self.html)

    def test_headline_numbers_trace_to_panel_rows(self):
        self.assertEqual(len(self.data["headlines"]), 5)
        for h in self.data["headlines"]:
            for s in h["stats"]:
                row = next(r for r in rows(f"skill_shift_{s['panel']}.csv") if r["skill_id"] == s["skill"])
                self.assertEqual((s["a"], s["b"], s["diff_pp"]), (float(row["rate_a"]), float(row["rate_b"]), float(row["risk_difference_pp"])))
                self.assertEqual(s["sig"], 1 if row["significant_q10"] == "True" else 0)

    def test_prose_numbers_are_looked_up_not_typed(self):
        d = self.data
        self.assertIn(f"{d['cells']['VN_2022']['n']:,} postings ({d['cells']['VN_platform_2022']['n']:,} from one platform)", self.html)
        mde = d["panels"]["P2_vn_2022_vs_2026"]["mde"]["0.2"]
        self.assertIn(f"by about {mde:.0f} points", self.html)
        self.assertNotIn("{{", self.html)
        template = TEMPLATE.read_text(encoding="utf-8")
        body = re.sub(r"<style>.*?</style>|<script.*?</script>", "", template, flags=re.S)
        typed = [m for m in re.findall(r"\d[\d,.]*\s?%|\b\d{1,3},\d{3}\b", body) if m.strip() not in ALLOWED_TYPED]
        self.assertEqual(typed, [], "numbers in the page text must come from {{...}} fills")

    def test_no_posting_text_only_short_strings(self):
        def strings(o):
            if isinstance(o, str):
                yield o
            elif isinstance(o, dict):
                for v in o.values():
                    yield from strings(v)
            elif isinstance(o, list):
                for v in o:
                    yield from strings(v)
        self.assertLess(max(len(s) for s in strings(self.data)), 200)


class PageQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = PAGE.read_text(encoding="utf-8")

    def test_self_contained(self):
        self.assertNotRegex(self.html, r"(?i)<script[^>]+\bsrc\s*=|<link\b|@import|url\(\s*[\"']?(?:https?:)?//|<iframe|<img[^>]+src\s*=\s*[\"']?https?:")
        self.assertLess(len(self.html.encode("utf-8")), 400_000)
        for url in re.findall(r"""(?:src|href)\s*=\s*["'](https?://[^"']+)""", self.html):
            pass  # links are allowed
        self.assertEqual(re.findall(r"<script\b[^>]*\bsrc=", self.html), [])

    def test_accessibility_basics(self):
        h = self.html
        self.assertIn('<html lang="en">', h)
        self.assertEqual(len(re.findall(r"<h1\b", h)), 1)
        for needle in ('class="skip"', "<main", '<nav class="jump" aria-label', "aria-live", ":focus-visible", "prefers-color-scheme:dark", 'name="viewport"', 'name="color-scheme"', "@media (max-width:640px)", "<noscript>"):
            self.assertIn(needle, h)
        for ident in re.findall(r"<select id=\"(\w+)\"", h):
            self.assertRegex(h, rf'<label for="{ident}"')
        self.assertEqual(len(re.findall(r"<input\b", h)), len(re.findall(r"<label[^>]*>\s*<input\b", h)), "every input sits inside its label")
        self.assertIn("aria-sort", h)
        self.assertIn("aria-pressed", h)

    def test_wording_rules(self):
        # visible text only: the data block holds skill labels such as "Web scraping / crawling", which are skills, not sources
        text = re.sub(r"<[^>]+>", " ", re.sub(r"<script.*?</script>|<style.*?</style>", "", self.html, flags=re.S))
        for banned in ("Mother" + "Duck", "scra" + "ped", "cra" + "wl", "no licence text", "my plain", "I could not", "Late 2022", "late 2022", "ask for", "English required"):
            self.assertNotIn(banned.lower(), text.lower(), banned)
        for needed in ("publicly available job postings", "Non-commercial note", "CC BY-NC 4.0", "whole year"):
            self.assertIn(needed, text)
        self.assertIn("Fluent English mentioned", self.html)  # built by the page script
        sources = " ".join(s["what"] + " " + s.get("cite", "") for s in embedded(self.html)["sources"])
        for needed in ("CareerPathKG", "10.18653/v1/2026.eacl-industry.60"):
            self.assertIn(needed, sources)

    def test_limits_box_is_readable_in_both_themes_and_on_phones(self):
        css = re.search(r"<style>(.*?)</style>", self.html, re.S).group(1)

        def lum(hexcolor):
            rgb = [int(hexcolor[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
            return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]

        def ratio(a, b):
            la, lb = sorted((lum(a), lum(b)), reverse=True)
            return (la + 0.05) / (lb + 0.05)

        for scope in (r":root\{(.*?)\}", r':root\[data-theme="dark"\]\{(.*?)\}'):
            block = re.search(scope, css, re.S).group(1)
            tok = dict(re.findall(r"--(\w+):(#[0-9a-fA-F]{6})", block))
            self.assertGreaterEqual(ratio(tok["text"], tok["warnbg"]), 7, scope)   # text on the box: AAA
            self.assertGreaterEqual(ratio(tok["warnline"], tok["bg"]), 3, scope)    # border against the page: 3:1
        self.assertRegex(css, r"\.limits ul\{[^}]*grid-template-columns:repeat\(auto-fit,minmax\(17rem,1fr\)\)")  # one column on a phone

    def test_unglossed_vietnamese_words_are_not_shown(self):
        data = embedded(self.html)
        for W in data["words"]:
            for side in ("more_a", "more_b"):
                for w in W[side]:
                    if br.VI_LETTERS.search(w["term"]):
                        self.assertTrue(w["gloss"], w["term"])

    def test_explains_what_the_audience_needs(self):
        text = re.sub(r"<[^>]+>", " ", self.html)
        for needle in ("Mentions are not requirements", "upper bound", "Cell sizes", "small", "Method in plain words", "Limits", "Next: stage 2", "stage 2", "Code and data sources", "No cookies, no tracking"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
