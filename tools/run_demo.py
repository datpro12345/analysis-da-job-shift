#!/usr/bin/env python3
"""Demo: run the pipeline on the SYNTHETIC corpus. No downloads, no network.

Copies examples/synthetic/corpus.jsonl into <out>/corpus/, then runs layer 2
(extract), layer 4 (compare) and layer 5 (themes), and writes the aggregates
to <out>/results/. Default <out> is out/demo (ignored by git).
The numbers are invented: they only show that the machinery works.

Usage:  python tools/run_demo.py [--out out/demo]      (use the project's .venv python)
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "examples" / "synthetic" / "corpus.jsonl"
PANELS = ("P1_us_2022_vs_2026", "P2_vn_2022_vs_2026", "P3_us_vs_vn_2026", "S1_vn_platform_only")


def run(out: Path, quiet: bool = False) -> Path:
    corpus = out / "corpus"
    results = out / "results"
    corpus.mkdir(parents=True, exist_ok=True)
    results.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURE, corpus / "corpus.jsonl")
    common = ["--data-root", str(out), "--results-dir", str(results)]
    steps = [["extract_deterministic.py", *common], ["compare_eras.py", *common]]
    steps += [["themes.py", *common, "--panel", p, "--k", "4"] for p in PANELS]
    for step in steps:
        proc = subprocess.run([sys.executable, str(ROOT / "src" / step[0]), *step[1:]], capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"{step[0]} failed:\n{proc.stdout}\n{proc.stderr}")
        if not quiet:
            print(proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else f"{step[0]} done")
    return results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "out" / "demo"))
    args = ap.parse_args(argv)
    results = run(Path(args.out))
    print(f"demo done (synthetic data). Look at {results}/skill_shift_P1_us_2022_vs_2026.csv and {results}/figures/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
