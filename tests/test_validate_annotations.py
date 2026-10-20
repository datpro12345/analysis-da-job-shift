"""Fictional records only: validator failures must never echo source text."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from src import common
from src.validate_annotations import validate_record

TEXT = "Data Analyst. Build SQL reports. Python is a plus. 2-4 years experience."
DOC = {"doc_id": "a" * 16, "era": "2022", "text": TEXT}


def record():
    evidence = {"quote": "Build SQL reports"}
    return {
        "schema_version": "1.0.0", "taxonomy_version": "1.0.0",
        "doc_id": DOC["doc_id"], "era": "2022",
        "annotator": {"id": "fictional-model", "kind": "llm"},
        "tasks": [{"category": "reporting_dashboards", "evidence": evidence}],
        "ai_roles": [], "skills": [
            {"skill_id": "sql", "requirement_level": "mentioned", "evidence": evidence},
            {"skill_id": "python", "requirement_level": "preferred",
             "evidence": {"quote": "Python is a plus"}}],
        "soft_skills": [],
        "seniority": {"level": "unspecified", "evidence": None},
        "years_experience": {"min_years": 2, "max_years": 4,
                             "evidence": {"quote": "2-4 years experience"}},
        "degree": {"level": "none_stated", "fields": [], "evidence": None},
        "languages": [], "work_mode": {"mode": "unspecified", "evidence": None},
        "salary": {"mentioned": "not_mentioned", "evidence": None},
        "role_family": {"family": "data_analyst", "evidence": {"quote": "Data Analyst"}},
        "annotator_confidence": 0.9,
    }


class AnnotationValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tax = common.load_taxonomy()

    def validate(self, value, doc=DOC):
        return validate_record(value, doc, self.tax)

    def test_valid_and_normalized_quotes(self):
        value = record()
        self.assertEqual(self.validate(value)["errors"], [])
        value["tasks"][0]["evidence"]["quote"] = "Build\n SQL reports"
        self.assertEqual(self.validate(value)["errors"], [])
        doc = dict(DOC, text=TEXT + " Dữ liệu")
        value["tasks"][0]["evidence"]["quote"] = "Du\u031b\u0303 lie\u0323\u0302u"
        self.assertEqual(self.validate(value, doc)["errors"], [])

    def test_schema_and_malformed_values(self):
        for value in [None, [], {}, dict(record(), extra=True)]:
            with self.subTest(value=type(value).__name__):
                self.assertIn("schema", self.validate(value)["errors"])

    def test_identity_and_version(self):
        for key, value, error in [("doc_id", "b" * 16, "doc_id"),
                                  ("era", "2026", "era"),
                                  ("taxonomy_version", "9.0.0", "taxonomy_version")]:
            r = record()
            r[key] = value
            self.assertIn(error, self.validate(r)["errors"])
        self.assertIn("unknown_document", self.validate(record(), None)["errors"])

    def test_fabricated_quote_and_title_not_in_body(self):
        r = record()
        r["role_family"]["evidence"]["quote"] = "Invented job title"
        self.assertIn("quote_not_found", self.validate(r)["errors"])

    def test_skills_other_and_duplicates(self):
        r = record()
        r["skills"][0]["skill_id"] = "invented_skill"
        self.assertIn("skill_id", self.validate(r)["errors"])
        r["skills"][0]["skill_id"] = "other"
        self.assertIn("other_raw_term", self.validate(r)["errors"])
        r["skills"][0]["raw_term"] = "SQL"
        self.assertEqual(self.validate(r)["errors"], [])
        r["skills"].append(copy.deepcopy(r["skills"][1]))
        self.assertIn("duplicate_skill", self.validate(r)["errors"])

    def test_years_order_and_evidence_required_for_claims(self):
        r = record()
        r["years_experience"]["min_years"] = 5
        self.assertIn("years_order", self.validate(r)["errors"])
        for field, key, value in [("seniority", "level", "senior"),
                                  ("degree", "level", "bachelor"),
                                  ("work_mode", "mode", "remote"),
                                  ("salary", "mentioned", "amount_given")]:
            r = record()
            r[field][key] = value
            self.assertIn("missing_evidence", self.validate(r)["errors"])
        r = record()
        r["years_experience"]["evidence"] = None
        self.assertIn("missing_evidence", self.validate(r)["errors"])

    def test_degree_subjects_can_be_stated_without_degree_level(self):
        r = record()
        r['degree'] = {'level': 'none_stated', 'fields': ['Statistics'],
                       'evidence': {'quote': 'Previous studies in Statistics'}}
        doc = dict(DOC, text=TEXT + ' Previous studies in Statistics.')
        self.assertEqual(self.validate(r, doc)['errors'], [])

    def test_email_marketing_is_not_a_personal_email_address(self):
        r = record()
        r['notes'] = 'Email marketing campaign analysis'
        self.assertEqual(self.validate(r)['errors'], [])

    def test_personal_data_never_echoed(self):
        for note in ["person@example.com", "+84" + "912345678", "Zalo: fictional_handle", "Mr. Example"]:
            r = record()
            r["notes"] = note
            result = self.validate(r)
            self.assertIn("personal_data", result["errors"])
            self.assertNotIn(note, json.dumps(result))

    def test_regex_disagreement_and_low_confidence_are_warnings(self):
        r = record()
        r["skills"] = []
        r["annotator_confidence"] = 0.5
        result = self.validate(r)
        self.assertEqual(result["errors"], [])
        self.assertIn("regex_only:sql", result["warnings"])
        self.assertIn("regex_only:python", result["warnings"])
        self.assertIn("low_confidence", result["warnings"])

    def test_cli_invalid_json_and_unknown_document_exit_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "corpus.jsonl").write_text(json.dumps(DOC) + "\n")
            (root / "annotations.jsonl").write_text("not json\n" + json.dumps(dict(record(), doc_id="b" * 16)) + "\n")
            run = subprocess.run([sys.executable, "src/validate_annotations.py", "--corpus",
                                  str(root / "corpus.jsonl"), "--annotations",
                                  str(root / "annotations.jsonl")], capture_output=True, text=True, check=False)
            self.assertEqual(run.returncode, 1, run.stderr)
            result = json.loads(run.stdout)
            self.assertEqual(result["failed"], 2)
            self.assertNotIn(TEXT, run.stdout)


if __name__ == "__main__":
    unittest.main()
