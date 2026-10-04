#!/usr/bin/env python3
"""Robustness check: US 2022 vs US 2026 inside ONE collection instrument.

Problem it answers. The main US comparison (panel P1) sets a 2022 Google Jobs
set against a 2026 set from a different open source, so platform differences
could masquerade as change over time. Luke Barousse's datanerd.tech pipeline
collected both eras the same way (US postings for "Data Analyst") and ships its OWN skill extraction for both: the
2022 Kaggle file carries `description_tokens`, the 2025-2026 release carries
`raw_job_skills.parquet`. The 2026 release has no description text, so this
check works at the skill level only, and only for keywords that exist in BOTH
of the author's vocabularies (105 keywords in 2022, about 340 in 2026; the
2026 list adds ChatGPT, Copilot, Claude and other tools that did not exist in
2022, so those are reported separately as "not in the 2022 vocabulary").

Selection is the same as everywhere else in the lab: Data Analyst family title
(common.is_da_family), United States search location, one row per job id.

Output: results/us_same_instrument_skills.csv (keyword, both rates
with Wilson intervals, Fisher p, BH q, risk difference) and
us_same_instrument_meta.json (sizes, months, vocabulary sizes).
Run:  .venv/bin/python src/us_instrument_check.py --data-root /path/to/data
"""
from __future__ import annotations

import argparse
import ast
import collections
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
import stats  # noqa: E402

MIN_DOCS_EITHER_ERA = 10


def load_2022(path: Path) -> tuple[list[set[str]], dict]:
    import pandas as pd

    g = pd.read_csv(path, low_memory=False, usecols=["job_id", "title", "date_time", "description_tokens"])
    g["date_time"] = pd.to_datetime(g["date_time"], errors="coerce")
    g = g[g["date_time"].dt.year == 2022].drop_duplicates("job_id")
    g = g[[common.is_da_family(t) for t in g["title"].fillna("").astype(object)]]
    docs = []
    for x in g["description_tokens"]:
        try:
            docs.append({str(t).lower().strip() for t in ast.literal_eval(x)} if isinstance(x, str) and x.startswith("[") else set())
        except (ValueError, SyntaxError):
            docs.append(set())
    return docs, {"n_docs": len(docs), "months": sorted(g["date_time"].dt.strftime("%Y-%m").unique().tolist())}


def load_2026(raw_dir: Path) -> tuple[list[set[str]], dict]:
    import pandas as pd

    frames = [pd.read_parquet(f, columns=["job_id", "job_title", "search_location", "search_date", "error"]) for f in sorted(raw_dir.glob("raw_job_postings_2026-*.parquet"))]
    p = pd.concat(frames, ignore_index=True)
    p = p[(p["error"] != True) & p["job_id"].notna()]  # noqa: E712
    p = p[p["search_location"].fillna("").str.endswith("United States")].drop_duplicates("job_id")
    p = p[[common.is_da_family(t) for t in p["job_title"].fillna("").astype(object)]]
    skills = pd.read_parquet(raw_dir / "raw_job_skills.parquet")
    skills = skills[skills["job_id"].isin(set(p["job_id"]))]
    by_job = skills.groupby("job_id")["skill_keyword"].apply(lambda s: {str(x).lower().strip() for x in s}).to_dict()
    docs = [by_job.get(j, set()) for j in p["job_id"]]
    return docs, {"n_docs": len(docs), "months": sorted(p["search_date"].astype(str).str[:7].unique().tolist()), "n_docs_with_any_skill": sum(1 for d in docs if d)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-root", help="default: $DAJS_DATA_DIR or ./data"); ap.add_argument("--results-dir", default=str(common.RESULTS_DIR))
    args = ap.parse_args(argv)
    raw = common.raw_dir(common.data_root(args.data_root)); results = Path(args.results_dir); results.mkdir(parents=True, exist_ok=True)
    from build_corpus import find_gsearch_csv

    d22, m22 = load_2022(find_gsearch_csv(raw / "gsearch_jobs_us_2022"))
    d26, m26 = load_2026(raw / "datanerd_us_2025_2026")
    c22, c26 = stats.tokens_to_counts(d22), stats.tokens_to_counts(d26)
    vocab22, vocab26 = set(c22), set(c26)
    rows = []
    for kw in sorted(vocab22 | vocab26):
        k1, k2 = c22.get(kw, 0), c26.get(kw, 0)
        if max(k1, k2) < MIN_DOCS_EITHER_ERA:
            continue
        c = stats.compare_prevalence(k1, len(d22), k2, len(d26))
        rows.append({"keyword": kw, "in_2022_vocabulary": kw in vocab22, "in_2026_vocabulary": kw in vocab26,
                     "n_2022": len(d22), "k_2022": k1, "rate_2022": round(c.rate1, 4), "wilson_2022": f"{c.wilson1_low:.3f}-{c.wilson1_high:.3f}",
                     "n_2026": len(d26), "k_2026": k2, "rate_2026": round(c.rate2, 4), "wilson_2026": f"{c.wilson2_low:.3f}-{c.wilson2_high:.3f}",
                     "risk_difference_pp": round(100 * c.risk_difference, 1), "odds_ratio": round(c.odds_ratio, 2), "cohens_h": round(c.cohens_h, 2), "fisher_p": f"{c.fisher_p:.4g}"})
    both = [r for r in rows if r["in_2022_vocabulary"] and r["in_2026_vocabulary"]]
    q = stats.benjamini_hochberg([float(r["fisher_p"]) for r in both])
    qmap = {r["keyword"]: qq for r, qq in zip(both, q)}
    for r in rows:
        r["bh_q_within_shared_vocabulary"] = f"{qmap[r['keyword']]:.3g}" if r["keyword"] in qmap else ""
    rows.sort(key=lambda r: (not (r["in_2022_vocabulary"] and r["in_2026_vocabulary"]), -abs(float(r["risk_difference_pp"]))))
    with (results / "us_same_instrument_skills.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, lineterminator="\n", fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    meta = {"source": "datanerd.tech pipeline, author's skill extraction", "us_2022": m22, "us_2026": m26,
            "vocabulary_2022": len(vocab22), "vocabulary_2026": len(vocab26), "shared_keywords": len(vocab22 & vocab26), "keywords_reported": len(rows),
            "note": "2026-only keywords (e.g. chatgpt, copilot, claude) cannot be compared: the 2022 extractor had no such keyword, so 0 in 2022 is by construction."}
    (results / "us_same_instrument_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"US same-instrument check: 2022 n={len(d22)} ({m22['months'][0]}..{m22['months'][-1]}), 2026 n={len(d26)} ({m26['months'][0]}..{m26['months'][-1]}); shared keywords {len(vocab22 & vocab26)}; rows {len(rows)}")
    for r in rows[:12]:
        print(f"  {r['keyword']:14} {r['rate_2022']:.3f} -> {r['rate_2026']:.3f}  q={r['bh_q_within_shared_vocabulary']}")


if __name__ == "__main__":
    main()
