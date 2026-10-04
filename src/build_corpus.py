#!/usr/bin/env python3
"""Layer 1: build one clean, deduplicated, era-labelled corpus from every source.

Method, in plain words
----------------------
A corpus is only comparable across time when every document went through the
same cleaning. This script therefore reads each source with a small loader
(they differ in format) and then pushes every document through ONE pipeline:

1. normalise text (Unicode NFC, whitespace) and strip personal data
   (e-mails, phones, chat handles, "Contact: Ms X" lines) - see common.py;
2. drop exact duplicates, then remove boilerplate by FREQUENCY: a line of 20+ characters that appears in at
   least 3 documents AND at least 5 % of the documents of the same source is
   company or platform boilerplate (EEO notice, "apply now" footer, a bank's
   "about us"), not a statement about the role. A frequency rule is used
   instead of a hand-written list so that the rule is identical for every
   source and auditable (the removed lines are counted in the meta file);
3. de-duplicate: exact (same cleaned text, removed BEFORE the boilerplate
   count so a re-post cannot push its own lines over the threshold) and
   near-exact (Jaccard similarity of word 5-shingles >= 0.8 inside the same
   source and company) - re-posts and multi-city copies of one advert would
   otherwise count several times;
4. label: era ("2022", "2026", or the posting year for trend data), source,
   language (vi/en), region, and whether the TITLE puts the job in the Data
   Analyst family (common.is_da_family). Adjacent roles (data engineer, data
   scientist) also talk about SQL and dashboards, so the title decides and the
   flag is kept rather than dropping rows, so the choice can be revisited;
5. write comparability checks (sizes, text length, language and region mix,
   per source and era) to results/corpus_summary.csv. These are the
   numbers the small-sample warning in the README is built from.

Outputs (under the data root, never in git): corpus/corpus.jsonl (one JSON
object per document), corpus/corpus_meta.json (counts, removed boilerplate
lines, duplicate counts). Only the aggregates in results/ are committed.

Only public downloads are read (see DATA_SOURCES.md). Nothing collected by
hand is part of this pipeline.

Data root layout (see common.data_root; scripts/fetch_data.py creates it):
  raw/tinixai_vietnamese_job_descriptions/data.parquet
  raw/gsearch_jobs_us_2022/gsearch_jobs_2022.csv  (or gsearch_jobs_hf_mirror.csv)
  raw/us_job_postings_2026/jobs_2026_MM.parquet
  raw/wayback_vn_2022/manifest.csv + <site>/*.html
Run:  .venv/bin/python src/build_corpus.py --data-root /path/to/data
"""
from __future__ import annotations

import argparse
import collections
import csv
import gzip
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

BOILERPLATE_MIN_DOCS = 3
BOILERPLATE_MIN_SHARE = 0.05
BOILERPLATE_MIN_CHARS = 20
NEAR_DUP_JACCARD = 0.8
MIN_TEXT_CHARS = 200  # shorter "postings" are stubs or teasers, not job descriptions


# ------------------------------------------------------------------ loaders
def _text(value) -> str:
    """A pandas cell as text: None, NaN and pandas NA become "" (otherwise the
    literal word "nan" ends up in the corpus and in the word tables)."""
    if value is None:
        return ""
    try:
        if value != value:  # NaN
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value)
    return "" if text in ("nan", "<NA>", "None", "NaT") else text


GSEARCH_FILES = ("gsearch_jobs_2022.csv", "gsearch_jobs_hf_mirror.csv")


def find_gsearch_csv(folder: Path) -> Path:
    """The US 2022 file: the 2022 split if present, else the full mirror (both hold the same 2022 rows)."""
    for name in GSEARCH_FILES:
        if (folder / name).exists():
            return folder / name
    raise FileNotFoundError(folder)


def load_gsearch_us(csv_path: Path, year: int = 2022):
    """Luke Barousse's Google-search 'data analyst' postings (US). Keep one year."""
    import pandas as pd

    wanted = {"title", "company_name", "location", "job_location", "description", "date_time", "via", "work_from_home", "salary"}
    df = pd.read_csv(csv_path, low_memory=False, usecols=lambda c: c in wanted)
    if "location" not in df.columns:  # the 2022 split names the column job_location
        df = df.rename(columns={"job_location": "location"})
    df["date_time"] = pd.to_datetime(df["date_time"], errors="coerce")
    df = df[df["date_time"].dt.year == year]
    for row in df.itertuples(index=False):
        yield {
            "source": "gsearch_us_2022", "era": str(year), "posted_year": year,
            "title": _text(row.title), "company": _text(row.company_name), "location": _text(row.location),
            "region": "US", "work_mode_declared": "remote" if row.work_from_home is True else "", "url": "",
            "text": _text(row.description),
        }


