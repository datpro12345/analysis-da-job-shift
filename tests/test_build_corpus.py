"""Tests for the corpus pipeline on synthetic documents and tiny fictional source files (no downloads, no network)."""
import csv
import gzip
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import build_corpus as bc  # noqa: E402
import common  # noqa: E402


def doc(title, text, company="Acme", source="s", era="2026"):
    return {"source": source, "era": era, "posted_year": int(era), "title": title, "company": company, "location": "Ho Chi Minh City", "region": "VN", "work_mode_declared": "", "url": "", "text": text}


# fictional number, built from parts so the repository scan finds no phone-like literal
FAKE_PHONE = "09" + "00 000 000"
WORDS = ["sales", "marketing", "finance", "supply chain", "customer", "product", "pricing", "fraud", "credit", "logistics", "retail", "payments"]
TEAMS = ["finance", "operations", "growth", "risk", "merchandising", "strategy"]


def body(seed: int) -> str:
    """Six distinct lines per seed so two different seeds share few 5-word shingles."""
    lines = [f"Line {seed}-{k}: analyze {WORDS[(seed * 3 + k) % len(WORDS)]} data for the {TEAMS[(seed + 2 * k) % len(TEAMS)]} team and report weekly trend number {seed * 7 + k}."
             for k in range(6)]
    return "\n".join(lines)


BODY = body(0)


class PipelineTests(unittest.TestCase):
    def test_boilerplate_removed_by_frequency(self):
        footer = "Equal opportunity employer. Apply through our careers portal today."
        docs = [doc(f"Data Analyst {i}", body(i) + "\n" + footer) for i in range(6)]
        meta = {}
        out = bc.process(docs, meta)
        self.assertEqual(len(out), 6)
        self.assertTrue(all(footer not in d["text"] for d in out))
        self.assertEqual(meta["boilerplate_distinct_lines"], 1)
        self.assertEqual(meta["boilerplate_lines_removed"], 6)

    def test_rare_line_is_kept(self):
        line = "Work with the pricing team on weekly margin reviews."
        docs = [doc("Data Analyst", body(0) + "\n" + line)] + [doc(f"Data Analyst {i}", body(i)) for i in range(1, 6)]
        out = bc.process(docs, {})
        self.assertTrue(any(line in d["text"] for d in out))

    def test_exact_and_near_duplicates_dropped(self):
        a = doc("Data Analyst", body(0) + "\nReport to the head of data.")
        b = doc("Data Analyst", body(0) + "\nReport to the head of data.")            # exact copy
        c = doc("Data Analyst", body(0) + "\nReport to the head of analytics.")       # near copy (one word), same company
        d = doc("Data Analyst", body(0) + "\nReport to the head of data.", company="Other")  # same text, other company -> exact dup by hash
        meta = {}
        out = bc.process([a, b, c, d], meta)
        self.assertEqual(len(out), 1)
        self.assertEqual(meta["exact_duplicates"], 2)
        self.assertEqual(meta["near_duplicates"], 1)

    def test_short_documents_dropped_and_labels_set(self):
        docs = [doc("Senior Data Analyst", body(1)), doc("Data Engineer", body(2)), doc("Data Analyst", "too short")]
        meta = {}
        out = bc.process(docs, meta)
        self.assertEqual(meta["too_short"], 1)
        fam = {d["title"]: d["da_family"] for d in out}
        self.assertEqual(fam, {"Senior Data Analyst": True, "Data Engineer": False})
        self.assertTrue(all(d["language"] == "en" and d["region"] == "VN-HCM" and len(d["doc_id"]) == 16 for d in out))

    def test_personal_data_never_survives(self):
        docs = [doc("Data Analyst", body(3) + "\nContact: Ms. Sample, zalo " + FAKE_PHONE + ", sample@example.com")]
        out = bc.process(docs, {})
        self.assertNotIn("example.com", out[0]["text"]); self.assertNotIn("09" + "00", out[0]["text"]); self.assertNotIn("Sample", out[0]["text"])


