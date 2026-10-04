#!/usr/bin/env python3
"""Layer 4 runner: compare the cells of every panel, write tables and figures.

Design (see extract_deterministic.CELLS / PANELS and the README):
  primary   P1 US 2022 vs US 2026, P2 Vietnam 2022 vs 2026, P3 US vs Vietnam in 2026
  secondary S1 same Vietnamese platform only (no change of portal)

For each panel and each taxonomy skill: prevalence in both cells with Wilson
intervals, Fisher exact p, Benjamini-Hochberg q across the panel's skills,
risk difference, risk ratio, odds ratio with CI, Cohen's h, bootstrap interval
for the risk difference, and two robustness columns:
  * weighted: the comparison cell re-weighted to the baseline cell's seniority
    (and, for Vietnam, region) mix - removes "different mix" from the shift;
  * size-matched: the larger cell subsampled to the smaller cell's size 200
    times - how often the direction and the significance replicate.
Word level: Monroe-Colaresi-Quinn log-odds z-scores for unigrams and bigrams
(document frequency, min 3 documents), top 40 per cell, separately for English
and Vietnamese documents. Power: minimum
detectable increase for each panel's sizes. Figures: dot plots with intervals.

Every output is aggregated (no text beyond single words and word pairs seen in
>= 3 documents) and lives in results/.
Run:  .venv/bin/python src/compare_eras.py --data-root /path/to/data
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
import stats  # noqa: E402
from extract_deterministic import CELLS, PANELS, stratum_of  # noqa: E402
from themes import tokenize  # noqa: E402

TOP_WORDS = 40
MIN_DF_WORDS = 3
N_SIZE_MATCH = 200


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, lineterminator="\n", fieldnames=list(rows[0].keys()) if rows else ["empty"]); w.writeheader(); w.writerows(rows)


def cell_docs(extracted: list[dict], cell: str) -> list[dict]:
    return [r for r in extracted if r["da_family"] == "True" and CELLS[cell](r)]


def skill_comparison(prev_rows: list[dict], extracted: list[dict], panel: str, spec: dict, tax: dict, seed: int = 0) -> list[dict]:
    a, b = spec["a"], spec["b"]
    by_cell = {c: {r["skill_id"]: r for r in prev_rows if r["cell"] == c} for c in (a, b)}
    docs = {c: cell_docs(extracted, c) for c in (a, b)}
    if not docs[a] or not docs[b]:
        return []
    strata = {c: [stratum_of(d, spec["strata"]) for d in docs[c]] for c in (a, b)}
    target = stats.strata_shares(strata[a])
    rows = []
    for skill_id, ra in by_cell[a].items():
        rb = by_cell[b][skill_id]
        k1, n1, k2, n2 = int(ra["k"]), int(ra["n_docs"]), int(rb["k"]), int(rb["n_docs"])
        c = stats.compare_prevalence(k1, n1, k2, n2)
        col = "any_ai" if skill_id == "any_ai" else f"skill__{skill_id}"
        ia = [1 if d[col] == "True" else 0 for d in docs[a]]
        ib = [1 if d[col] == "True" else 0 for d in docs[b]]
        _, blo, bhi = stats.bootstrap_ci(ia, ib, n_boot=500, seed=seed)
        w_rate, coverage = stats.post_stratified_rate(ib, strata[b], target)
        small, large = (ia, ib) if n1 <= n2 else (ib, ia)
        med_rd, p_rep, sign_rep = stats.size_matched_replication(small, large, n_rep=N_SIZE_MATCH, seed=seed)
        if n1 > n2:
            med_rd = -med_rd  # keep the sign as b - a
        rows.append({
            "panel": panel, "cell_a": a, "cell_b": b, "skill_id": skill_id, "group": ra["group"], "label": ra["label"],
            "n_a": n1, "k_a": k1, "rate_a": round(c.rate1, 4), "wilson_a": f"{c.wilson1_low:.3f}-{c.wilson1_high:.3f}",
            "n_b": n2, "k_b": k2, "rate_b": round(c.rate2, 4), "wilson_b": f"{c.wilson2_low:.3f}-{c.wilson2_high:.3f}",
            "risk_difference_pp": round(100 * c.risk_difference, 1), "bootstrap_rd_pp": f"{100 * blo:.1f} to {100 * bhi:.1f}",
            "rate_b_weighted_to_a_mix": round(w_rate, 4) if w_rate == w_rate else "", "weighted_rd_pp": round(100 * (w_rate - c.rate1), 1) if w_rate == w_rate else "",
            "strata_coverage": round(coverage, 2),
            "size_matched_median_rd_pp": round(100 * med_rd, 1), "size_matched_share_p_lt_05": round(p_rep, 2), "size_matched_share_same_sign": round(sign_rep, 2),
            "risk_ratio": "inf" if c.risk_ratio == float("inf") else ("nan" if c.risk_ratio != c.risk_ratio else round(c.risk_ratio, 2)),
            "odds_ratio": round(c.odds_ratio, 2), "odds_ratio_ci": f"{c.odds_ratio_low:.2f}-{c.odds_ratio_high:.2f}",
            "cohens_h": round(c.cohens_h, 2), "fisher_p": f"{c.fisher_p:.4g}",
        })
    q = stats.benjamini_hochberg([float(r["fisher_p"]) for r in rows])
    for r, qq in zip(rows, q):
        r["bh_q"] = f"{qq:.3g}"
        r["significant_q10"] = qq <= 0.10
    rows.sort(key=lambda r: float(r["bh_q"]))
    return rows


def word_log_odds(corpus_docs: list[dict], spec: dict, panel: str) -> list[dict]:
    """Top words per cell, computed separately per language: comparing Vietnamese
    documents with English ones would only rank function words of each language."""
    rows = []
    for lang in ("en", "vi"):
        rows += _word_log_odds_lang(corpus_docs, spec, panel, lang)
    return rows


def _word_log_odds_lang(corpus_docs: list[dict], spec: dict, panel: str, lang: str) -> list[dict]:
    a, b = spec["a"], spec["b"]
    groups = {c: [d for d in corpus_docs if d["da_family"] and d["language"] == lang and CELLS[c](d)] for c in (a, b)}
    if min(len(g) for g in groups.values()) < 5:
        return []

    def counts(docs):
        toks = []
        for d in docs:
            t = tokenize(f"{d['title']}\n{d['text']}")
            toks.append(set(t) | {" ".join(p) for p in zip(t, t[1:])})
        return stats.tokens_to_counts(toks)

    ca, cb = counts(groups[a]), counts(groups[b])
    pooled = collections.Counter(ca) + collections.Counter(cb)
    from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
    stop = set(common.load_stopwords_vi()) | set(ENGLISH_STOP_WORDS)
    vocab = {w for w, n in pooled.items() if n >= MIN_DF_WORDS and len(w) > 2 and not all(part in stop for part in w.split())}
    lo = stats.log_odds_informative_dirichlet({w: cb.get(w, 0) for w in vocab}, {w: ca.get(w, 0) for w in vocab})
    ranked = sorted(lo.items(), key=lambda kv: (kv[1][2], kv[0]))  # ties broken by the term, so a rerun gives the same table
    rows = []
    for side, items in ((f"more_in_{b}", ranked[::-1][:TOP_WORDS]), (f"more_in_{a}", ranked[:TOP_WORDS])):
        for w, (delta, var, z) in items:
            rows.append({"panel": panel, "language": lang, "side": side, "term": w, "docs_a": ca.get(w, 0), "n_a": len(groups[a]), "docs_b": cb.get(w, 0), "n_b": len(groups[b]),
                         "log_odds_delta": round(delta, 3), "z": round(z, 2)})
    return rows


def power_rows(panel_meta: dict) -> list[dict]:
    rows = []
    for panel, m in panel_meta.items():
        n1, n2 = m["n_a"], m["n_b"]
        if min(n1, n2) == 0:
            continue
        for p1 in (0.05, 0.20, 0.50):
            rows.append({"panel": panel, "cell_a": m["a"], "n_a": n1, "cell_b": m["b"], "n_b": n2, "base_rate_a": p1,
                         "min_detectable_increase_pp": round(100 * stats.minimum_detectable_difference(n1, n2, p1), 1)})
    return rows


def draw_figures(comp: dict[str, list[dict]], trend: list[dict], results: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # same bytes on every run: no creation date, fixed id salt
    matplotlib.rcParams["svg.hashsalt"] = "da-job-shift"
    matplotlib.rcParams["svg.fonttype"] = "path"

    figs = results / "figures"; figs.mkdir(exist_ok=True)
    for panel, rows in comp.items():
        top = sorted(rows, key=lambda r: abs(float(r["risk_difference_pp"])), reverse=True)[:20]
        top = sorted(top, key=lambda r: float(r["risk_difference_pp"]))
        fig, ax = plt.subplots(figsize=(8, 7))
        for i, r in enumerate(top):
            loa, hia = map(float, r["wilson_a"].split("-")); lob, hib = map(float, r["wilson_b"].split("-"))
            ax.plot([100 * loa, 100 * hia], [i - 0.15, i - 0.15], color="#888", lw=1)
            ax.plot([100 * lob, 100 * hib], [i + 0.15, i + 0.15], color="#1f77b4", lw=1)
            ax.plot(100 * float(r["rate_a"]), i - 0.15, "o", color="#888", ms=5)
            ax.plot(100 * float(r["rate_b"]), i + 0.15, "o", color="#1f77b4", ms=5)
        ax.set_yticks(range(len(top))); ax.set_yticklabels([f"{r['label'][:38]}{' *' if r['significant_q10'] else ''}" for r in top], fontsize=8)
        ax.set_xlabel("% of postings mentioning (dots) with 95 % Wilson interval (bars)")
        ax.set_title(f"{panel}: grey = {top[0]['cell_a']} (n={top[0]['n_a']}), blue = {top[0]['cell_b']} (n={top[0]['n_b']})\n* = Benjamini-Hochberg q <= 0.10", fontsize=9)
        ax.grid(axis="x", alpha=0.3); fig.tight_layout(); fig.savefig(figs / f"prevalence_{panel}.svg", metadata={"Date": None}); plt.close(fig)
    if trend:
        years = sorted({r["cell"] for r in trend})
        by_skill = collections.defaultdict(dict)
        for r in trend:
            by_skill[r["skill_id"]][r["cell"]] = (float(r["rate"]) if r["rate"] else 0.0, r["label"])
        latest = years[-1]
        chosen = sorted(by_skill, key=lambda s: -abs(by_skill[s].get(latest, (0, ""))[0] - by_skill[s].get(years[0], (0, ""))[0]))[:12]
        fig, ax = plt.subplots(figsize=(8, 5))
        for s in chosen:
            ax.plot(years, [100 * by_skill[s].get(y, (0, ""))[0] for y in years], marker="o", lw=1.2, label=by_skill[s][latest][1][:30] if latest in by_skill[s] else s)
        ax.set_ylabel("% of Data-Analyst-family postings"); ax.set_title("Vietnamese platform, year by year: 12 skills with the largest change", fontsize=9)
        ax.legend(fontsize=7, ncol=2); ax.grid(alpha=0.3); fig.tight_layout(); fig.savefig(figs / "tinix_vn_trend.svg", metadata={"Date": None}); plt.close(fig)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-root", help="default: $DAJS_DATA_DIR or ./data"); ap.add_argument("--results-dir", default=str(common.RESULTS_DIR))
    args = ap.parse_args(argv)
    root = common.data_root(args.data_root); results = Path(args.results_dir)
    tax = common.load_taxonomy()
    prev = read_csv(results / "skill_prevalence_by_cell.csv")
    extracted = read_csv(common.corpus_dir(root) / "extracted.csv")
    corpus = [json.loads(l) for l in (common.corpus_dir(root) / "corpus.jsonl").open(encoding="utf-8")]
    panel_meta = json.loads((results / "panels.json").read_text(encoding="utf-8"))["panels"]
    comp, words = {}, []
    for panel, spec in PANELS.items():
        rows = skill_comparison(prev, extracted, panel, spec, tax)
        if rows:
            comp[panel] = rows
            write_csv(results / f"skill_shift_{panel}.csv", rows)
            sig = [r for r in rows if r["significant_q10"]]
            print(f"{panel}: {spec['a']} n={rows[0]['n_a']} vs {spec['b']} n={rows[0]['n_b']}: {len(sig)} of {len(rows)} skills with BH q<=0.10")
        words += word_log_odds(corpus, spec, panel)
    write_csv(results / "word_log_odds_by_panel.csv", words)
    write_csv(results / "power_check.csv", power_rows(panel_meta))
    trend_path = results / "tinix_vn_yearly_trend.csv"
    trend = read_csv(trend_path) if trend_path.exists() and trend_path.stat().st_size else []
    draw_figures(comp, trend, results)
    print(f"written: skill_shift_*.csv, word_log_odds_by_panel.csv, power_check.csv, figures/ -> {results}")


if __name__ == "__main__":
    main()
