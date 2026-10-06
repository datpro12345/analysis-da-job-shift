#!/usr/bin/env python3
"""Build report/index.html: one self-contained page with the aggregated results.

Input : results/*.csv and results/*.json (aggregates only), taxonomy/skills.yaml (group names)
Output: report/index.html  (the template scripts/report_template.html with the data embedded
        as JSON in <script type="application/json" id="report-data">)

The page needs no server, no external script, no external font and no tracking.
Every number on the page comes from DATA below, and every number in DATA is read
from a results file (tests/test_report.py checks that, cell by cell). No posting
text goes in: only skill labels, rates, counts and single words or word pairs
that the results already hold (seen in 3 or more postings).

Usage:  python scripts/build_report.py [--results results] [--out report/index.html]
                                        [--repo-url https://github.com/<you>/<repo>] [--check]
Standard library only, except that group names are read from the taxonomy with a tiny
line parser (so PyYAML is not needed).
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
TEMPLATE = Path(__file__).resolve().parent / "report_template.html"
OUT = ROOT / "report" / "index.html"
TAXONOMY = ROOT / "taxonomy" / "skills.yaml"
MARK = "/*__DATA__*/null"
REPO_NAME = "analysis-da-job-shift"

CELLS = {
    "US_2022": ("United States", "2022", "US", "Public US postings, Nov to Dec 2022"),
    "US_2026": ("United States", "2026", "US", "Open postings set, Jan to Aug 2026"),
    "VN_2022": ("Vietnam", "2022", "VN", "Job platform plus archived portal pages, 2022"),
    "VN_2026": ("Vietnam", "2026", "VN", "Job platform, 2026"),
    "VN_platform_2022": ("Vietnam, platform only", "2022", "VN", "Same job platform, 2022"),
    "VN_platform_2026": ("Vietnam, platform only", "2026", "VN", "Same job platform, 2026"),
}
PANELS = ["P1_us_2022_vs_2026", "P2_vn_2022_vs_2026", "P3_us_vs_vn_2026", "S1_vn_platform_only"]
PANEL_TITLES = {
    "P1_us_2022_vs_2026": "United States: 2022 to 2026",
    "P2_vn_2022_vs_2026": "Vietnam: 2022 to 2026",
    "P3_us_vs_vn_2026": "United States against Vietnam, 2026",
    "S1_vn_platform_only": "Vietnam, same platform only: 2022 to 2026",
}
AI_SKILLS = ["any_ai", "ai_general", "generative_ai", "machine_learning", "deep_learning_nlp", "predictive_modeling", "automation", "rpa_low_code"]
TREND_SKILLS = ["sql", "python", "excel", "power_bi", "tableau", "dashboard", "statistics", "any_ai", "generative_ai", "machine_learning", "english", "data_warehouse", "data_quality"]
REQ_FIELDS = [("seniority", "senior"), ("seniority", "lead"), ("seniority", "manager"), ("seniority", "head_director"), ("degree", "bachelor"), ("degree", "master"),
              ("english", "required_fluent"), ("work_mode", "remote"), ("work_mode", "hybrid"), ("salary", "amount_given"), ("years_min", "stated"), ("years_min", "median")]

# Display names for two skills whose pipeline labels carry internal ids.
LABEL_OVERRIDES = {"any_ai": "Any AI mention (AI term or generative AI)", "ai_general": "The word AI or artificial intelligence"}

# Plain-English names for themes, keyed by (panel, language, first top term). A theme not listed here is shown as "Theme N".
BOILERPLATE = "One employer's footer text (boilerplate)"
THEME_LABELS = {
    ("P1_us_2022_vs_2026", "en", "status"): ("Equal-opportunity and benefits notices (boilerplate)", True),
    ("P1_us_2022_vs_2026", "en", "analyst"): ("Core analyst work: reports, SQL, Excel", False),
    ("P1_us_2022_vs_2026", "en", "residency"): ("Public-sector residency and degree rules", True),
    ("P1_us_2022_vs_2026", "en", "synchrony"): (BOILERPLATE, True),
    ("P1_us_2022_vs_2026", "en", "media"): (BOILERPLATE, True),
    ("P1_us_2022_vs_2026", "en", "chase"): (BOILERPLATE, True),
    ("P1_us_2022_vs_2026", "en", "google"): (BOILERPLATE, True),
    ("P1_us_2022_vs_2026", "en", "analytics"): ("AI, product and growth analytics", False),
    ("P2_vn_2022_vs_2026", "vi", "nghiệp vụ"): ("Business requirements, documents and project design", False),
    ("P2_vn_2022_vs_2026", "vi", "mb"): ("One bank's recruiting footer (boilerplate)", True),
    ("P2_vn_2022_vs_2026", "vi", "hàng"): ("Banking, risk and operations", False),
    ("P2_vn_2022_vs_2026", "vi", "năng độc"): ("Independent research and learning on the job", False),
    ("P2_vn_2022_vs_2026", "vi", "bán"): ("Sales, revenue and stock reporting", False),
    ("P2_vn_2022_vs_2026", "vi", "xã"): ("Social media and marketing research", False),
    ("P2_vn_2022_vs_2026", "vi", "quả"): ("Insight, statistics and visual explanation", False),
    ("P2_vn_2022_vs_2026", "vi", "số liệu"): ("Checking and reconciling figures", False),
}
# The Vietnamese theme tables are not published (git-ignored), so the page shows the English-text themes only.
THEME_SETS = [("P1_us_2022_vs_2026", "en", "United States, English text")]

VI_LETTERS = re.compile(r"[ăâđêôơưàáảãạèéẻẽẹìíỉĩịòóỏõọùúủũụỳýỷỹỵ]", re.I)

# English glosses for the Vietnamese terms the page shows. Terms without a gloss are left out of the page
# (the Vietnamese tokenizer has no word segmenter, so many top terms are syllable fragments).
GLOSS = {
    "hiệu suất": "performance", "cơ hội": "opportunity", "chuẩn hóa": "standardise", "insight": "insight", "phát hiện": "detect, discover",
    "looker": "Looker (BI tool)", "ra quyết": "decision making", "năng lực": "capability", "chiến dịch": "campaign", "sức khỏe": "health (benefits)",
    "bảo hiểm": "insurance (benefits)", "dashboard": "dashboard", "machine learning": "machine learning", "làm sạch": "data cleaning", "pandas": "pandas (Python library)",
    "api": "APIs", "thạo sql": "fluent in SQL", "excel nâng": "advanced Excel", "phụ cấp": "allowances", "chuyên sâu": "in-depth",
    "cao đẳng": "college diploma", "lập trình": "programming", "spss": "SPSS", "cấp trên": "line manager above you", "ngôn ngữ": "language",
    "trách nhiệm": "responsibility", "thẩm định": "appraisal, review", "trung thực": "honest", "vi tính": "computer skills", "máy tính": "computer",
    "tableau": "Tableau", "studio": "Studio (Looker Studio)", "bi tableau": "BI, Tableau", "làm sạch": "data cleaning",
    "excel spss": "Excel, SPSS", "spss sas": "SPSS, SAS", "trên excel": "in Excel",
}
WORD_SETS = [("P1_us_2022_vs_2026", "en", "United States", "2022", "2026"), ("P2_vn_2022_vs_2026", "vi", "Vietnam (Vietnamese text)", "2022", "2026"),
             ("P3_us_vs_vn_2026", "en", "2026, English text only", "United States", "Vietnam")]

SOURCES = [
    {"name": "US 2022", "what": "\"Data Analyst Job Postings [Pay, Skills, Benefits]\", Luke Barousse (Kaggle)", "licence": "Licence: Apache 2.0.", "url": "https://www.kaggle.com/datasets/lukebarousse/data-analyst-job-postings-google-search"},
    {"name": "US 2026", "what": "publicly available US job postings", "licence": "Local use only; this page shows aggregates."},
    {"name": "Vietnam 2022 and 2026", "what": "\"Vietnamese Job Descriptions\", Tinix (Hugging Face)", "licence": "Licence: CC BY-NC 4.0.", "url": "https://huggingface.co/datasets/tinixai/vietnamese-job-descriptions",
     "cite": "Le, Hoang, Tran, Vuong. CareerPathKG: Knowledge Graph Integrated Framework for Career Intelligence. EACL 2026 Industry Track, pp. 813-822. doi:10.18653/v1/2026.eacl-industry.60."},
    {"name": "Vietnam 2022", "what": "archived Vietnamese portal pages, Internet Archive", "licence": "This page shows aggregates.", "url": "https://archive.org/"},
    {"name": "US same-pipeline check", "what": "datanerd.tech 2025-2026 release, Luke Barousse", "licence": "Skill counts only."},
]


# ------------------------------------------------------------------ readers
def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def num(text: str):
    """A results cell as int or float; '' stays None; 'inf' and 'nan' stay None (JSON has no such value)."""
    if text is None or text == "" or text in ("inf", "nan", "-inf"):
        return None
    f = float(text)
    return int(f) if f.is_integer() and "." not in text and "e" not in text.lower() else f


def parse_range(text: str, sep: str) -> tuple[float | None, float | None]:
    lo, _, hi = text.partition(sep)
    return (float(lo), float(hi)) if lo and hi else (None, None)


def read_groups(path: Path = TAXONOMY) -> dict[str, str]:
    """The `groups:` block of the taxonomy (id: label), without a YAML library."""
    groups, inside = {}, False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("groups:"):
            inside = True
            continue
        if inside:
            m = re.match(r"^  (\w+):\s+(.+?)\s*$", line)
            if not m:
                if line.strip() and not line.startswith(" "):
                    break
                continue
            groups[m.group(1)] = m.group(2)
    return groups


# ------------------------------------------------------------------ builders
def build_data(results: Path = RESULTS) -> dict:
    panels_json = json.loads((results / "panels.json").read_text(encoding="utf-8"))
    meta = json.loads((results / "corpus_meta.json").read_text(encoding="utf-8"))
    groups = read_groups()

    cells = {}
    for cell, info in panels_json["cells"].items():
        place, period, region, note = CELLS[cell]
        cells[cell] = {"n": info["n_docs"], "place": place, "period": period, "region": region, "note": note, "share_vi": info["share_vi"]}

    prev_rows = read_csv(results / "skill_prevalence_by_cell.csv")
    skills, prev = {}, {c: {} for c in cells}
    for r in prev_rows:
        skills.setdefault(r["skill_id"], {"id": r["skill_id"], "label": LABEL_OVERRIDES.get(r["skill_id"], r["label"]), "group": r["group"]})
        prev[r["cell"]][r["skill_id"]] = [num(r["k"]), num(r["rate"]), num(r["wilson_low"]), num(r["wilson_high"])]

    panels = {}
    for name in PANELS:
        spec = panels_json["panels"][name]
        rows = {}
        for r in read_csv(results / f"skill_shift_{name}.csv"):
            wa, wb = parse_range(r["wilson_a"], "-"), parse_range(r["wilson_b"], "-")
            bl, bh = parse_range(r["bootstrap_rd_pp"], " to ")
            rows[r["skill_id"]] = [num(r["rate_a"]), wa[0], wa[1], num(r["rate_b"]), wb[0], wb[1], num(r["risk_difference_pp"]), bl, bh,
                                   num(r["weighted_rd_pp"]), num(r["bh_q"]), 1 if r["significant_q10"] == "True" else 0, num(r["size_matched_share_p_lt_05"])]
        mde = {}
        for r in read_csv(results / "power_check.csv"):
            if r["panel"] == name:
                mde[r["base_rate_a"]] = num(r["min_detectable_increase_pp"])
        panels[name] = {"title": PANEL_TITLES[name], "a": spec["a"], "b": spec["b"], "n_a": spec["n_a"], "n_b": spec["n_b"], "strata": spec["strata"], "mde": mde, "rows": rows}

    trend_rows = read_csv(results / "tinix_vn_yearly_trend.csv")
    years = sorted({r["cell"] for r in trend_rows})
    trend = {"years": years, "n": [num([r for r in trend_rows if r["cell"] == y][0]["n_docs"]) for y in years], "series": {}}
    for sid in TREND_SKILLS:
        by_year = {r["cell"]: num(r["rate"]) for r in trend_rows if r["skill_id"] == sid}
        trend["series"][sid] = [by_year.get(y) for y in years]

    req_rows = read_csv(results / "requirements_by_cell.csv")
    requirements = {}
    for field, value in REQ_FIELDS:
        requirements[f"{field}:{value}"] = {c: next((num(r["rate"]) for r in req_rows if r["cell"] == c and r["field"] == field and r["value"] == value), None)
                                            for c in ("US_2022", "US_2026", "VN_2022", "VN_2026")}

    themes = []
    for panel, lang, title in THEME_SETS:
        spec = panels_json["panels"][panel]
        a, b = spec["a"], spec["b"]
        path = results / f"themes_{lang}_{panel}.csv"
        stab = read_csv(results / f"themes_{lang}_{panel}_stability.csv")[0]
        items = []
        for r in read_csv(path):
            first = r["top_terms"].split(" | ")[0]
            label, boiler = THEME_LABELS.get((panel, lang, first), (f"Theme {r['theme']}", False))
            items.append({"id": int(r["theme"]), "label": label, "boilerplate": boiler, "terms": [] if boiler else r["top_terms"].split(" | ")[:10],
                          "stability": num(r["stability_cosine"]), "share_a": num(r[f"share_dominant_{a}"]), "share_b": num(r[f"share_dominant_{b}"])})
        themes.append({"panel": panel, "language": lang, "title": title, "a": a, "b": b, "n_a": num(r[f"n_docs_{a}"]), "n_b": num(r[f"n_docs_{b}"]),
                       "n_themes": num(stab["k"]), "mean_stability": num(stab["mean_stability"]), "items": items})

    words = []
    word_rows = read_csv(results / "word_log_odds_by_panel.csv")
    for panel, lang, title, name_a, name_b in WORD_SETS:
        spec = panels_json["panels"][panel]
        rows = [r for r in word_rows if r["panel"] == panel and r["language"] == lang]
        def pick(side):
            out = []
            for r in rows:
                if r["side"] != side:
                    continue
                if VI_LETTERS.search(r["term"]) and r["term"] not in GLOSS:
                    continue  # Vietnamese words without a reliable gloss are left out, in any panel
                out.append({"term": r["term"], "gloss": GLOSS.get(r["term"], ""), "docs_a": num(r["docs_a"]), "docs_b": num(r["docs_b"]), "z": num(r["z"])})
                if len(out) == 8:
                    break
            return out
        words.append({"panel": panel, "language": lang, "title": title, "name_a": name_a, "name_b": name_b, "a": spec["a"], "b": spec["b"],
                      "n_a": rows[0]["n_a"] if rows else None, "n_b": rows[0]["n_b"] if rows else None,
                      "more_b": pick(f"more_in_{spec['b']}"), "more_a": pick(f"more_in_{spec['a']}")})

    same = read_csv(results / "us_same_instrument_skills.csv")
    shared = [r for r in same if r["in_2022_vocabulary"] == "True" and r["in_2026_vocabulary"] == "True"][:14]
    only26 = sorted([r for r in same if r["in_2022_vocabulary"] != "True"], key=lambda r: -float(r["rate_2026"]))[:8]
    sm = json.loads((results / "us_same_instrument_meta.json").read_text(encoding="utf-8"))
    same_instrument = {"n_2022": sm["us_2022"]["n_docs"], "n_2026": sm["us_2026"]["n_docs"], "shared_keywords": sm["shared_keywords"],
                       "shared": [{"keyword": r["keyword"], "r22": num(r["rate_2022"]), "r26": num(r["rate_2026"]), "diff_pp": num(r["risk_difference_pp"]), "q": num(r["bh_q_within_shared_vocabulary"])} for r in shared],
                       "only_2026": [{"keyword": r["keyword"], "r26": num(r["rate_2026"])} for r in only26]}

    platform_share = {}
    for r in read_csv(results / "corpus_summary.csv"):
        if r["source"] == "tinix_vn":
            total = num(r["platform_total_postings_that_year"])
            platform_share[r["era"]] = {"n": num(r["n_da_family"]), "total": total, "share": round(num(r["n_da_family"]) / total, 6)}
    funnel = {}
    for s, m in meta["sources"].items():
        funnel[s] = {"raw": m["n_raw"], "exact_duplicates": m["exact_duplicates"], "near_duplicates": m["near_duplicates"], "too_short": m["too_short"]}

    data = {
        "taxonomy_version": panels_json["taxonomy_version"], "cells": cells, "groups": groups, "skills": sorted(skills.values(), key=lambda s: (s["group"], s["label"])),
        "prev": prev, "panels": panels, "trend": trend, "requirements": requirements, "themes": themes, "words": words, "same_instrument": same_instrument,
        "ai_skills": AI_SKILLS, "funnel": funnel, "platform_share": platform_share, "sources": SOURCES, "panel_order": PANELS,
    }
    data["headlines"] = build_headlines(data)
    return data


def stat(data: dict, panel: str, skill: str, label: str | None = None) -> dict:
    row = data["panels"][panel]["rows"][skill]
    return {"panel": panel, "skill": skill, "label": label or next(s["label"] for s in data["skills"] if s["id"] == skill), "a": row[0], "b": row[3], "diff_pp": row[6], "q": row[10], "sig": row[11]}


def build_headlines(data: dict) -> list[dict]:
    """Five headline shifts. The sentences are fixed text; the numbers are looked up from the panels."""
    return [
        {"id": "us-ai", "title": "AI went from a footnote to a headline in US postings",
         "text": "In November and December 2022 almost no US Data Analyst posting mentioned AI. By 2026 four in ten do, and one in five names generative AI or LLM tools.",
         "region": "US", "stats": [stat(data, "P1_us_2022_vs_2026", "any_ai", "Any AI mention"), stat(data, "P1_us_2022_vs_2026", "generative_ai")]},
        {"id": "us-people", "title": "US postings name more than tools: people and judgement",
         "text": "Working with stakeholders, giving recommendations and mentoring others rose by 20 points or more. Dashboards and KPIs rose too.",
         "region": "US", "stats": [stat(data, "P1_us_2022_vs_2026", "stakeholder_management"), stat(data, "P1_us_2022_vs_2026", "insights"), stat(data, "P1_us_2022_vs_2026", "leadership_mentoring"), stat(data, "P1_us_2022_vs_2026", "dashboard")]},
        {"id": "vn-bi", "title": "In Vietnam, dashboards and data quality moved up",
         "text": "Vietnamese postings now name dashboards, Power BI and data quality far more often than in 2022. The 2022 sample is small, so only big shifts can be trusted.",
         "region": "VN", "stats": [stat(data, "P2_vn_2022_vs_2026", "dashboard"), stat(data, "P2_vn_2022_vs_2026", "power_bi"), stat(data, "P2_vn_2022_vs_2026", "data_quality")]},
        {"id": "legacy", "title": "Older statistics tools are fading in both markets",
         "text": "SAS and SPSS or Stata are named less often. In the US, Excel also slipped, but it is still named in about a third of postings.",
         "region": "both", "stats": [stat(data, "P1_us_2022_vs_2026", "sas", "SAS (US)"), stat(data, "P2_vn_2022_vs_2026", "sas", "SAS (Vietnam)"), stat(data, "P2_vn_2022_vs_2026", "spss_stata", "SPSS / Stata (Vietnam)"), stat(data, "P1_us_2022_vs_2026", "excel", "Excel (US)")]},
        {"id": "gap", "title": "In 2026 the two markets still write different postings",
         "text": "Vietnamese postings mention AI less than half as often as US ones, and name English and Power BI more often. This is a difference between markets, not proof that Vietnam is behind in time.",
         "region": "gap", "stats": [stat(data, "P3_us_vs_vn_2026", "any_ai", "Any AI mention"), stat(data, "P3_us_vs_vn_2026", "english"), stat(data, "P3_us_vs_vn_2026", "power_bi")]},
    ]


# ------------------------------------------------------------------ render
def json_for_html(data: dict) -> str:
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return text.replace("</", "<\\/").replace("<!--", "<\\!--").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def pct_text(x: float) -> str:
    return f"{100 * x:.1f} %" if x < 0.1 else f"{100 * x:.0f} %"


def fill(text: str, data: dict) -> str:
    """Replace {{n:CELL}}, {{pct:PANEL:SKILL:a|b}}, {{pp:PANEL:SKILL}} and {{mde:PANEL:RATE}} with numbers from DATA.

    Prose on the page therefore never holds a typed number: each one is looked up."""
    def sub(m: re.Match) -> str:
        kind, *args = m.group(1).split(":")
        if kind == "n":
            return f"{data['cells'][args[0]]['n']:,}"
        if kind == "pct":
            row = data["panels"][args[0]]["rows"][args[1]]
            return pct_text(row[0] if args[2] == "a" else row[3])
        if kind == "pp":
            return f"{abs(data['panels'][args[0]]['rows'][args[1]][6]):.0f}"
        if kind == "mde":
            return f"{data['panels'][args[0]]['mde'][args[1]]:.0f}"
        if kind == "share":
            x = data["platform_share"][args[0]]["share"]
            return f"{100 * x:.3f} %"
        if kind == "ratio":
            return f"{data['platform_share'][args[0]]['share'] / data['platform_share'][args[1]]['share']:.1f}"
        if kind == "total":
            return f"{sum(data['cells'][c]['n'] for c in ('US_2022', 'US_2026', 'VN_2022', 'VN_2026')):,}"
        raise KeyError(m.group(0))
    return re.sub(r"\{\{((?:n|pct|pp|mde|share|ratio|total):[^}]*)\}\}", sub, text)


def render(data: dict, repo_url: str = "") -> str:
    template = fill(TEMPLATE.read_text(encoding="utf-8"), data)
    assert MARK in template, "template has no data marker"
    html = template.replace(MARK, json_for_html(data), 1)
    base = repo_url.rstrip("/") + "/blob/main/" if repo_url else "../"
    name = repo_url.rstrip("/").rsplit("/", 1)[-1] if repo_url else REPO_NAME
    return html.replace("{{REPO}}", base).replace("{{REPO_ROOT}}", repo_url or "..").replace("{{REPO_NAME}}", name)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", default=str(RESULTS))
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--repo-url", default="", help="public repository URL for the links on the page (default: relative links)")
    ap.add_argument("--check", action="store_true", help="fail when the file on disk differs from a fresh build")
    args = ap.parse_args(argv)
    html = render(build_data(Path(args.results)), args.repo_url)
    out = Path(args.out)
    if args.check:
        same = out.exists() and out.read_text(encoding="utf-8") == html
        print("report is up to date" if same else "report differs: rerun scripts/build_report.py")
        return 0 if same else 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out} ({len(html) / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