class HtmlExtractionTests(unittest.TestCase):
    def test_sections_between_markers(self):
        html = ("<html><head><title>Data Analyst - Acme | Jobs</title><style>.x{}</style></head><body><script>var a=1;</script>"
                "<div>Việc làm tương tự</div><h2>Mô tả công việc</h2><ul><li>Phân tích dữ liệu bán hàng với SQL</li><li>Xây dựng dashboard Power BI</li></ul>"
                "<h2>Yêu cầu ứng viên</h2><p>Tốt nghiệp Đại học, 2 năm kinh nghiệm, tiếng Anh giao tiếp. " + "Thành thạo Excel. " * 10 + "</p>"
                "<h2>Địa điểm làm việc</h2><p>Hồ Chí Minh</p><footer>Cách thức ứng tuyển</footer></body></html>")
        title, text, in_vn, hint = bc.html_to_job_text(html)
        self.assertEqual(title, "Data Analyst")
        self.assertIn("Hồ Chí Minh", hint)
        self.assertTrue(text.startswith("Mô tả công việc"))
        self.assertIn("Yêu cầu ứng viên", text); self.assertIn("Power BI", text)
        self.assertNotIn("Địa điểm làm việc", text); self.assertNotIn("var a=1", text)
        self.assertTrue(in_vn)

    def test_fallback_to_longest_block(self):
        html = "<html><body><p>short</p><p>" + "Build reports and dashboards for the finance team using SQL. " * 8 + "</p><p>tiny</p></body></html>"
        _, text, in_vn, _ = bc.html_to_job_text(html)
        self.assertIn("dashboards", text); self.assertFalse(in_vn)


class MissingValueTests(unittest.TestCase):
    def test_pandas_missing_values_become_empty_text(self):
        self.assertEqual(bc._text(None), "")
        self.assertEqual(bc._text(float("nan")), "")
        self.assertEqual(bc._text("nan"), "")
        self.assertEqual(bc._text("<NA>"), "")
        self.assertEqual(bc._text("SQL, Excel"), "SQL, Excel")
        self.assertEqual(bc._text(2022), "2022")


class LocationTests(unittest.TestCase):
    def test_us_location_rule(self):
        yes = ["New York, NY", "San Francisco Bay Area", "United States", "Austin, TX", "Jersey City, NJ", "Washington DC-Baltimore Area", "Remote - USA"]
        no = ["London, England, United Kingdom", "Remote", "Toronto, Ontario, Canada", "Paris, Île-de-France, France", "Singapore, Singapore", "Ho Chi Minh City, Vietnam", "Sydney, New South Wales, Australia"]
        for loc in yes:
            self.assertTrue(bc.is_us_location(loc), loc)
        for loc in no:
            self.assertFalse(bc.is_us_location(loc), loc)


def drain(gen):
    """Items of a loader generator and the value it returns (loaders return per-source totals)."""
    items = []
    try:
        while True:
            items.append(next(gen))
    except StopIteration as stop:
        return items, stop.value


