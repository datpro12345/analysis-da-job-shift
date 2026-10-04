#!/usr/bin/env python3
"""Layer 5: unsupervised view - TF-IDF + NMF themes, compared across eras.

Why this layer exists
---------------------
Layers 2 to 4 only count what we already knew to look for (the taxonomy). An
unsupervised pass lets the postings group themselves, so a theme we did not
anticipate ("data mesh / analytics engineering", "AI-driven products") can
surface. It is exploratory: it suggests, the taxonomy and stage 2 confirm.

Method
------
1. Documents of the chosen panel's two cells are split by language (English
   and Vietnamese vocabularies do not mix in one topic model); only
   Data-Analyst-family titles are used.
2. TF-IDF with unigrams and bigrams, sub-linear term frequency, min_df = 3
   documents (a term in fewer documents cannot define a theme and could be a
   name), max_df = 0.8 (a term in 80 % of documents says nothing). English
   stop words from scikit-learn; Vietnamese syllable stop words from
   taxonomy/stopwords_vi.txt. Tokens with digits are dropped (salaries,
   phone fragments, years).
3. NMF (non-negative matrix factorisation) with K themes. NMF was chosen over
   LDA because it works well on TF-IDF for short documents and gives
   additive, readable term weights; K is a free choice, so the script also
   reports a STABILITY score: the model is refitted with 3 random seeds and
   each theme is matched to its closest theme in the other fits (cosine of
   term vectors). Themes that do not reappear across seeds are noise.
4. For each theme: top terms, mean theme weight per cell, and the share of
   documents in each cell whose dominant theme it is. The contrast between
   the two cells is the finding; the rest is description.

Outputs: results/themes_<lang>[_<panel>].csv and the matching _stability.csv.
Run:  .venv/bin/python src/themes.py --data-root /path/to/data --panel P2_vn_2022_vs_2026 [--k 8]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

TOKEN = re.compile(r"(?u)\b[^\W\d_][^\W\d_]+\b")  # letters only, 2+ chars, Unicode aware


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in TOKEN.findall(common.normalize_text(text))]


def fit_nmf(matrix, k: int, seed: int):
    from sklearn.decomposition import NMF

    model = NMF(n_components=k, init="nndsvda", random_state=seed, max_iter=600)
    doc_topic = model.fit_transform(matrix)
    return model, doc_topic


def stability(components: list[np.ndarray]) -> list[float]:
    """For each theme of fit 0, the mean best-match cosine against the other fits."""
    base = components[0]
    base_n = base / (np.linalg.norm(base, axis=1, keepdims=True) + 1e-12)
    scores = np.zeros(base.shape[0])
    for other in components[1:]:
        other_n = other / (np.linalg.norm(other, axis=1, keepdims=True) + 1e-12)
        scores += (base_n @ other_n.T).max(axis=1)
    return [float(s / max(1, len(components) - 1)) for s in scores]


def run_language(docs: list[dict], lang: str, k: int, results: Path, seeds=(0, 1, 2), top_terms: int = 15, suffix: str = "") -> None:
    from sklearn.feature_extraction.text import TfidfVectorizer, ENGLISH_STOP_WORDS

    texts = [f"{d['title']}\n{d['text']}" for d in docs]
    eras = np.array([d["cell"] for d in docs])
    if len(texts) < max(20, 2 * k):
        print(f"{lang}: only {len(texts)} documents, skipping themes"); return
    stop = list(ENGLISH_STOP_WORDS) + common.load_stopwords_vi() + ["experience", "work", "working", "team", "company", "job", "skills", "skill", "year", "years", "kinh", "nghiệm"]
    vec = TfidfVectorizer(tokenizer=tokenize, token_pattern=None, lowercase=False, ngram_range=(1, 2), min_df=3, max_df=0.8, sublinear_tf=True, stop_words=stop)
    X = vec.fit_transform(texts)
    terms = np.array(vec.get_feature_names_out())
    fits = [fit_nmf(X, k, s) for s in seeds]
    model, W = fits[0]
    stab = stability([m.components_ for m, _ in fits])
    dominant = W.argmax(axis=1)
    rows = []
    for t in range(k):
        top = terms[np.argsort(model.components_[t])[::-1][:top_terms]]
        row = {"language": lang, "theme": t, "top_terms": " | ".join(top), "stability_cosine": round(stab[t], 3)}
        for era in sorted(set(eras)):
            mask = eras == era
            row[f"mean_weight_{era}"] = round(float(W[mask, t].mean()), 4)
            row[f"share_dominant_{era}"] = round(float((dominant[mask] == t).mean()), 4)
            row[f"n_docs_{era}"] = int(mask.sum())
        rows.append(row)
    out = results / f"themes_{lang}{suffix}.csv"
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, lineterminator="\n", fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    with (results / f"themes_{lang}{suffix}_stability.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n"); w.writerow(["language", "k", "seeds", "mean_stability", "min_stability", "n_docs", "vocab_size"])
        w.writerow([lang, k, " ".join(map(str, seeds)), round(float(np.mean(stab)), 3), round(float(np.min(stab)), 3), len(texts), len(terms)])
    print(f"{lang}: {len(texts)} docs, vocab {len(terms)}, k={k}, mean stability {np.mean(stab):.2f} -> {out}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-root", help="default: $DAJS_DATA_DIR or ./data"); ap.add_argument("--results-dir", default=str(common.RESULTS_DIR))
    ap.add_argument("--k", type=int, default=8, help="number of themes per language")
    ap.add_argument("--panel", default="P2_vn_2022_vs_2026", help="a panel name from extract_deterministic.PANELS; documents are labelled by the panel's two cells")
    args = ap.parse_args(argv)
    root = common.data_root(args.data_root); results = Path(args.results_dir); results.mkdir(parents=True, exist_ok=True)
    from extract_deterministic import CELLS, PANELS

    spec = PANELS[args.panel]
    docs = [json.loads(l) for l in (common.corpus_dir(root) / "corpus.jsonl").open(encoding="utf-8")]
    labelled = []
    for d in docs:
        if not d["da_family"]:
            continue
        for cell in (spec["a"], spec["b"]):
            if CELLS[cell](d):
                labelled.append({**d, "cell": cell}); break
    for lang in ("en", "vi"):
        run_language([d for d in labelled if d["language"] == lang], lang, args.k, results, suffix=f"_{args.panel}")


if __name__ == "__main__":
    main()