US_STATES = set("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split())
US_METRO = re.compile(r"(united states|\busa\b|new york city metropolitan|san francisco bay area|washington dc-baltimore|los angeles metropolitan|greater (?:chicago|boston|seattle|houston|philadelphia|phoenix|minneapolis|pittsburgh|st\. louis|sacramento|orlando|tampa|cleveland|indianapolis|milwaukee|richmond|hartford|madison|boise)|dallas-fort worth|atlanta metropolitan|denver metropolitan|miami-fort lauderdale|austin, texas metropolitan|raleigh-durham|salt lake city metropolitan|portland, oregon metropolitan|san diego metropolitan|las vegas metropolitan|cincinnati metropolitan|kansas city metropolitan|columbus, ohio metropolitan|nashville metropolitan|charlotte metro|detroit metropolitan|omaha metropolitan|oklahoma city metropolitan|louisville metropolitan)", re.I)


def is_us_location(location: str) -> bool:
    """LinkedIn-style free-text location -> is it in the United States?

    True for "City, ST" with a real state code, "United States"/"USA", or a US
    metro phrase. "Remote" alone is NOT enough (country unknown) and such rows
    are left out of the US cell; the count is reported in the meta file."""
    loc = (location or "").strip()
    m = re.search(r",\s*([A-Z]{2})$", loc)
    if m and m.group(1) in US_STATES:
        return True
    return bool(US_METRO.search(loc))


def load_us_open_2026(md_dir: Path, year: int = 2026):
    """Open US job-postings set (data-role titles, 2025-2026, full text).
    Only rows whose free-text location resolves to the United States are kept."""
    import pandas as pd

    files = sorted(md_dir.glob(f"jobs_{year}_*.parquet"))
    if not files:
        raise FileNotFoundError(md_dir)
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    df["listed_date"] = pd.to_datetime(df["listed_date"], errors="coerce")
    df = df[df["listed_date"].dt.year == year]
    locs = df["location"].fillna("").astype(object).tolist()
    keep = [is_us_location(l) for l in locs]
    n_remote_unknown = sum(1 for l, k in zip(locs, keep) if not k and re.search(r"remote", l, re.I))
    sub = df[keep]
    for row in sub.itertuples(index=False):
        yield {
            "source": f"us_open_{year}", "era": str(year), "posted_year": year,
            "title": _text(row.title), "company": "", "location": _text(row.location), "region": "US",
            "work_mode_declared": "", "url": "", "text": _text(row.description),
        }
    return {"rows_in_year": int(len(df)), "rows_us": int(len(sub)), "rows_remote_country_unknown": n_remote_unknown}


def load_tinix_vn(parquet_path: Path):
    """Tinix Vietnamese postings 2022-2026. Only Data-Analyst-family TITLES are
    kept (the file has 600k rows); totals per year are returned separately so
    the share of DA postings among all postings can still be reported."""
    import pandas as pd

    df = pd.read_parquet(parquet_path)
    totals = df["year"].value_counts().to_dict()
    titles = df["job_title"].fillna("").astype(object).tolist()
    keep = [common.is_da_family(t) for t in titles]
    sub = df[keep]
    for row in sub.itertuples(index=False):
        req = _text(row.requirements)
        parts = [_text(row.job_description), "Yêu cầu ứng viên:\n" + req if req else ""]
        yield {
            "source": "tinix_vn", "era": str(int(row.year)), "posted_year": int(row.year),
            "title": _text(row.job_title), "company": _text(row.company_name), "location": _text(row.location),
            "region": "VN", "work_mode_declared": _text(row.job_type), "url": "",
            "declared_experience": _text(row.experience_level), "declared_position": _text(row.job_position),
            "declared_education": _text(row.education_level), "declared_salary": _text(row.salary),
            "text": "\n".join(p for p in parts if p),
        }
    return totals


class _TextExtractor(HTMLParser):
    """HTML -> text with line breaks at block elements; scripts and styles dropped."""
    BLOCK = {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article", "ul", "ol", "header", "footer", "td"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self._skip, self.title = [], 0, ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "svg"):
            self._skip += 1
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg") and self._skip:
            self._skip -= 1
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_title:
            self.title += data
        self.parts.append(data)


START_MARK = re.compile(r"(mô tả công việc|job description|trách nhiệm công việc|responsibilities|what you will do)", re.I)
END_MARK = re.compile(r"(quyền lợi|phúc lợi|benefits?\b|cách thức ứng tuyển|địa điểm làm việc|thông tin khác|báo cáo tin|việc làm tương tự|similar jobs|ứng tuyển ngay|apply now|chia sẻ|share this job|nộp hồ sơ|hạn nộp)", re.I)
VN_PLACE = re.compile(r"(việt nam|vietnam|viet nam|hồ chí minh|ho chi minh|hcm|hà nội|ha noi|hanoi|đà nẵng|da nang|bình dương|đồng nai|cần thơ|hải phòng)", re.I)


LOCATION_MARK = re.compile(r"(địa điểm làm việc|nơi làm việc|work location|location)\s*:?\s*", re.I)
VN_CITY = re.compile(r"(hồ chí minh|ho chi minh|hcm|hà nội|ha noi|hanoi|đà nẵng|da nang|bình dương|binh duong|đồng nai|dong nai|cần thơ|can tho|hải phòng|hai phong|việt nam|vietnam|viet nam)", re.I)


def html_to_job_text(html: str) -> tuple[str, str, bool, str]:
    """Return (title, job text, mentions_vietnam, location_hint) from an archived job page.

    The job text is the span from the first duties heading to the first
    footer-like heading after it; when no heading is found the longest run of
    non-empty lines is used instead (works for pages that render the posting
    as one block). The location hint is the text right after a "location"
    label, so the region can be decided from the page rather than assumed."""
    p = _TextExtractor()
    try:
        p.feed(html)
    except Exception:  # malformed archive HTML: fall back to a crude strip
        text = re.sub(r"<[^>]+>", "\n", html)
        p.parts = [text]
    text = common.normalize_text("".join(p.parts))
    m = START_MARK.search(text)
    body = ""
    if m:
        rest = text[m.start():]
        e = END_MARK.search(rest, pos=200)
        body = rest[: e.start()] if e else rest[:8000]
    if len(body) < MIN_TEXT_CHARS:
        runs, cur = [], []
        for line in text.split("\n"):
            if line.strip():
                cur.append(line)
            else:
                runs.append(cur); cur = []
        runs.append(cur)
        body = "\n".join(max(runs, key=lambda r: sum(len(x) for x in r)) if runs else [])
    title = common.normalize_text(p.title.split("|")[0].split(" - ")[0]) if p.title else ""
    lm = LOCATION_MARK.search(text)
    hint = text[lm.end(): lm.end() + 80].split("\n")[0] if lm else ""
    return title, body, bool(VN_PLACE.search(text)), hint


def load_wayback_vn(wb_dir: Path):
    """Archived 2022 Vietnamese job pages fetched from the Wayback Machine (manifest.csv + html)."""
    man = wb_dir / "manifest.csv"
    if not man.exists():
        return
    with man.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if str(row.get("http_status")) != "200":
                continue
            path = wb_dir / row["file"]
            if not path.exists():
                continue
            raw = path.read_bytes()
            if raw[:2] == b"\x1f\x8b":  # some archived responses are stored gzip-encoded
                try:
                    raw = gzip.decompress(raw)
                except OSError:
                    continue
            html = raw.decode("utf-8", errors="replace")
            if row["site"] == "vietnamworks" and not row["original_url"].split("?")[0].endswith("-jd"):
                continue  # "-kw"/"-kv" pages are keyword search listings, not postings
            if row["site"] == "glints":
                # Glints renders the posting client-side (Draft.js JSON inside
                # __NEXT_DATA__) and the /vn/ path also lists Indonesian and
                # Taiwanese jobs; 29 pages were fetched, none is used. See
                # DATA_SOURCES.md.
                continue
            title, body, in_vn, location = html_to_job_text(html)
            in_vn = in_vn or bool(VN_CITY.search(location))
            # TopCV titles read "Tuyển <role> làm việc tại <company>"; TopDev "<company> recruits <role>"
            title = re.sub(r"^\s*tuyển\s*(?:dụng)?\s*", "", title, flags=re.I)
            title = re.split(r"\s+làm việc tại\s+|\s+tại\s+", title, maxsplit=1)[0]
            if " recruits " in title:
                title = title.split(" recruits ", 1)[1]
            yield {
                "source": "wayback_vn_2022", "era": "2022", "posted_year": int(row["timestamp"][:4]),
                "title": title, "company": "", "location": location, "region": "VN" if in_vn else "other",
                "work_mode_declared": "", "url": row["original_url"], "site": row["site"], "text": body,
            }


# ------------------------------------------------------------ cleaning steps
def boilerplate_lines(docs: list[dict]) -> set[str]:
    """Lines repeated across >= BOILERPLATE_MIN_DOCS docs and >= 5 % of a source's docs."""
    counts = collections.Counter()
    for d in docs:
        seen = {ln for ln in d["text"].split("\n") if len(ln) >= BOILERPLATE_MIN_CHARS}
        counts.update(seen)
    threshold = max(BOILERPLATE_MIN_DOCS, int(len(docs) * BOILERPLATE_MIN_SHARE))
    return {ln for ln, c in counts.items() if c >= threshold}


def shingles(text: str, n: int = 5) -> set[str]:
    words = re.findall(r"\w+", text.lower())
    return {" ".join(words[i:i + n]) for i in range(max(0, len(words) - n + 1))}


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def region_of(location: str, default: str) -> str:
    s = (location or "").lower()
    if re.search(r"h[ồo]\s*ch[íi]\s*minh|hcm|sài gòn|saigon|bình dương|đồng nai|binh duong", s):
        return "VN-HCM"
    if re.search(r"h[àa]\s*n[ộo]i|hanoi", s):
        return "VN-HN"
    if re.search(r"remote", s):
        return default + "-remote"
    return default


def process(docs: list[dict], meta: dict) -> list[dict]:
    """Shared pipeline for one source: clean -> boilerplate -> dedupe -> label."""
    for d in docs:
        d["text"] = common.strip_personal_data(common.normalize_text(d["text"]))
    # Exact copies go first: a re-posted advert would otherwise push its own
    # lines over the boilerplate threshold and delete itself.
    first_by_hash: dict[str, dict] = {}
    for d in docs:
        first_by_hash.setdefault(common.doc_id_for(d["text"]), d)
    exact = len(docs) - len(first_by_hash)
    docs = list(first_by_hash.values())
    bp = boilerplate_lines(docs)
    removed = 0
    for d in docs:
        kept = []
        for ln in d["text"].split("\n"):
            if ln in bp:
                removed += 1
            else:
                kept.append(ln)
        d["text"] = common.normalize_text("\n".join(kept))
    meta["boilerplate_lines_removed"] = removed
    meta["boilerplate_distinct_lines"] = len(bp)

    out, seen_ids, too_short = [], set(), 0
    buckets: dict[str, list[tuple[set, int]]] = collections.defaultdict(list)
    near = 0
    for d in docs:
        if len(d["text"]) < MIN_TEXT_CHARS:
            too_short += 1
            continue
        did = common.doc_id_for(d["text"])
        if did in seen_ids:
            continue
        # near-duplicate bucket: same company when known, else same title and
        # same opening words (re-posts keep their first sentence)
        key = re.sub(r"\W+", " ", (d.get("company") or (d["title"] + " " + d["text"][:40])).lower()).strip()[:100]
        sh = shingles(d["text"])
        if any(jaccard(sh, other) >= NEAR_DUP_JACCARD for other, _ in buckets[key]):
            near += 1
            continue
        buckets[key].append((sh, len(out)))
        seen_ids.add(did)
        d["doc_id"] = did
        d["language"] = common.detect_language(d["text"])
        d["da_family"] = common.is_da_family(d["title"])
        d["region"] = region_of(d.get("location", ""), d["region"]) if d["region"] in ("VN", "US") else d["region"]
        d["company"] = d.get("company") or ""
        d["n_chars"] = len(d["text"])
        out.append(d)
    meta["exact_duplicates"] = exact
    meta["near_duplicates"] = near
    meta["too_short"] = too_short
    return out


def summarise(corpus: list[dict], tinix_totals: dict) -> list[dict]:
    rows = []
    groups = collections.defaultdict(list)
    for d in corpus:
        groups[(d["source"], d["era"])].append(d)
    for (source, era), ds in sorted(groups.items()):
        fam = [d for d in ds if d["da_family"]]
        lens = sorted(d["n_chars"] for d in fam) or [0]
        rows.append({
            "source": source, "era": era, "n_docs": len(ds), "n_da_family": len(fam),
            "share_vi": round(sum(d["language"] == "vi" for d in fam) / max(1, len(fam)), 3),
            "share_region_vn_hcm": round(sum(d["region"] == "VN-HCM" for d in fam) / max(1, len(fam)), 3),
            "share_region_vn_hn": round(sum(d["region"] == "VN-HN" for d in fam) / max(1, len(fam)), 3),
            "share_region_us": round(sum(d["region"].startswith("US") for d in fam) / max(1, len(fam)), 3),
            "median_chars": lens[len(lens) // 2], "p10_chars": lens[len(lens) // 10], "p90_chars": lens[min(len(lens) - 1, (len(lens) * 9) // 10)],
            "platform_total_postings_that_year": tinix_totals.get(int(era), "") if source == "tinix_vn" else "",
        })
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-root", help="where raw inputs live and the corpus is written (default: $DAJS_DATA_DIR or ./data; never in git)")
    ap.add_argument("--results-dir", default=str(common.RESULTS_DIR))
    args = ap.parse_args(argv)
    root = common.data_root(args.data_root)
    raw = common.raw_dir(root)
    out_dir = common.corpus_dir(root)
    out_dir.mkdir(parents=True, exist_ok=True)
    results_dir = Path(args.results_dir); results_dir.mkdir(parents=True, exist_ok=True)

    corpus, meta, tinix_totals = [], {"sources": {}}, {}
    sources = [
        ("gsearch_us_2022", lambda: load_gsearch_us(find_gsearch_csv(raw / "gsearch_jobs_us_2022"))),
        ("wayback_vn_2022", lambda: load_wayback_vn(raw / "wayback_vn_2022")),
    ]
    for name, loader in sources:
        try:
            docs = list(loader())
        except FileNotFoundError as exc:
            print(f"{name}: skipped, input missing ({exc})"); continue
        m = {"n_raw": len(docs)}
        corpus.extend(process(docs, m))
        meta["sources"][name] = m
        print(f"{name}: raw {m['n_raw']} -> kept {m['n_raw'] - m['too_short'] - m['exact_duplicates'] - m['near_duplicates']} (short {m['too_short']}, exact dup {m['exact_duplicates']}, near dup {m['near_duplicates']}, boilerplate lines {m['boilerplate_lines_removed']})")
    md_dir = raw / "us_job_postings_2026"
    if md_dir.exists() and any(md_dir.glob("jobs_2026_*.parquet")):
        gen = load_us_open_2026(md_dir, 2026)
        docs = []
        try:
            while True:
                docs.append(next(gen))
        except StopIteration as stop:
            md_meta = stop.value or {}
        m = {"n_raw": len(docs), **md_meta}
        corpus.extend(process(docs, m))
        meta["sources"]["us_open_2026"] = m
        print(f"us_open_2026: raw US rows {m['n_raw']} (of {m.get('rows_in_year')} in 2026; remote-no-country {m.get('rows_remote_country_unknown')}) -> kept {m['n_raw'] - m['too_short'] - m['exact_duplicates'] - m['near_duplicates']} (short {m['too_short']}, exact dup {m['exact_duplicates']}, near dup {m['near_duplicates']}, boilerplate lines {m['boilerplate_lines_removed']})")
    else:
        print("us_open_2026: skipped, input missing")
    tinix_path = raw / "tinixai_vietnamese_job_descriptions" / "data.parquet"
    if tinix_path.exists():
        gen = load_tinix_vn(tinix_path)
        docs = []
        try:
            while True:
                docs.append(next(gen))
        except StopIteration as stop:
            tinix_totals = stop.value or {}
        # process per year so the boilerplate rule sees one platform-year at a time
        by_year = collections.defaultdict(list)
        for d in docs:
            by_year[d["era"]].append(d)
        for era, ds in sorted(by_year.items()):
            m = {"n_raw": len(ds)}
            corpus.extend(process(ds, m))
            meta["sources"][f"tinix_vn_{era}"] = m
            print(f"tinix_vn {era}: raw {m['n_raw']} -> kept {m['n_raw'] - m['too_short'] - m['exact_duplicates'] - m['near_duplicates']} (short {m['too_short']}, exact dup {m['exact_duplicates']}, near dup {m['near_duplicates']})")
    else:
        print("tinix_vn: skipped, input missing")

    with (out_dir / "corpus.jsonl").open("w", encoding="utf-8") as fh:
        for d in corpus:
            fh.write(json.dumps(d, ensure_ascii=False) + "\n")
    meta["n_corpus"] = len(corpus)
    meta["tinix_platform_totals_by_year"] = {str(k): int(v) for k, v in tinix_totals.items()}
    meta["parameters"] = {"boilerplate_min_docs": BOILERPLATE_MIN_DOCS, "boilerplate_min_share": BOILERPLATE_MIN_SHARE, "near_dup_jaccard": NEAR_DUP_JACCARD, "min_text_chars": MIN_TEXT_CHARS}
    (out_dir / "corpus_meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    summary = summarise(corpus, tinix_totals)
    with (results_dir / "corpus_summary.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, lineterminator="\n", fieldnames=list(summary[0].keys()) if summary else ["source"])
        w.writeheader(); w.writerows(summary)
    (results_dir / "corpus_meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"corpus: {len(corpus)} documents -> {out_dir / 'corpus.jsonl'}; summary -> {results_dir / 'corpus_summary.csv'}")


if __name__ == "__main__":
    main()
