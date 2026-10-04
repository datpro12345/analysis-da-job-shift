"""Tests for the cleaning helpers, role-family rule, taxonomy and deterministic extraction."""
import sys
import unicodedata
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import common  # noqa: E402
import extract_deterministic as ed  # noqa: E402

TAX = common.load_taxonomy()


def hits(skill_id: str, text: str) -> bool:
    return ed.skill_flags(common.normalize_text(text), TAX)[skill_id]


class CleaningTests(unittest.TestCase):
    def test_nfc_normalisation_fixes_word_boundaries(self):
        nfd = unicodedata.normalize("NFD", "thiết bị")
        self.assertNotEqual(nfd, "thiết bị")
        self.assertEqual(common.normalize_text(nfd), "thiết bị")
        self.assertFalse(hits("bi_generic", nfd))

    def test_personal_data_is_stripped(self):
        # fictional values only (built from parts so the repository scan finds no phone-like literal)
        fake, fake2 = "09" + "00 000 000", "09" + "00000001"
        text = f"Contact for detailed JD. Zalo: {fake} (Ms. Sample)\nEmail: someone@example.com\nPhone: {fake2}\nSalary 45,000,000 VND, 5+ years"
        out = common.strip_personal_data(text)
        for forbidden in ("09" + "00", "Sample", "example.com", fake2):
            self.assertNotIn(forbidden, out)
        self.assertIn("45,000,000 VND", out)
        self.assertIn("5+ years", out)

    def test_international_phone_stripped_years_kept(self):
        out = common.strip_personal_data("Call +84 " + "900 000 000" + " or +1 " + "555 000 " + "0000" + ". Founded 2013, 3 years exp.")
        self.assertNotIn("900 000", out); self.assertNotIn("555", out)
        self.assertIn("2013", out); self.assertIn("3 years", out)

    def test_language_detection(self):
        self.assertEqual(common.detect_language("Analyze datasets with SQL and Power BI"), "en")
        self.assertEqual(common.detect_language("Phân tích dữ liệu bằng SQL và Power BI"), "vi")

    def test_doc_id_is_stable_and_short(self):
        self.assertEqual(common.doc_id_for("abc"), common.doc_id_for("abc"))
        self.assertEqual(len(common.doc_id_for("abc")), 16)


class RoleFamilyTests(unittest.TestCase):
    def test_in_family(self):
        for t in ["Senior Data Analyst", "Chuyên viên phân tích dữ liệu", "Business Analytics Specialist", "BI Analyst", "Senior BI Engineer",
                  "Manager, Data Reporting & Insights", "Chuyên viên báo cáo và phân tích dữ liệu nhân sự", unicodedata.normalize("NFD", "Nhân viên phân tích dữ liệu"),
                  "Chuyên viên phân tích số liệu", "Chuyên viên BI", "Chuyên viên MIS", "MIS Analyst", "Nhân viên BI (Business Intelligence)"]:
            self.assertTrue(common.is_da_family(t), t)

    def test_out_of_family(self):
        for t in ["Data Engineer", "Data Scientist", "Data Engineer / Data Analyst", "Nhân viên kỹ thuật thiết bị ô tô", "Vòng bi FAG sales",
                  "Tuyển nữ nhân viên xếp bi CLB bida", "Operations Specialist - Senior", "Software Developer", "Business Transformation Manager",
                  "Business Analyst", "Chuyên viên phân tích kinh doanh", "Chuyên viên phân tích tín dụng"]:
            self.assertFalse(common.is_da_family(t), t)


