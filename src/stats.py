"""Layer 4 library: the statistics used to compare the two eras.

Every function is small, pure, and unit-tested (tests/test_stats.py). The
docstrings say WHY each method is used, because the reader is learning.

Prevalence of a skill in an era is a proportion: k documents mention it out of
n. Comparing two proportions with small n is the whole statistical problem of
this study, so the toolkit is:

* Wilson score interval - a confidence interval for a proportion that behaves
  well when n is small or the rate is near 0 or 1 (the textbook "p +/- 1.96
  sqrt(p(1-p)/n)" interval collapses to zero width when k = 0 and can go below
  0). Wilson (1927); recommended by Brown, Cai and DasGupta (2001).
* Fisher's exact test - tests whether the rate differs between eras using the
  exact hypergeometric distribution of the 2x2 table, so it is valid for the
  tiny cells we have (a chi-square test needs expected counts >= 5).
* Benjamini-Hochberg - we test ~90 skills at once; at alpha = 0.05 about 4 or 5
  would "pass" by chance. BH controls the false discovery rate: among the
  skills we call significant, the expected share of false calls is <= q.
* Log-odds ratio with an informative Dirichlet prior (Monroe, Colaresi and
  Quinn 2008, "Fightin' Words") - for WORDS rather than taxonomy skills. Raw
  log-odds explode for rare words (a word seen 3 times in one era and 0 in the
  other looks infinitely distinctive). The prior adds pseudo-counts in
  proportion to a background corpus, shrinking rare words toward zero, and the
  z-score divides by the estimated standard deviation so words are ranked by
  evidence, not by raw difference.
* Effect sizes - a p-value says "probably not zero"; the reader also needs
  "how big": risk difference (percentage points), risk ratio, odds ratio with a
  Woolf confidence interval, and Cohen's h (difference of arcsine-transformed
  proportions, which is comparable across skills with different base rates).
* Bootstrap - resampling documents with replacement gives a confidence
  interval for any statistic without a formula, and is the honest option when
  the statistic is odd (a median, a ratio) or n is small.
* Cohen's kappa - chance-corrected agreement between two annotators (stage 2).
* Minimum detectable difference - with n1 = 30 and n2 = 100, what change in
  prevalence could this study even see? Reported next to every comparison so
  "not significant" is never read as "no change".
* Post-stratification weights - the 2026 cell has more senior titles and more
  Hanoi postings than the 2022 cell. Part of any raw difference is therefore
  "different mix", not "different role". Reweighting the comparison cell so its
  seniority (and region) mix matches the baseline cell removes that part. It
  is the simplest form of standardisation (direct standardisation in
  epidemiology).
* Size-matched check - when one cell is 50 times larger than the other, the
  test is driven by the small cell. Drawing many random subsamples of the
  large cell at the small cell's size and repeating the test shows how often
  the finding replicates; it protects against reading a lucky draw as a trend.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Iterable, Mapping, Sequence

import numpy as np
from scipy import stats as _sps

Z95 = 1.959963984540054


# ------------------------------------------------------------- proportions
def wilson_interval(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    """Wilson score interval for k successes in n trials. Returns (low, high); (0, 0) when n == 0."""
    if n <= 0:
        return (0.0, 0.0)
    if k < 0 or k > n:
        raise ValueError("k must be between 0 and n")
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def fisher_exact(k1: int, n1: int, k2: int, n2: int) -> tuple[float, float]:
    """Two-sided Fisher exact test on the 2x2 table [[k1, n1-k1], [k2, n2-k2]].

    Returns (conditional odds ratio as scipy reports it, p-value). Rows are
    eras, columns are 'mentions' / 'does not mention'."""
    table = [[k1, n1 - k1], [k2, n2 - k2]]
    odds, p = _sps.fisher_exact(table, alternative="two-sided")
    return float(odds), float(p)


def benjamini_hochberg(pvalues: Sequence[float]) -> list[float]:
    """Benjamini-Hochberg adjusted p-values (q-values), same order as the input.

    q_i = min over j >= rank(i) of (m * p_(j) / j), capped at 1. A skill with
    q <= 0.10 means: if we call every skill with q <= 0.10 'changed', about 10 %
    of those calls are expected to be false."""
    p = np.asarray(pvalues, dtype=float)
    m = len(p)
    if m == 0:
        return []
    order = np.argsort(p)
    ranked = p[order] * m / (np.arange(m) + 1)
    # enforce monotonicity from the largest rank down
    q_sorted = np.minimum.accumulate(ranked[::-1])[::-1]
    q = np.empty(m)
    q[order] = np.minimum(q_sorted, 1.0)
    return [float(x) for x in q]


def risk_difference(k1: int, n1: int, k2: int, n2: int) -> float:
    """p2 - p1 (era 2 minus era 1), in proportion units."""
    return k2 / n2 - k1 / n1


def risk_ratio(k1: int, n1: int, k2: int, n2: int) -> float:
    """p2 / p1. Infinite when p1 == 0 and p2 > 0; nan when both are 0."""
    p1, p2 = k1 / n1, k2 / n2
    if p1 == 0:
        return math.inf if p2 > 0 else math.nan
    return p2 / p1


def odds_ratio_ci(k1: int, n1: int, k2: int, n2: int, z: float = Z95) -> tuple[float, float, float]:
    """Odds ratio (era 2 vs era 1) with Woolf's log-scale interval.

    When any cell is 0 the Haldane-Anscombe correction adds 0.5 to every cell
    so the ratio and interval stay finite; the result is then marked only by
    its width, which is honest about the lack of information."""
    a, b, c, d = k2, n2 - k2, k1, n1 - k1  # era2 mentions, era2 not, era1 mentions, era1 not
    if min(a, b, c, d) == 0:
        a, b, c, d = a + 0.5, b + 0.5, c + 0.5, d + 0.5
    orr = (a * d) / (b * c)
    se = math.sqrt(1 / a + 1 / b + 1 / c + 1 / d)
    return (orr, math.exp(math.log(orr) - z * se), math.exp(math.log(orr) + z * se))


def cohens_h(p1: float, p2: float) -> float:
    """Cohen's h = 2*asin(sqrt(p2)) - 2*asin(sqrt(p1)). Rules of thumb: 0.2 small, 0.5 medium, 0.8 large."""
    return 2 * math.asin(math.sqrt(p2)) - 2 * math.asin(math.sqrt(p1))


