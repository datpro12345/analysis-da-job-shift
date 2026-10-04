#!/usr/bin/env python3
"""Layer 2: deterministic extraction - taxonomy skills and regex fields per document.

Why deterministic first
-----------------------
Before any model reads the postings, a rule layer gives numbers that are cheap,
reproducible and easy to audit: the same regex gives the same answer tomorrow,
and a doubtful hit can be traced to one pattern in taxonomy/skills.yaml. It is
also the recall floor for the LLM annotation in stage 2 (a tool the regex saw
but the model did not list is flagged for review). What rules cannot do is
tell "uses AI tools" from "builds AI products" or "required" from "nice to
have"; that is stage 2's job.

Fields
------
* one boolean per taxonomy skill (document mentions it at least once);
* years of experience (min, max) from "3+ years", "2-4 năm kinh nghiệm" and
  similar, accepted only when the word experience / kinh nghiệm is nearby so
  contract lengths and ages are not mistaken for experience;
* seniority from the title (intern, junior, mid, senior, lead, manager,
  head_director, unspecified);
* degree level (college_diploma, bachelor, master, phd, none_stated);
* English requirement (required_fluent, required_working, mentioned, none);
* work mode (remote, hybrid, on_site, unspecified) from the text only;
* salary mention (amount_given, negotiable_or_competitive, not_mentioned)
  from the text only. Structured fields some sources carry (a remote flag, a
  salary field) are deliberately NOT used, so every cell is measured the same
  way; they stay in the corpus for stage 3;
* any_ai = generative_ai OR ai_general, a convenience flag.

Outputs: <data-root>/corpus/extracted.csv (document level, not in git)
and results/*.csv (aggregates: prevalence per skill per CELL with
Wilson intervals; requirement distributions; the yearly trend inside the
Vietnamese platform). Cells and panels are defined in CELLS / PANELS below and
explained in the README.
Run:  .venv/bin/python src/extract_deterministic.py --data-root /path/to/data
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
import stats  # noqa: E402

# ------------------------------------------------------------------- cells
# A CELL is one country-era group built from one or more sources with the SAME
# selection rule (Data Analyst family title, see common.is_da_family). A PANEL
# compares two cells: `a` is the baseline, `b` the comparison, so a positive
# risk difference reads "more common in b".
CELLS = {
    "US_2022": lambda d: d["source"] == "gsearch_us_2022",
    "US_2026": lambda d: d["source"] == "us_open_2026",
    "VN_2022": lambda d: (d["source"] == "tinix_vn" and str(d["era"]) == "2022") or (d["source"] == "wayback_vn_2022" and str(d["region"]).startswith("VN")),
    "VN_2026": lambda d: d["source"] == "tinix_vn" and str(d["era"]) == "2026",
    "VN_platform_2022": lambda d: d["source"] == "tinix_vn" and str(d["era"]) == "2022",
    "VN_platform_2026": lambda d: d["source"] == "tinix_vn" and str(d["era"]) == "2026",
}
PANELS = {
    # primary design
    "P1_us_2022_vs_2026": {"a": "US_2022", "b": "US_2026", "strata": "seniority",
                           "question": "United States: Data Analyst family postings, Nov-Dec 2022 (Google Jobs set) vs Jan-Aug 2026 (open postings set)."},
    "P2_vn_2022_vs_2026": {"a": "VN_2022", "b": "VN_2026", "strata": "seniority_region",
                           "question": "Vietnam: 2022 (platform + archived portals) vs 2026 (platform)."},
    "P3_us_vs_vn_2026": {"a": "US_2026", "b": "VN_2026", "strata": "seniority",
                         "question": "Cross-section 2026: Vietnam vs United States."},
    # robustness
    "S1_vn_platform_only": {"a": "VN_platform_2022", "b": "VN_platform_2026", "strata": "seniority_region",
                            "question": "Same Vietnamese platform only, 2022 vs 2026 (no portal or channel change)."},
}

SENIORITY_BUCKET = {"intern": "junior", "junior": "junior", "mid": "mid", "unspecified": "mid", "senior": "senior", "lead": "lead_plus", "manager": "lead_plus", "head_director": "lead_plus"}


def stratum_of(row: dict, kind: str) -> str:
    """Stratum label used for post-stratification weights (see stats.post_stratified_rate)."""
    sen = SENIORITY_BUCKET.get(row["seniority"], "mid")
    if kind == "seniority_region":
        reg = row["region"] if row["region"] in ("VN-HCM", "VN-HN") else "other"
        return f"{sen}|{reg}"
    return sen


# ------------------------------------------------------------ field regexes
EXP_CONTEXT_VI = re.compile(r"(kinh\s*nghiệm|experience|trở\s*lên)", re.I)
# English "N years" is experience unless it is an age, a contract or a warranty.
EXP_NOT_EN = re.compile(r"^\s*(?:old|of\s*age|contract|warranty|guarantee|tenure|lease)", re.I)
YEARS_EN = re.compile(r"(?<!\d)(\d{1,2})(?:\s*(?:\+|or more|plus))?(?:\s*(?:-|–|to)\s*(\d{1,2}))?\s*\+?\s*(?:years?|yrs?)\b", re.I)
YEARS_VI = re.compile(r"(?<!\d)(\d{1,2})(?:\s*(?:-|–|đến|tới)\s*(\d{1,2}))?\s*\+?\s*năm\b", re.I)
MIN_WORDS = re.compile(r"(at least|minimum|min\.?|tối thiểu|ít nhất|từ|trên|hơn|over)\s*$", re.I)

SENIORITY_RULES = [
    ("intern", re.compile(r"\bintern(ship)?\b|thực\s*tập|\btrainee\b|\bfresher\b", re.I)),
    ("head_director", re.compile(r"\bhead\b|\bdirector\b|\bchief\b|\bvp\b|vice president|giám\s*đốc|\bcdo\b|\bcto\b", re.I)),
    ("manager", re.compile(r"\bmanager\b|\bmanagement\b(?!\s*trainee)|trưởng\s*phòng|quản\s*lý|trưởng\s*bộ\s*phận|\bexpert\b|chuyên\s*gia", re.I)),
    ("lead", re.compile(r"\blead(er)?\b|\bteam\s*lead|\bsupervisor\b|trưởng\s*nhóm|giám\s*sát|\bprincipal\b", re.I)),
    ("senior", re.compile(r"\bsenior\b|\bsr\.?\b|\biii\b|chuyên\s*viên\s*(?:chính|cao\s*cấp)|\bcvcc\b", re.I)),
    ("junior", re.compile(r"\bjunior\b|\bjr\.?\b|\bentry[- ]level\b|\bassociate\b|\bgraduate\b|\bi\b$|nhân\s*viên\s*mới", re.I)),
    ("mid", re.compile(r"\bmiddle\b|\bmid[- ]level\b|\bii\b|\bchuyên\s*viên\b", re.I)),
]

DEGREE_RULES = [
    ("phd", re.compile(r"\bph\.?d\b|doctorate|tiến\s*sĩ", re.I)),
    ("master", re.compile(r"\bmaster'?s?\b|\bm\.?sc?\.?\b|\bmba\b|thạc\s*sĩ|\bpostgraduate\b", re.I)),
    ("bachelor", re.compile(r"\bbachelor'?s?\b|\bb\.?sc?\.?\b|\bbs/ms\b|\bundergraduate\b|university\s*degree|đại\s*học|cử\s*nhân|\bđh\b|\bdegree\b", re.I)),
    ("college_diploma", re.compile(r"cao\s*đẳng|\bcollege\b|associate'?s?\s*degree|\bdiploma\b|\bcđ\b", re.I)),
]

ENGLISH = re.compile(r"\benglish\b|tiếng\s*anh|\bielts\b|\btoeic\b", re.I)
ENGLISH_FLUENT = re.compile(r"(fluent|fluency|excellent|proficien|advanced|native|professional\s*(?:working\s*)?proficiency|thành\s*thạo|lưu\s*loát|tốt|ielts\s*[67]|toeic\s*[78]\d\d)", re.I)
ENGLISH_WORKING = re.compile(r"(good|working|intermediate|communicat|business\s*english|giao\s*tiếp|khá|đọc\s*hiểu|reading|written)", re.I)

REMOTE = re.compile(r"\bremote\b|work\s*from\s*home|\bwfh\b|làm\s*việc\s*từ\s*xa|\btừ\s*xa\b", re.I)
HYBRID = re.compile(r"\bhybrid\b|\d\s*days?\s*(?:in|at)\s*(?:the\s*)?office|\d\s*ngày\s*(?:tại|ở)\s*văn\s*phòng", re.I)
ONSITE = re.compile(r"\bon[- ]?site\b|\bin[- ]office\b|tại\s*văn\s*phòng|\boffice[- ]based\b", re.I)

SALARY_AMOUNT = re.compile(r"(\$\s?\d|\d\s?(?:usd|vnd|vnđ|đ\b|triệu|\btr\b|million|k\b/(?:month|year))|\d{1,3}(?:[.,]\d{3}){2,}|\bup\s*to\s*\$?\d|\d+\s*-\s*\d+\s*(?:triệu|tr\b|usd|\$))", re.I)
SALARY_NEGOTIABLE = re.compile(r"negotiable|competitive|thỏa\s*thuận|thoả\s*thuận|cạnh\s*tranh|attractive|hấp\s*dẫn|\bnego\b", re.I)


def years_of_experience(text: str) -> tuple[float | None, float | None]:
    """(min, max) years from the first well-supported experience phrase, else (None, None).

    Vietnamese "N năm" counts only with kinh nghiệm / experience within 80
    characters (năm also means a calendar year and appears in contract terms);
    English "N years" counts unless it is followed by old / of age / contract /
    warranty. "13th-month salary", "2-year contract" and "tuổi từ 20 đến 40"
    therefore do not count. Over all hits we take the smallest minimum and the
    largest maximum, which is what a candidate reads as the stated range."""
    mins, maxs = [], []
    for rx in (YEARS_EN, YEARS_VI):
        for m in rx.finditer(text):
            if rx is YEARS_EN:
                if EXP_NOT_EN.match(text[m.end(): m.end() + 20]):
                    continue
            else:
                window = text[max(0, m.start() - 80): m.end() + 80]
                if not EXP_CONTEXT_VI.search(window):
                    continue
            lo = float(m.group(1)); hi = float(m.group(2)) if m.group(2) else None
            if lo > 20:
                continue
            if hi is not None and hi < lo:
                lo, hi = hi, lo
            mins.append(lo)
            if hi is not None:
                maxs.append(hi)
    if not mins:
        return (None, None)
    return (min(mins), max(maxs) if maxs else None)


def seniority_from_title(title: str) -> str:
    t = common.normalize_text(title)
    for level, rx in SENIORITY_RULES:
        if rx.search(t):
            return level
    return "unspecified"


def degree_level(text: str) -> str:
    for level, rx in DEGREE_RULES:
        if rx.search(text):
            return level
    return "none_stated"


def english_requirement(text: str) -> str:
    hits = list(ENGLISH.finditer(text))
    if not hits:
        return "none"
    for m in hits:
        window = text[max(0, m.start() - 60): m.end() + 60]
        if ENGLISH_FLUENT.search(window):
            return "required_fluent"
    for m in hits:
        window = text[max(0, m.start() - 60): m.end() + 60]
        if ENGLISH_WORKING.search(window):
            return "required_working"
    return "mentioned"


def work_mode(text: str, declared: str = "") -> str:
    d = (declared or "").lower()
    if "remote" in d or "từ xa" in d:
        return "remote"
    if "hybrid" in d:
        return "hybrid"
    if "on-site" in d or "onsite" in d or "on site" in d:
        return "on_site"
    if HYBRID.search(text):
        return "hybrid"
    if REMOTE.search(text):
        return "remote"
    if ONSITE.search(text):
        return "on_site"
    return "unspecified"


def salary_mention(text: str, declared: str = "") -> str:
    d = (declared or "").strip().lower()
    if d and d not in ("", "not published", "thỏa thuận", "thoả thuận", "negotiable", "none", "nan"):
        return "amount_given"
    if SALARY_AMOUNT.search(text):
        return "amount_given"
    if SALARY_NEGOTIABLE.search(text) or d in ("thỏa thuận", "thoả thuận", "negotiable"):
        return "negotiable_or_competitive"
    return "not_mentioned"


def skill_flags(text: str, tax: dict) -> dict[str, bool]:
    return {s["id"]: any(rx.search(text) for rx in s["_ci"]) or any(rx.search(text) for rx in s["_cs"]) for s in tax["skills"]}


def extract_document(doc: dict, tax: dict) -> dict:
    text = f"{doc['title']}\n{doc['text']}"
    flags = skill_flags(text, tax)
    lo, hi = years_of_experience(text)
    return {
        "doc_id": doc["doc_id"], "source": doc["source"], "era": doc["era"], "posted_year": doc["posted_year"],
        "da_family": doc["da_family"], "language": doc["language"], "region": doc["region"], "n_chars": doc["n_chars"],
        "years_min": lo, "years_max": hi, "seniority": seniority_from_title(doc["title"]), "degree": degree_level(text),
        # text only, on purpose: some sources carry a structured remote flag or
        # salary field and others do not, so using them would make cells differ
        # by instrument rather than by content (the declared values stay in the
        # corpus for stage 3)
        "english": english_requirement(text), "work_mode": work_mode(text),
        "salary": salary_mention(text), "any_ai": flags["generative_ai"] or flags["ai_general"],
        **{f"skill__{k}": v for k, v in flags.items()},
    }


# ------------------------------------------------------------- aggregates
def prevalence_rows(rows: list[dict], tax: dict, panel: str, cell: str) -> list[dict]:
    n = len(rows)
    out = []
    for s in tax["skills"] + [{"id": "any_ai", "label": "Any AI mention (generative_ai or ai_general)", "group": "ai_genai"}]:
        col = "any_ai" if s["id"] == "any_ai" else f"skill__{s['id']}"
        k = sum(1 for r in rows if r[col])
        lo, hi = stats.wilson_interval(k, n)
        out.append({"panel": panel, "cell": cell, "skill_id": s["id"], "group": s["group"], "label": s["label"], "n_docs": n, "k": k,
                    "rate": round(k / n, 4) if n else None, "wilson_low": round(lo, 4), "wilson_high": round(hi, 4)})
    return out


def distribution_rows(rows: list[dict], panel: str, cell: str) -> list[dict]:
    n = len(rows)
    out = []
    for field in ("seniority", "degree", "english", "work_mode", "salary"):
        for value, k in sorted(collections.Counter(r[field] for r in rows).items()):
            lo, hi = stats.wilson_interval(k, n)
            out.append({"panel": panel, "cell": cell, "field": field, "value": value, "n_docs": n, "k": k, "rate": round(k / n, 4), "wilson_low": round(lo, 4), "wilson_high": round(hi, 4)})
    ys = sorted(r["years_min"] for r in rows if r["years_min"] is not None)
    out.append({"panel": panel, "cell": cell, "field": "years_min", "value": "stated", "n_docs": n, "k": len(ys), "rate": round(len(ys) / n, 4) if n else None,
                "wilson_low": round(stats.wilson_interval(len(ys), n)[0], 4), "wilson_high": round(stats.wilson_interval(len(ys), n)[1], 4)})
    if ys:
        out.append({"panel": panel, "cell": cell, "field": "years_min", "value": "median", "n_docs": n, "k": len(ys), "rate": ys[len(ys) // 2], "wilson_low": ys[len(ys) // 4], "wilson_high": ys[(3 * len(ys)) // 4]})
    return out


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8"); return
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, lineterminator="\n", fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-root", help="default: $DAJS_DATA_DIR or ./data"); ap.add_argument("--results-dir", default=str(common.RESULTS_DIR))
    ap.add_argument("--include-off-family", action="store_true", help="also count postings whose title is outside the Data Analyst family")
    args = ap.parse_args(argv)
    root = common.data_root(args.data_root); results = Path(args.results_dir)
    tax = common.load_taxonomy()
    corpus_path = common.corpus_dir(root) / "corpus.jsonl"
    docs = [json.loads(l) for l in corpus_path.open(encoding="utf-8")]
    extracted = [extract_document(d, tax) for d in docs]
    write_csv(common.corpus_dir(root) / "extracted.csv", extracted)

    scope = extracted if args.include_off_family else [r for r in extracted if r["da_family"]]
    prev, dist, cell_meta = [], [], {}
    for cell, pred in CELLS.items():
        rows = [r for r in scope if pred(r)]
        prev += prevalence_rows(rows, tax, "cells", cell)
        dist += distribution_rows(rows, "cells", cell)
        cell_meta[cell] = {"n_docs": len(rows), "sources": sorted({r["source"] for r in rows}),
                           "share_vi": round(sum(r["language"] == "vi" for r in rows) / len(rows), 3) if rows else None}
    panel_meta = {name: {"question": spec["question"], "a": spec["a"], "b": spec["b"], "strata": spec["strata"],
                         "n_a": cell_meta[spec["a"]]["n_docs"], "n_b": cell_meta[spec["b"]]["n_docs"]} for name, spec in PANELS.items()}
    write_csv(results / "skill_prevalence_by_cell.csv", prev)
    write_csv(results / "requirements_by_cell.csv", dist)
    # yearly trend inside the Vietnamese platform (all years it covers)
    trend = []
    for year in sorted({r["posted_year"] for r in scope if r["source"] == "tinix_vn"}):
        rows = [r for r in scope if r["source"] == "tinix_vn" and r["posted_year"] == year]
        trend += prevalence_rows(rows, tax, "tinix_vn_trend", str(year))
    write_csv(results / "tinix_vn_yearly_trend.csv", trend)
    # off-family counts so the reader sees what the title filter removed
    fam = collections.Counter((r["source"], r["era"], r["da_family"]) for r in extracted)
    write_csv(results / "role_family_filter.csv", [{"source": s, "era": e, "da_family": f, "n_docs": n} for (s, e, f), n in sorted(fam.items())])
    (results / "panels.json").write_text(json.dumps({"taxonomy_version": tax["version"], "cells": cell_meta, "panels": panel_meta}, indent=2), encoding="utf-8")
    for cell, m in cell_meta.items():
        print(f"cell {cell}: n={m['n_docs']} sources={m['sources']}")
    for name, m in panel_meta.items():
        print(f"panel {name}: {m['a']} n={m['n_a']} vs {m['b']} n={m['n_b']}")
    print(f"extracted {len(extracted)} documents (taxonomy {tax['version']}); results -> {results}")


if __name__ == "__main__":
    main()