class TaxonomyTests(unittest.TestCase):
    def test_taxonomy_well_formed(self):
        ids = [s["id"] for s in TAX["skills"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(s["group"] in TAX["groups"] for s in TAX["skills"]))
        self.assertRegex(TAX["version"], r"^\d+\.\d+\.\d+$")

    def test_tricky_tokens(self):
        cases = [
            ("r_lang", "Proficient in SQL/R/Python", True), ("r_lang", "HR data analyst", False), ("r_lang", "R programming", True), ("r_lang", "R&D team", False),
            ("sas", "SaaS platform", False), ("sas", "SAS programming", True),
            ("ai_general", "ai cũng có thể ứng tuyển", False), ("ai_general", "kinh nghiệm với AI", True), ("ai_general", "Artificial intelligence", True),
            ("excel", "excel at communication", False), ("excel", "Advanced Excel (pivot tables)", True),
            ("generative_ai", "use ChatGPT, Copilot or Claude Code", True), ("generative_ai", "LLM-based features", True), ("generative_ai", "data analyst", False),
            ("power_bi", "PowerBI dashboards", True), ("power_bi", "Power-BI", True), ("tableau", "Tableau", True),
            ("machine_learning", "HTML and CSS", False), ("machine_learning", "ML models", True),
            ("looker", "Looker Studio", False), ("looker_studio", "Looker Studio", True), ("looker", "LookML explores", True),
            ("sql", "truy vấn dữ liệu", True), ("english", "Tiếng Anh giao tiếp", True), ("data_warehouse", "kho dữ liệu", True),
        ]
        for skill_id, text, want in cases:
            with self.subTest(skill=skill_id, text=text):
                self.assertEqual(hits(skill_id, text), want)


class FieldExtractionTests(unittest.TestCase):
    def test_years_of_experience(self):
        cases = {
            "Minimum 3+ years of experience in analytics": (3.0, None),
            "Từ 2-4 năm kinh nghiệm phân tích dữ liệu": (2.0, 4.0),
            "Tháng lương thứ 13, hợp đồng 2 năm": (None, None),
            "Tuổi từ 20 tới 40 năm": (None, None),
            "5+ years in data/analytics": (5.0, None),
            "must be 21 years old": (None, None),
            "2 year contract": (None, None),
            "3-5 years working with SQL": (3.0, 5.0),
            "no numbers here": (None, None),
        }
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual(ed.years_of_experience(text), want)

    def test_seniority(self):
        cases = {"Senior Data Analyst": "senior", "Data Analyst Intern": "intern", "Chuyên viên chính phân tích dữ liệu": "senior",
                 "Manager, Data Reporting": "manager", "Head of Analytics": "head_director", "Data Analyst": "unspecified",
                 "Chuyên viên phân tích dữ liệu": "mid", "Data Analyst II": "mid", "Junior BI Developer": "junior", "Analytics Team Lead": "lead"}
        for title, want in cases.items():
            with self.subTest(title=title):
                self.assertEqual(ed.seniority_from_title(title), want)

    def test_degree_english_workmode_salary(self):
        self.assertEqual(ed.degree_level("Bachelor's degree in Statistics"), "bachelor")
        self.assertEqual(ed.degree_level("Tốt nghiệp Cao đẳng trở lên"), "college_diploma")
        self.assertEqual(ed.degree_level("Thạc sĩ"), "master")
        self.assertEqual(ed.degree_level("nothing"), "none_stated")
        self.assertEqual(ed.english_requirement("Fluent English is required"), "required_fluent")
        self.assertEqual(ed.english_requirement("Tiếng Anh giao tiếp"), "required_working")
        self.assertEqual(ed.english_requirement("English"), "mentioned")
        self.assertEqual(ed.english_requirement("no language"), "none")
        self.assertEqual(ed.work_mode("hybrid role, 3 days in office"), "hybrid")
        self.assertEqual(ed.work_mode("100% remote in Vietnam"), "remote")
        self.assertEqual(ed.work_mode("x", declared="On-site"), "on_site")
        self.assertEqual(ed.work_mode("x"), "unspecified")
        self.assertEqual(ed.salary_mention("Salary: Từ 45,000,000 VND++"), "amount_given")
        self.assertEqual(ed.salary_mention("Competitive salary"), "negotiable_or_competitive")
        self.assertEqual(ed.salary_mention("nothing"), "not_mentioned")
        self.assertEqual(ed.salary_mention("x", declared="26 - 36 triệu"), "amount_given")
        self.assertEqual(ed.salary_mention("x", declared="Thỏa thuận"), "negotiable_or_competitive")

    def test_extract_document_shape(self):
        doc = {"doc_id": "a" * 16, "source": "t", "era": "2026", "posted_year": 2026, "da_family": True, "language": "en", "region": "VN-HCM", "n_chars": 50,
               "title": "Senior Data Analyst", "text": "Use SQL and Power BI. 3+ years of experience. Familiar with ChatGPT. Hybrid, 2 days in office.", "work_mode_declared": "Remote", "declared_salary": "20 triệu"}
        row = ed.extract_document(doc, TAX)
        self.assertTrue(row["skill__sql"] and row["skill__power_bi"] and row["skill__generative_ai"] and row["any_ai"])
        self.assertFalse(row["skill__tableau"])
        # text wins over the declared fields so every cell is measured the same way
        self.assertEqual((row["years_min"], row["years_max"], row["seniority"], row["work_mode"], row["salary"]), (3.0, None, "senior", "hybrid", "not_mentioned"))

    def test_prevalence_rows_use_wilson(self):
        rows = [{"any_ai": i < 2, **{f"skill__{s['id']}": (s["id"] == "sql" and i < 5) for s in TAX["skills"]}} for i in range(10)]
        prev = ed.prevalence_rows(rows, TAX, "p", "2026")
        sql = next(r for r in prev if r["skill_id"] == "sql"); ai = next(r for r in prev if r["skill_id"] == "any_ai")
        self.assertEqual((sql["k"], sql["n_docs"], sql["rate"]), (5, 10, 0.5))
        self.assertAlmostEqual(sql["wilson_low"], 0.2366, places=3)
        self.assertEqual(ai["k"], 2)


class CellAndStratumTests(unittest.TestCase):
    def test_cells_are_disjoint_within_a_panel_and_use_the_family_flag(self):
        docs = [
            {"source": "gsearch_us_2022", "era": "2022", "region": "US"}, {"source": "us_open_2026", "era": "2026", "region": "US"},
            {"source": "tinix_vn", "era": "2022", "region": "VN-HCM"}, {"source": "tinix_vn", "era": "2026", "region": "VN-HN"},
            {"source": "wayback_vn_2022", "era": "2022", "region": "VN-HN"}, {"source": "wayback_vn_2022", "era": "2022", "region": "other"},
            {"source": "unlisted_source", "era": "2026", "region": "VN-HCM"},  # a source this repo never loads: it must fall in no cell
        ]
        counts = {cell: sum(bool(pred(d)) for d in docs) for cell, pred in ed.CELLS.items()}
        self.assertEqual(counts["US_2022"], 1); self.assertEqual(counts["US_2026"], 1)
        self.assertEqual(counts["VN_2022"], 2)      # platform 2022 + archived page in Vietnam; the "other"-region page is excluded
        self.assertEqual(counts["VN_2026"], 1)      # platform 2026 only
        self.assertEqual(sorted(counts), sorted(ed.CELLS))
        self.assertEqual(sum(counts.values()) - counts["VN_platform_2022"] - counts["VN_platform_2026"], 5)  # unknown sources join no cell
        for name, spec in ed.PANELS.items():
            a, b = ed.CELLS[spec["a"]], ed.CELLS[spec["b"]]
            self.assertFalse(any(a(d) and b(d) for d in docs), name)

    def test_stratum_labels(self):
        self.assertEqual(ed.stratum_of({"seniority": "senior", "region": "VN-HN"}, "seniority"), "senior")
        self.assertEqual(ed.stratum_of({"seniority": "manager", "region": "VN-HN"}, "seniority_region"), "lead_plus|VN-HN")
        self.assertEqual(ed.stratum_of({"seniority": "unspecified", "region": "US"}, "seniority_region"), "mid|other")
        self.assertEqual(ed.stratum_of({"seniority": "intern", "region": "VN-HCM"}, "seniority"), "junior")


class PublicOnlyTests(unittest.TestCase):
    def test_only_public_sources_define_cells_and_panels(self):
        sources = {"gsearch_us_2022", "us_open_2026", "tinix_vn", "wayback_vn_2022"}
        used = {d["source"] for d in [{"source": s, "era": e, "region": "VN-HN"} for s in sources for e in ("2022", "2026")] if any(pred(d) for pred in ed.CELLS.values())}
        self.assertEqual(used, sources)
        self.assertEqual(sorted(ed.CELLS), ["US_2022", "US_2026", "VN_2022", "VN_2026", "VN_platform_2022", "VN_platform_2026"])
        self.assertEqual(sorted(ed.PANELS), ["P1_us_2022_vs_2026", "P2_vn_2022_vs_2026", "P3_us_vs_vn_2026", "S1_vn_platform_only"])


if __name__ == "__main__":
    unittest.main()
