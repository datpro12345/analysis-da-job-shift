"""The stage 2 schema and the committed results must stay consistent and free of personal data."""
import csv
import json
import re
import sys
import unittest
from pathlib import Path

LAB = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(LAB / "src"))
import common  # noqa: E402

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"(?<!\d)(?:\+84|0)[\s.-]?(?:\d[\s.-]?){8,9}\d(?!\d)")


class SchemaTests(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads((LAB / "schema" / "jd_annotation.schema.json").read_text(encoding="utf-8"))

    def test_required_fields_present(self):
        for field in ("tasks", "ai_roles", "skills", "soft_skills", "seniority", "years_experience", "degree", "languages", "work_mode", "salary", "role_family"):
            self.assertIn(field, self.schema["properties"])
            self.assertIn(field, self.schema["required"])

    def test_ai_role_categories(self):
        cats = self.schema["properties"]["ai_roles"]["items"]["properties"]["category"]["enum"]
        for c in ("ai_as_analyst_tool", "ai_as_product_team_builds", "ai_governance_ethics_risk"):
            self.assertIn(c, cats)

    def test_every_judgement_carries_evidence(self):
        props = self.schema["properties"]
        for field in ("tasks", "ai_roles", "skills", "soft_skills", "languages"):
            self.assertIn("evidence", props[field]["items"]["required"], field)
        for field in ("seniority", "years_experience", "degree", "work_mode", "salary", "role_family"):
            self.assertIn("evidence", props[field]["required"], field)
        self.assertLessEqual(self.schema["$defs"]["evidence"]["properties"]["quote"]["maxLength"], 300)

    def test_guide_mentions_kappa_and_validation(self):
        guide = (LAB / "docs" / "ANNOTATION_GUIDE.md").read_text(encoding="utf-8")
        for needle in ("Cohen's kappa", "validate_annotations.py", "verbatim", "ai_as_analyst_tool"):
            self.assertIn(needle, guide)


class ResultsHygieneTests(unittest.TestCase):
    """Committed results are aggregates: no e-mails, phones, or free text columns."""

    def test_results_have_no_personal_data(self):
        results = LAB / "results"
        if not results.exists():
            self.skipTest("results not built yet")
        for path in results.rglob("*"):
            if path.suffix not in (".csv", ".json", ".md"):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            self.assertIsNone(EMAIL.search(text), path.name)
            self.assertIsNone(PHONE.search(text), path.name)

    def test_prevalence_csv_is_aggregate_only(self):
        path = LAB / "results" / "skill_prevalence_by_cell.csv"
        if not path.exists():
            self.skipTest("results not built yet")
        with path.open(encoding="utf-8") as fh:
            header = next(csv.reader(fh))
        self.assertNotIn("text", header); self.assertNotIn("doc_id", header)
        for col in ("panel", "cell", "skill_id", "n_docs", "k", "rate", "wilson_low", "wilson_high"):
            self.assertIn(col, header)

    def test_word_tables_only_contain_terms_seen_in_three_documents(self):
        path = LAB / "results" / "word_log_odds_by_panel.csv"
        if not path.exists():
            self.skipTest("results not built yet")
        with path.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                self.assertGreaterEqual(int(row["docs_a"]) + int(row["docs_b"]), 3, row["term"])


class DocsTests(unittest.TestCase):
    def test_docs_have_no_unfilled_placeholders_or_personal_data(self):
        for name in ("README.md", "DATA_SOURCES.md", "docs/BRD.md", "docs/TDD.md", "docs/ANNOTATION_GUIDE.md"):
            if not (LAB / name).exists():
                continue
            text = (LAB / name).read_text(encoding="utf-8")
            self.assertNotIn("{{", text, f"{name}: unfilled placeholder")
            self.assertIsNone(EMAIL.search(text), name)
            self.assertIsNone(PHONE.search(text), name)

    def test_readme_names_every_script(self):
        readme = (LAB / "README.md").read_text(encoding="utf-8")
        for script in sorted(p.name for p in (LAB / "src").glob("*.py")):
            self.assertIn(script, readme, script)


class WordingAndLicenceTests(unittest.TestCase):
    """Source wording, credits and licences must say the same thing everywhere."""
    FILES = ("README.md", "DATA_SOURCES.md", "docs/BRD.md", "docs/TDD.md", "docs/PUBLISHING.md", "scripts/report_template.html", "scripts/build_report.py", "report/index.html")

    def test_source_wording(self):
        for name in self.FILES:
            text = (LAB / name).read_text(encoding="utf-8")
            text = re.sub(r"<script.*?</script>", "", text, flags=re.S).lower()  # the page's data block holds skill labels, not source wording
            for banned in ("mother" + "duck", "scra" + "ped", "cra" + "wled", "no licence text", "no terms"):
                self.assertNotIn(banned, text, f"{name}: {banned}")

    def test_licences_say_the_same_everywhere(self):
        for name in ("LICENSE", "README.md", "DATA_SOURCES.md", "report/index.html", "results/README.md"):
            text = (LAB / name).read_text(encoding="utf-8")
            self.assertIn("CC BY-NC 4.0", text, name)
            self.assertIn("on-commercial", text, name)
        for name in ("LICENSE", "README.md", "report/index.html"):
            text = (LAB / name).read_text(encoding="utf-8")
            self.assertIn("MIT", text, name)
            self.assertIn("CC BY 4.0", text, name)

    def test_tinix_citation_is_present_where_credits_are_given(self):
        for name in ("README.md", "DATA_SOURCES.md", "report/index.html"):
            text = (LAB / name).read_text(encoding="utf-8")
            for needle in ("CareerPathKG", "EACL 2026 Industry Track", "10.18653/v1/2026.eacl-industry.60"):
                self.assertIn(needle, text, f"{name}: {needle}")

    def test_vietnamese_theme_tables_are_not_published(self):
        import subprocess
        tracked = subprocess.run(["git", "-C", str(LAB), "ls-files", "results"], capture_output=True, text=True).stdout.split()
        self.assertEqual([f for f in tracked if "themes_vi" in f], [])
        self.assertIn("results/themes_vi_*.csv", (LAB / ".gitignore").read_text(encoding="utf-8"))


class DataRootTests(unittest.TestCase):
    def test_fallback_is_the_gitignored_data_folder(self):
        import os
        old = os.environ.pop(common.DATA_ENV_VAR, None)
        try:
            self.assertEqual(common.data_root(None), common.REPO_ROOT / "data")
            self.assertEqual(common.data_root("/tmp/x"), Path("/tmp/x").resolve())
            os.environ[common.DATA_ENV_VAR] = "/tmp/y"
            self.assertEqual(common.data_root(None), Path("/tmp/y").resolve())
            self.assertEqual(common.raw_dir(Path("/r")), Path("/r/raw"))
            self.assertEqual(common.corpus_dir(Path("/r")), Path("/r/corpus"))
        finally:
            os.environ.pop(common.DATA_ENV_VAR, None)
            if old is not None:
                os.environ[common.DATA_ENV_VAR] = old

    def test_gitignore_keeps_data_out(self):
        text = (LAB / ".gitignore").read_text(encoding="utf-8").splitlines()
        for entry in ("data/", "raw/", "corpus/", ".venv/"):
            self.assertIn(entry, text)


if __name__ == "__main__":
    unittest.main()