@dataclass
class PrevalenceComparison:
    k1: int; n1: int; k2: int; n2: int
    rate1: float; rate2: float
    wilson1_low: float; wilson1_high: float; wilson2_low: float; wilson2_high: float
    risk_difference: float; risk_ratio: float
    odds_ratio: float; odds_ratio_low: float; odds_ratio_high: float
    cohens_h: float; fisher_p: float

    def as_dict(self) -> dict:
        return asdict(self)


def compare_prevalence(k1: int, n1: int, k2: int, n2: int) -> PrevalenceComparison:
    """Everything the results table needs for one skill: rates, Wilson intervals, effect sizes, Fisher p."""
    w1, w2 = wilson_interval(k1, n1), wilson_interval(k2, n2)
    orr, lo, hi = odds_ratio_ci(k1, n1, k2, n2)
    _, p = fisher_exact(k1, n1, k2, n2)
    return PrevalenceComparison(
        k1, n1, k2, n2, k1 / n1, k2 / n2, w1[0], w1[1], w2[0], w2[1],
        risk_difference(k1, n1, k2, n2), risk_ratio(k1, n1, k2, n2), orr, lo, hi, cohens_h(k1 / n1, k2 / n2), p,
    )


# ------------------------------------------------------------- word level
def log_odds_informative_dirichlet(counts_a: Mapping[str, int], counts_b: Mapping[str, int],
                                   prior: Mapping[str, int] | None = None, alpha0: float | None = None) -> dict[str, tuple[float, float, float]]:
    """Monroe, Colaresi and Quinn (2008) log-odds ratio with an informative Dirichlet prior.

    For each word w with counts y_aw, y_bw in the two groups (totals n_a, n_b)
    and prior pseudo-count alpha_w:

        delta_w = log((y_aw + alpha_w) / (n_a + alpha_0 - y_aw - alpha_w))
                - log((y_bw + alpha_w) / (n_b + alpha_0 - y_bw - alpha_w))
        var_w   = 1 / (y_aw + alpha_w) + 1 / (y_bw + alpha_w)
        z_w     = delta_w / sqrt(var_w)

    alpha_w = alpha_0 * prior_w / sum(prior). By default the prior is the two
    groups pooled and alpha_0 = the pooled total (the 'Fightin' Words'
    convention), which shrinks rare words hard and leaves frequent words alone.
    Positive z means the word is more typical of group A. Returns
    {word: (delta, var, z)} for words in either group."""
    if prior is None:
        prior = {w: counts_a.get(w, 0) + counts_b.get(w, 0) for w in set(counts_a) | set(counts_b)}
    prior_total = float(sum(prior.values()))
    if prior_total <= 0:
        raise ValueError("prior must have positive total count")
    if alpha0 is None:
        alpha0 = prior_total
    n_a, n_b = float(sum(counts_a.values())), float(sum(counts_b.values()))
    out = {}
    for w in set(counts_a) | set(counts_b):
        alpha_w = alpha0 * prior.get(w, 0) / prior_total
        if alpha_w <= 0:
            alpha_w = alpha0 / prior_total  # a word absent from the prior gets the smallest pseudo-count
        ya, yb = counts_a.get(w, 0), counts_b.get(w, 0)
        delta = math.log((ya + alpha_w) / (n_a + alpha0 - ya - alpha_w)) - math.log((yb + alpha_w) / (n_b + alpha0 - yb - alpha_w))
        var = 1.0 / (ya + alpha_w) + 1.0 / (yb + alpha_w)
        out[w] = (delta, var, delta / math.sqrt(var))
    return out