class LoaderTests(unittest.TestCase):
    """Each loader reads a tiny FICTIONAL file written to a temp folder, in the real source's column layout."""

    def test_gsearch_keeps_one_year_and_reads_either_location_column(self):
        import pandas as pd

        rows = [
            {"title": "Data Analyst", "company_name": "Example Co", "job_location": "Springfield, ST", "description": "Analyze fictional data.", "date_time": "2022-11-05 10:00:00", "via": "via Example Board", "work_from_home": True, "salary": ""},
            {"title": "Data Analyst", "company_name": "Example Co", "job_location": "Springfield, ST", "description": "Later year, dropped.", "date_time": "2023-02-01 10:00:00", "via": "via Example Board", "work_from_home": False, "salary": ""},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            pd.DataFrame(rows).to_csv(folder / "gsearch_jobs_2022.csv", index=False)
            self.assertEqual(bc.find_gsearch_csv(folder).name, "gsearch_jobs_2022.csv")
            out = list(bc.load_gsearch_us(folder / "gsearch_jobs_2022.csv"))
            (folder / "gsearch_jobs_2022.csv").rename(folder / "gsearch_jobs_hf_mirror.csv")
            self.assertEqual(bc.find_gsearch_csv(folder).name, "gsearch_jobs_hf_mirror.csv")
            with self.assertRaises(FileNotFoundError):
                bc.find_gsearch_csv(folder / "missing")
        self.assertEqual(len(out), 1)
        self.assertEqual((out[0]["source"], out[0]["era"], out[0]["location"], out[0]["work_mode_declared"]), ("gsearch_us_2022", "2022", "Springfield, ST", "remote"))

    def test_us_open_keeps_us_rows_of_the_year(self):
        import pandas as pd

        rows = [
            {"job_id": 1, "listed_date": "2026-02-03", "title": "Data Analyst", "location": "Springfield, IL", "description": "Fictional text one."},
            {"job_id": 2, "listed_date": "2026-02-03", "title": "Data Analyst", "location": "Remote", "description": "Country unknown, dropped."},
            {"job_id": 3, "listed_date": "2026-02-03", "title": "Data Analyst", "location": "Paris, France", "description": "Not US, dropped."},
            {"job_id": 4, "listed_date": "2025-12-30", "title": "Data Analyst", "location": "Austin, TX", "description": "Wrong year, dropped."},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            pd.DataFrame(rows).to_parquet(Path(tmp) / "jobs_2026_02.parquet")
            out, meta = drain(bc.load_us_open_2026(Path(tmp), 2026))
            with self.assertRaises(FileNotFoundError):
                drain(bc.load_us_open_2026(Path(tmp) / "none", 2026))
        self.assertEqual([d["text"] for d in out], ["Fictional text one."])
        self.assertEqual(meta, {"rows_in_year": 3, "rows_us": 1, "rows_remote_country_unknown": 1})

    def test_tinix_keeps_data_analyst_titles_and_reports_year_totals(self):
        import pandas as pd

        base = {"company_name": "Example Co", "location": "Hà Nội", "job_type": "Toàn thời gian", "experience_level": "1 năm", "job_position": "Nhân viên", "education_level": "Đại học", "salary": "Thỏa thuận"}
        rows = [
            {**base, "year": 2022, "job_title": "Chuyên viên phân tích dữ liệu", "job_description": "Mô tả giả tưởng.", "requirements": "Biết SQL."},
            {**base, "year": 2022, "job_title": "Kế toán", "job_description": "Không phải ngành dữ liệu.", "requirements": ""},
            {**base, "year": 2026, "job_title": "Data Analyst", "job_description": "Fictional description.", "requirements": None},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            pd.DataFrame(rows).to_parquet(Path(tmp) / "data.parquet")
            out, totals = drain(bc.load_tinix_vn(Path(tmp) / "data.parquet"))
        self.assertEqual([d["title"] for d in out], ["Chuyên viên phân tích dữ liệu", "Data Analyst"])
        self.assertEqual(totals, {2022: 2, 2026: 1})
        self.assertIn("Yêu cầu ứng viên:\nBiết SQL.", out[0]["text"])
        self.assertNotIn("Yêu cầu", out[1]["text"])
        self.assertEqual((out[0]["era"], out[1]["era"], out[0]["region"]), ("2022", "2026", "VN"))

    def test_wayback_reads_manifest_gunzips_and_skips_unusable_pages(self):
        page = ("<html><head><title>Data Analyst - Example Co | Jobs</title></head><body><h2>Mô tả công việc</h2><p>" + "Phân tích dữ liệu giả tưởng bằng SQL. " * 8 +
                "</p><h2>Quyền lợi</h2><p>Không có.</p><p>Địa điểm làm việc: Hà Nội</p></body></html>")
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "topcv").mkdir()
            (folder / "topcv" / "plain.html").write_text(page, encoding="utf-8")
            (folder / "topcv" / "zipped.html").write_bytes(gzip.compress(page.encode("utf-8")))
            (folder / "topcv" / "missing_status.html").write_text(page, encoding="utf-8")
            with (folder / "manifest.csv").open("w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(["site", "timestamp", "original_url", "wayback_url", "file", "http_status", "bytes", "fetched_at_utc"])
                w.writerow(["topcv", "20220105000000", "https://example.invalid/a", "", "topcv/plain.html", "200", "1", ""])
                w.writerow(["topcv", "20220106000000", "https://example.invalid/b", "", "topcv/zipped.html", "200", "1", ""])
                w.writerow(["topcv", "20220107000000", "https://example.invalid/c", "", "topcv/missing_status.html", "404", "1", ""])
                w.writerow(["vietnamworks", "20220108000000", "https://example.invalid/d-kw", "", "topcv/plain.html", "200", "1", ""])
                w.writerow(["glints", "20220109000000", "https://example.invalid/e", "", "topcv/plain.html", "200", "1", ""])
            out = list(bc.load_wayback_vn(folder))
            self.assertEqual(list(bc.load_wayback_vn(folder / "none")), [])
        self.assertEqual(len(out), 2)
        self.assertTrue(all(d["region"] == "VN" and d["title"] == "Data Analyst" and d["posted_year"] == 2022 for d in out))

    def test_only_the_four_public_loaders_exist(self):
        loaders = sorted(n for n in dir(bc) if n.startswith("load_"))
        self.assertEqual(loaders, ["load_gsearch_us", "load_tinix_vn", "load_us_open_2026", "load_wayback_vn"])

    def test_summary_rows(self):
        corpus = [{"source": "s", "era": "2026", "da_family": True, "language": "en", "region": "VN-HCM", "n_chars": 500},
                  {"source": "s", "era": "2026", "da_family": False, "language": "vi", "region": "VN-HN", "n_chars": 900}]
        rows = bc.summarise(corpus, {})
        self.assertEqual(rows[0]["n_docs"], 2); self.assertEqual(rows[0]["n_da_family"], 1); self.assertEqual(rows[0]["median_chars"], 500)

    def test_corpus_lines_are_json(self):
        d = doc("Data Analyst", BODY)
        out = bc.process([d], {})
        line = json.dumps(out[0], ensure_ascii=False)
        self.assertEqual(json.loads(line)["doc_id"], out[0]["doc_id"])


if __name__ == "__main__":
    unittest.main()
