#!/usr/bin/env python3
"""Validate stage-2 JSONL against its corpus; emit codes/ids, never quotations.

Usage: python src/validate_annotations.py --corpus FILE --annotations FILE
Nonzero exit means at least one record needs correction. Regex disagreements
and confidence below 0.6 are review warnings, not validation failures.
"""
from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path

from jsonschema import Draft202012Validator

try:
    from . import common
except ImportError:
    import common

SCHEMA_PATH = common.REPO_ROOT / "schema" / "jd_annotation.schema.json"
VALIDATOR = Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


def normalized(text: str) -> str:
    """The guide permits NFC and whitespace collapse, but no paraphrasing."""
    return " ".join(unicodedata.normalize("NFC", text).split())


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from strings(child)


def quotes(value):
    if isinstance(value, dict):
        if isinstance(value.get("quote"), str):
            yield value["quote"]
        for child in value.values():
            yield from quotes(child)
    elif isinstance(value, list):
        for child in value:
            yield from quotes(child)


def validate_record(record, document: dict | None, taxonomy: dict) -> dict:
    """Validate one parsed object against one unambiguous corpus record."""
    errors, warnings = set(), set()
    if list(VALIDATOR.iter_errors(record)):
        # jsonschema messages can embed raw values; do not print them.
        return {"errors": ["schema"], "warnings": []}
    if document is None:
        errors.add("unknown_document")
    else:
        if record["doc_id"] != document["doc_id"]:
            errors.add("doc_id")
        if record["era"] != str(document["era"]):
            errors.add("era")
        text = normalized(document["text"])
        if any(normalized(quote) not in text for quote in quotes(record)):
            errors.add("quote_not_found")
    if record["taxonomy_version"] != taxonomy["version"]:
        errors.add("taxonomy_version")
    known = {skill["id"] for skill in taxonomy["skills"]}
    seen = set()
    for skill in record["skills"]:
        sid = skill["skill_id"]
        if sid not in known and sid != "other":
            errors.add("skill_id")
        if sid == "other" and not skill.get("raw_term", "").strip():
            errors.add("other_raw_term")
        key = (sid, skill.get("raw_term", "")) if sid == "other" else (sid, "")
        if key in seen:
            errors.add("duplicate_skill")
        seen.add(key)
    years = record["years_experience"]
    if (years["min_years"] is not None and years["max_years"] is not None
            and years["min_years"] > years["max_years"]):
        errors.add("years_order")
    if any(years[k] is not None for k in ("min_years", "max_years")) and years["evidence"] is None:
        errors.add("missing_evidence")
    for field, key, absent in [("seniority", "level", "unspecified"),
                               ("degree", "level", "none_stated"),
                               ("work_mode", "mode", "unspecified"),
                               ("salary", "mentioned", "not_mentioned")]:
        value = record[field]
        if value[key] != absent and value["evidence"] is None:
            errors.add("missing_evidence")
        # A subject can be stated without a degree level (e.g. "studies in
        # Statistics"). Its fields still need the quoted evidence.
        subject_evidence = field == "degree" and bool(value["fields"])
        if value[key] == absent and value["evidence"] is not None and not subject_evidence:
            errors.add("unexpected_evidence")
    # CONTACT_LINE is a cleaning heuristic, not a personal-data detector:
    # "Email marketing" is a duty, not an email address.
    patterns = (common.EMAIL, common.PHONE, common.HANDLE, common.URL_WITH_USER,
                common.HONORIFIC_NAME)
    if any(pattern.search(s) for s in strings(record) for pattern in patterns):
        errors.add("personal_data")
    if document is not None:
        regex_ids = {s["id"] for s in taxonomy["skills"]
                     if any(p.search(document["text"]) for p in s["_ci"] + s["_cs"])}
        model_ids = {s["skill_id"] for s in record["skills"]} - {"other"}
        warnings.update("regex_only:" + s for s in regex_ids - model_ids)
        warnings.update("model_only:" + s for s in model_ids - regex_ids)
    if record["annotator_confidence"] < 0.6:
        warnings.add("low_confidence")
    return {"errors": sorted(errors), "warnings": sorted(warnings)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, required=True)
    args = parser.parse_args()
    tax = common.load_taxonomy()
    documents = {}
    ambiguous = set()
    with args.corpus.open(encoding="utf-8") as handle:
        for line in handle:
            d = json.loads(line)
            key = (d["doc_id"], str(d["era"]))
            if key in documents:
                ambiguous.add(key)
            documents[key] = d
    results = []
    seen = set()
    with args.annotations.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            try:
                r = json.loads(line)
            except ValueError:
                results.append({"line": number, "errors": ["json_parse"], "warnings": []})
                continue
            key = (r.get("doc_id"), r.get("era")) if isinstance(r, dict) else (None, None)
            # Malformed compound identities must also fail safely.
            if not all(isinstance(k, str) for k in key):
                result = {"errors": ["schema"], "warnings": []}
            else:
                result = validate_record(r, documents.get(key), tax)
                if key in ambiguous:
                    result["errors"].append("ambiguous_document")
                annotator = r.get("annotator")
                identity = key + (annotator.get("id") if isinstance(annotator, dict) else None,)
                if isinstance(identity[2], str):
                    if identity in seen:
                        result["errors"].append("duplicate_annotation")
                    seen.add(identity)
            results.append({"line": number, **result})
    failed = sum(bool(r["errors"]) for r in results)
    print(json.dumps({"records": len(results), "failed": failed, "results": results}, indent=2))
    return int(failed > 0)


if __name__ == "__main__":
    sys.exit(main())
