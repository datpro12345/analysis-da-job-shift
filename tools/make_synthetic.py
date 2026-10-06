#!/usr/bin/env python3
"""Generate the SYNTHETIC demo corpus: examples/synthetic/corpus.jsonl.

Every document is made up. Companies are "Example Corp N", texts are built from
a few template sentences, and each text starts with "SYNTHETIC EXAMPLE". The
skill rates per era are invented to show the pipeline at work; they say nothing
about the real job market. Generation is deterministic (fixed seed), and a test
checks that the committed file equals what this script writes.

Usage:  python tools/make_synthetic.py [--out examples/synthetic/corpus.jsonl] [--check]
Standard library only (it reuses nothing from src/, so it also runs on a bare Python).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "examples" / "synthetic" / "corpus.jsonl"
SEED = 20260101

# (probability in the early era, probability in the late era) per skill, per market
EN_SKILLS = {
    "sql": ("Write SQL queries to pull the data.", (0.55, 0.60)),
    "python": ("Use Python for analysis.", (0.30, 0.40)),
    "excel": ("Advanced Excel is needed.", (0.40, 0.32)),
    "sas": ("Experience with SAS or SPSS.", (0.12, 0.05)),
    "dashboards": ("Build dashboards for managers.", (0.33, 0.55)),
    "power_bi": ("Know Power BI.", (0.25, 0.35)),
    "tableau": ("Know Tableau.", (0.20, 0.22)),
    "stakeholders": ("Work with stakeholders and explain insights.", (0.40, 0.70)),
    "ai": ("Use ChatGPT and other AI tools to speed up work.", (0.04, 0.40)),
}
VI_SKILLS = {
    "sql": ("Viết truy vấn SQL để lấy dữ liệu.", (0.45, 0.62)),
    "excel": ("Thành thạo Excel.", (0.60, 0.48)),
    "sas": ("Biết SPSS hoặc SAS.", (0.09, 0.02)),
    "dashboards": ("Xây dựng dashboard cho quản lý.", (0.25, 0.55)),
    "power_bi": ("Biết Power BI.", (0.40, 0.57)),
    "tableau": ("Biết Tableau.", (0.20, 0.38)),
    "ai": ("Sử dụng ChatGPT và công cụ AI.", (0.00, 0.16)),
}
EN_OPENERS = ["Join our team to analyze business data.", "We need an analyst to report on weekly sales.", "Help the company understand its customers with data."]
VI_OPENERS = ["Phân tích dữ liệu kinh doanh hằng tuần.", "Lập báo cáo và phân tích số liệu bán hàng.", "Hỗ trợ công ty hiểu khách hàng bằng dữ liệu."]
EN_TITLES = ["Data Analyst", "Senior Data Analyst", "Junior Data Analyst", "BI Analyst", "Data Analyst II"]
VI_TITLES = ["Chuyên viên phân tích dữ liệu", "Nhân viên phân tích dữ liệu", "Senior Data Analyst", "Data Analyst", "Chuyên viên BI"]

# source, era, posted_year, region, language, title pool, skills, count
PLAN = [
    ("gsearch_us_2022", "2022", 2022, "US", "en", EN_TITLES, EN_SKILLS, 0, 70),
    ("us_open_2026", "2026", 2026, "US", "en", EN_TITLES, EN_SKILLS, 1, 90),
    ("tinix_vn", "2022", 2022, "VN-HCM", "vi", VI_TITLES, VI_SKILLS, 0, 24),
    ("wayback_vn_2022", "2022", 2022, "VN-HN", "vi", VI_TITLES, VI_SKILLS, 0, 24),
    ("tinix_vn", "2026", 2026, "VN-HN", "vi", VI_TITLES, VI_SKILLS, 1, 60),
]


def make_docs() -> list[dict]:
    rng = random.Random(SEED)
    docs = []
    for source, era, year, region, lang, titles, skills, late, count in PLAN:
        for i in range(count):
            sentences = [rng.choice(EN_OPENERS if lang == "en" else VI_OPENERS)]
            for sentence, probs in skills.values():
                if rng.random() < probs[late]:
                    sentences.append(sentence)
            rest = sentences[1:]
            rng.shuffle(rest)
            sentences = sentences[:1] + rest
            region_i = region if region != "VN-HN" else rng.choice(["VN-HN", "VN-HCM"])
            title = rng.choice(titles)
            text = "SYNTHETIC EXAMPLE. " + " ".join(sentences)
            doc_id = hashlib.sha256(f"{source}|{era}|{i}|{text}".encode()).hexdigest()[:16]
            docs.append({
                "source": source, "era": era, "posted_year": year, "title": title, "company": f"Example Corp {rng.randint(1, 40)}",
                "location": "Example City", "region": region_i, "work_mode_declared": "", "url": "", "text": text,
                "doc_id": doc_id, "language": lang, "da_family": True, "n_chars": len(text),
            })
    return docs


def render() -> str:
    return "".join(json.dumps(d, ensure_ascii=False, sort_keys=True) + "\n" for d in make_docs())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--check", action="store_true", help="fail when the file on disk differs from a fresh generation")
    args = ap.parse_args(argv)
    out = Path(args.out)
    text = render()
    if args.check:
        same = out.exists() and out.read_text(encoding="utf-8") == text
        print("synthetic corpus is up to date" if same else "synthetic corpus differs: rerun tools/make_synthetic.py")
        return 0 if same else 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out} ({text.count(chr(10))} fictional documents)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