# --------------------------------------------------------------- bootstrap
def bootstrap_ci(sample_a: Sequence[float], sample_b: Sequence[float], statistic=None, n_boot: int = 2000,
                 alpha: float = 0.05, seed: int = 0) -> tuple[float, float, float]:
    """Percentile bootstrap interval for statistic(b) - statistic(a) (default: mean difference).

    Documents are resampled with replacement inside each era, the statistic is
    recomputed n_boot times, and the 2.5 % and 97.5 % quantiles are the
    interval. Returns (point estimate, low, high). Deterministic for a given seed."""
    rng = np.random.default_rng(seed)
    a, b = np.asarray(sample_a, dtype=float), np.asarray(sample_b, dtype=float)
    if len(a) == 0 or len(b) == 0:
        raise ValueError("both samples must be non-empty")
    stat = statistic or (lambda x: float(np.mean(x)))
    point = stat(b) - stat(a)
    diffs = np.empty(n_boot)
    for i in range(n_boot):
        diffs[i] = stat(rng.choice(b, len(b), replace=True)) - stat(rng.choice(a, len(a), replace=True))
    lo, hi = np.quantile(diffs, [alpha / 2, 1 - alpha / 2])
    return (float(point), float(lo), float(hi))


# -------------------------------------------------------------- agreement
def cohens_kappa(labels_a: Sequence, labels_b: Sequence) -> float:
    """Cohen's kappa between two annotators' labels for the same items.

    kappa = (p_o - p_e) / (1 - p_e): observed agreement minus the agreement two
    annotators would reach by chance given their own label frequencies.
    Returns 1.0 when both annotators use one identical label throughout
    (perfect agreement with no room for chance correction)."""
    if len(labels_a) != len(labels_b):
        raise ValueError("label sequences must have the same length")
    n = len(labels_a)
    if n == 0:
        raise ValueError("no items")
    po = sum(x == y for x, y in zip(labels_a, labels_b)) / n
    cats = set(labels_a) | set(labels_b)
    pe = sum((list(labels_a).count(c) / n) * (list(labels_b).count(c) / n) for c in cats)
    if pe == 1.0:
        return 1.0
    return (po - pe) / (1 - pe)


