#!/bin/sh
# Run the whole pipeline. Needs .venv and your own copy of the public data (see README.md, section 7 and DATA_SOURCES.md).
# Usage: ./run_all.sh [data-root] [results-dir]
set -e
cd "$(dirname "$0")"
PY=.venv/bin/python
ROOT="${1:-${DAJS_DATA_DIR:-data}}"
OUT="${2:-results}"
$PY src/build_corpus.py --data-root "$ROOT" --results-dir "$OUT"
$PY src/extract_deterministic.py --data-root "$ROOT" --results-dir "$OUT"
$PY src/compare_eras.py --data-root "$ROOT" --results-dir "$OUT"
for P in P1_us_2022_vs_2026 P2_vn_2022_vs_2026 P3_us_vs_vn_2026 S1_vn_platform_only; do
  $PY src/themes.py --data-root "$ROOT" --results-dir "$OUT" --panel "$P"
done
$PY src/us_instrument_check.py --data-root "$ROOT" --results-dir "$OUT"
echo "pipeline done -> $OUT/"