# ------------------------------------------------------------ power / MDE
def minimum_detectable_difference(n1: int, n2: int, p1: float, alpha: float = 0.05, power: float = 0.8) -> float:
    """Smallest increase p2 - p1 a two-sided two-proportion z-test can detect with the given power.

    Solved numerically on p2 in (p1, 1). Used in the README's warning section so
    the reader sees, for example, that with 30 vs 100 documents a skill at 20 %
    must roughly double before the test can see it."""
    if not (0 <= p1 < 1):
        raise ValueError("p1 must be in [0, 1)")
    z_a, z_b = _sps.norm.ppf(1 - alpha / 2), _sps.norm.ppf(power)

    def power_at(p2: float) -> float:
        pbar = (n1 * p1 + n2 * p2) / (n1 + n2)
        se0 = math.sqrt(pbar * (1 - pbar) * (1 / n1 + 1 / n2))
        se1 = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
        if se1 == 0:
            return 1.0
        return 1 - _sps.norm.cdf((z_a * se0 - (p2 - p1)) / se1) + _sps.norm.cdf((-z_a * se0 - (p2 - p1)) / se1)

    lo, hi = p1, 1.0 - 1e-9
    if power_at(hi) < power:
        return 1.0 - p1
    for _ in range(60):
        mid = (lo + hi) / 2
        if power_at(mid) >= power:
            hi = mid
        else:
            lo = mid
    return hi - p1


def tokens_to_counts(docs_tokens: Iterable[Iterable[str]]) -> dict[str, int]:
    """Document-frequency counts: each word counted once per document (robust to one long posting)."""
    counts: dict[str, int] = {}
    for toks in docs_tokens:
        for w in set(toks):
            counts[w] = counts.get(w, 0) + 1
    return counts


# ------------------------------------------------ standardisation / matching
def post_stratified_rate(indicator: Sequence[int], strata: Sequence[str], target_shares: Mapping[str, float]) -> tuple[float, float]:
    """Rate of `indicator` in a cell, reweighted so its strata match `target_shares`.

    indicator[i] is 0/1 for document i, strata[i] its stratum label (e.g.
    "senior|VN-HN"). target_shares maps stratum -> share in the baseline
    cell. Strata absent from this cell cannot be weighted and are dropped; the
    second return value is the share of the target distribution that was
    covered (1.0 = every baseline stratum exists in this cell)."""
    if len(indicator) != len(strata):
        raise ValueError("indicator and strata must align")
    by: dict[str, list[int]] = {}
    for x, s in zip(indicator, strata):
        by.setdefault(s, []).append(int(x))
    covered = sum(share for s, share in target_shares.items() if s in by)
    if covered <= 0:
        return (math.nan, 0.0)
    rate = sum(share * (sum(by[s]) / len(by[s])) for s, share in target_shares.items() if s in by) / covered
    return (rate, covered)


def strata_shares(strata: Sequence[str]) -> dict[str, float]:
    """Share of each stratum label in a cell."""
    n = len(strata)
    counts: dict[str, int] = {}
    for s in strata:
        counts[s] = counts.get(s, 0) + 1
    return {s: c / n for s, c in counts.items()} if n else {}


def size_matched_replication(ind_small: Sequence[int], ind_large: Sequence[int], n_rep: int = 200, alpha: float = 0.05, seed: int = 0) -> tuple[float, float, float]:
    """Subsample the large cell to the small cell's size n_rep times.

    Returns (median risk difference large - small, share of replicates with
    Fisher p < alpha, share of replicates where the sign of the difference
    matches the full-sample sign). A finding that holds in most replicates is
    not an artefact of the size imbalance."""
    rng = np.random.default_rng(seed)
    small = np.asarray(ind_small, dtype=int); large = np.asarray(ind_large, dtype=int)
    n = len(small)
    if n == 0 or len(large) == 0:
        raise ValueError("both cells must be non-empty")
    full_sign = np.sign(large.mean() - small.mean())
    diffs, sig, same = [], 0, 0
    k1 = int(small.sum())
    for _ in range(n_rep):
        sub = rng.choice(large, n, replace=False) if len(large) >= n else rng.choice(large, n, replace=True)
        k2 = int(sub.sum())
        diffs.append(k2 / n - k1 / n)
        _, p = fisher_exact(k1, n, k2, n)
        sig += p < alpha
        same += np.sign(k2 / n - k1 / n) == full_sign
    return (float(np.median(diffs)), sig / n_rep, same / n_rep)
