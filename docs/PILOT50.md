# Stage 2: 50-posting annotation pilot

**Run date: 2026-10-20 UTC. Result: 50 final annotations, all 50 pass the
standalone validator.** This is a cost/reliability pilot, not a full annotation
run or a second-annotator agreement study. Full-run size and dates remain
undecided.

## 1. Sample and method

Seed **20261017**, Python `random.Random`. Sort eligible documents by `doc_id`
within each cell before sampling, then sort each selected stratum by id.
Allocate **13 US_2022, 13 US_2026, 12 VN_2022, 12 VN_2026**. This deliberately
balances cells rather than following their unequal population sizes.

- [`results/pilot50_calls.csv`](../results/pilot50_calls.csv): all 50 sampled
  ids, final response transport, component token estimates, reported usage,
  elapsed time, attempt count and validator warnings.
- [`results/pilot50_attempts.csv`](../results/pilot50_attempts.csv): all **59 CLI
  invocations**, including failed transports, invalid output and a rejected
  Codex configuration. Blank usage means **unknown**, not zero.

`tools/run_annotation_pilot.py` excludes sources outside the four public main
cells. The local corpus contained 36 additional, out-of-scope records; they
were excluded before sampling. A legacy local label for the US 2026 public
source was mapped to `us_open_2026` without changing its documents. Public
scope: 23,450 year/source-specific records; main cells: 9,309 distinct ids.
No P2/P3 rerun, download-script change or statistics-code change was made.

Public-scope corpus SHA-256:
`ede4af74b3adc4a0c96045c97ace333e727063c079b0a96a8e7e4b7b6719c58c`.
Fixed system-plus-user-prefix SHA-256:
`80182a1d13e435234485032c93f2bf6807e0cd6d94ee2932b30ec9bccd627b23`.

### Subscription model and prompt

Model: **gpt-6.1-sol**. Primary transport: Pi **0.85.1**, provider
`openai-codex`, logged-in **subscription OAuth**, confirmed by `pi auth check`.
No paid API key was used; API-key environment variables were removed from
subprocesses. Pi had no tools, extensions, skills, context files or persistent
session. Each posting used a fresh process: four concurrent initially, two
for the seven retries. Thinking was `off`; this CLI did not expose temperature,
so temperature 0 was not asserted.

The fixed prompt contains the existing schema 1.0.0, complete guide, taxonomy
ids and labels, evidence/injection rules and annotator metadata. Guide git
blob: `60a362b651344f2163ca1d0e7c7b6017218317af`. No guide or schema meaning was
changed. Raw text, prompts, event logs, annotations and environment details
remain under ignored `out/pilot50/`; none is committed. The final merged
annotation file is `out/pilot50/final/annotations.jsonl`.

Firstmate authorized one Pi retry for the seven missing responses, then
`codex exec` (CLI **0.163.0-alpha.10.2**) for any remaining failure.
All seven retries returned JSON; one
used an invalid task category, so that posting used Codex with the **same
model and saved user prompt**, and the same annotation instructions supplied
as developer instructions. Codex used ChatGPT subscription login, ephemeral
read-only execution, no user config, disabled shell tool and no project docs.
No tool execution appeared in its event stream.

Codex rejected `reasoning.effort=none` before generation. A corrected invocation
used its supported `low` setting and returned a valid record. Codex also added
bootstrap/skills-context warnings despite the skip-discovery option; therefore
its actual input was much larger than Pi's. This was not an identical protocol
request, and **Codex usage is kept separate**, not pooled into Pi's estimate.

## 2. Tokens and elapsed time

Server input in the CSV is **uncached input + cache-read input**. Pi event
usage is summed once per assistant attempt, not again for duplicated turn or
session events. One original call recovered internally after a `fetch failed`
message. Its successful output and reported usage were recovered offline from
the saved stream after fixing the event parser; no new model call was made.

**Prompt-versus-posting attribution is estimated, not server-measured.** Pi
reports total input only. `tiktoken` 0.14.0 `o200k_base` gives **5,363 fixed
prompt tokens per Pi call**, with posting text and its JSON envelope separately
counted in the CSV. GPT-6.1 Sol's server tokenizer and protocol overhead are
not exposed, so these local components are not an exact server-token split.

The following Pi means use its **50 returned responses**, including the one
schema-invalid response, but not the seven no-response invocations. There is
one returned Pi response per sampled posting, before the Codex replacement.

| Cell | n | Fixed prompt, estimated | Posting text, estimated mean | Server input, mean | Server output, mean | Seconds, mean |
|---|---:|---:|---:|---:|---:|---:|
| US_2022 | 13 | 5,363 | 564.4 | 6,023.5 | 1,117.4 | 31.31 |
| US_2026 | 13 | 5,363 | 909.8 | 6,376.2 | 1,434.2 | 51.56 |
| VN_2022 | 12 | 5,363 | 470.7 | 5,960.6 | 1,094.9 | 25.98 |
| VN_2026 | 12 | 5,363 | 429.3 | 5,876.8 | 1,307.4 | 38.38 |

### Observed totals, separated by transport

| Transport | CLI invocations | Responses with usage | Server input | Of which cached | Server output | Sum of elapsed seconds |
|---|---:|---:|---:|---:|---:|---:|
| Pi | 57 | 50 | **303,244** | **0** | **61,999** | **2,425.313** |
| Codex exec | 2 | 1 | **31,940** | **11,648** | **1,257** | **57.123** |

Codex uncached input was **20,292**; its successful call took **47.076 s** and
the rejected configuration took **10.047 s**. Reported reasoning output was
zero. The totals include the discarded Pi schema-invalid output. The final
50-record file uses **49 Pi records + one Codex record**. Summed call durations
are parallel work, not wall-clock runtime; pauses for network recovery and
worker interruptions make the overall wall-clock span unsuitable for throughput
forecasting. Seven failed Pi calls and the rejected Codex configuration have
no trustworthy usage figures. Unreported server-side usage is unknown.

### Projection for about 11,200 calls

Weight each Pi cell mean by **2,545 / 6,381 / 141 / 242**, divided by 9,309;
then multiply by 11,200. Do **not** multiply the balanced pilot's unweighted
mean by the full-run size. This gives a Pi base estimate, **before retries**:

| Quantity | Weighted mean per call | At 11,200 calls |
|---|---:|---:|
| Server input | 6,260.46 | **70,117,105 tokens** |
| Server output | 1,339.17 | **14,998,722 tokens** |
| Fixed prompt, local estimate | 5,363.00 | 60,065,600 tokens |
| Posting text, local estimate | 796.20 | 8,917,480 tokens |
| Posting envelope, local estimate | 62.25 | 697,225 tokens |
| Returned-call elapsed time | 45.30 s | 140.92 serial hours |

Exact server totals and locally estimated components need not add up. The
11,200 planning number rounds up 9,309 × 1.2 = 11,170.8. The time is not a
promised schedule: concurrency, subscription quotas and network recovery can
dominate. No cache saving was observed for Pi. One Codex fallback is far too
small to project a Codex full run, and its higher CLI overhead cannot be
applied to Pi calls. Observed recovery added **31,940 known input + 1,257
output tokens** for the fallback, besides the already-counted invalid Pi
response; further failed-request usage remains unknown.

No dollar figure is given: subscription usage is not metered API billing,
and Pi's internal cost metadata is not a verified public list-price source.
Before choosing full-run dates/size, allow for repeat calls and semantic
review; the base token estimate is not an all-in guarantee.

## 3. Failures, validator and review

### Network/configuration failures versus annotation failures

- Initial Pi run: **7 / 50 calls (14%)** exhausted transport retries, all late
  in VN_2026. Each logged four `fetch failed` assistant errors. A separate
  call recovered after one internal error. Thus 29 such error events occurred,
  but these are not 29 separate measured CLI invocations.
- One authorized Pi retry per missing posting: **7 / 7 returned JSON**, no
  remaining transport failures. Across both rounds, **7 / 57 Pi invocations
  (12.3%)** failed transport. These rates are clustered observations, not a
  stable independent failure probability.
- Returned Pi JSON: **1 / 50 (2%) failed annotation validation**.
  `70252b2fc047e37e` used task category **`documentation`**, which is a skill id
  but not a valid task category. It was not silently coerced. A same-prompt
  Codex fallback replaced it and passed.
- Codex: one configuration rejection, followed by one valid response. This is
  separate from network failures and schema failures.
- Final merged output: **0 / 50 validator failures (0%)**. Across all 51
  returned model records, including the discarded Pi response, the annotation
  failure rate was **1 / 51 (2.0%)**. Passing does not establish semantic accuracy.

### Implemented validation

`src/validate_annotations.py` checks Draft 2020-12 schema, corpus identity/era,
NFC/whitespace-normalized quotes, taxonomy version and ids, `other` terms,
duplicate skills, years ordering, evidence consistency and personal-data
patterns. Regex disagreements and confidence below 0.6 are warnings. Diagnostics
contain codes, not posting text. Ambiguous corpus identities are not silently
overwritten. The final standalone command was:

```bash
.venv/bin/python src/validate_annotations.py --corpus out/pilot50/public_corpus.jsonl --annotations out/pilot50/final/annotations.jsonl
```

All 50 final records have deterministic cross-check warnings: **171 regex-only
and 106 model-only skill flags**. Example: `0b66b826ad3f8797` has regex-only
`machine_learning` and `communication`, and model-only `storytelling`. Human
review must inspect the source context. Some warnings reflect soft-skill
concepts represented in `soft_skills` rather than duplicated in `skills`.

Two validator false positives were corrected and regression-tested, not counted
as annotation failures: stated study subjects can have evidence without a
specified degree level; and a duty starting with “Email marketing” is not a
personal email address. `CONTACT_LINE` is a cleaning heuristic, not a PII
address detector. Actual email, phone, handle and other existing PII patterns
remain checked. Fictional tests also reject invented quotes, invalid ids,
reversed years and malformed JSON. No raw posting quote is published here.

## 4. Count audit

### US_2022: 2,545 is correct

Independently reran **only** `load_gsearch_us` and `process` on the local raw
2022 CSV, without running comparisons or replacing results:

- 5,488 − 1,448 exact duplicates − 332 near duplicates − 258 short texts
  = **3,450 cleaned rows**.
- The title rule retains **2,545** and excludes **905**.
- Rebuilt ids equal the saved corpus's US_2022 ids exactly; all 2,545 are unique.
  The extracted CSV also has 2,545 distinct eligible ids, as do published counts.
  There is no duplicate, missing or non-English US row to subtract.

**2,544 is unsupported by every inspected source artifact.** No committed
reference to 2,544 exists; the origin of that off-by-one assertion cannot be
reconstructed from this checkout. It is not a valid alternative corpus count.
Existing 2,545 documentation was retained, and the TDD open question replaced
with the verified answer rather than changing a correct number.
Raw CSV SHA-256:
`03cbadd8b2fe471b879a6fbe126c55c3e878d905766b6b371c01d8d98daa71aa`.

### Tinix: raw rows versus year-records versus unique text

A direct read of raw Parquet `year` and `job_title` columns confirms:

| Year | All raw postings | DA-family titles before cleaning | Cleaned records |
|---|---:|---:|---:|
| 2022 | 111,033 | 59 | 45 |
| 2023 | 129,674 | 55 | 49 |
| 2024 | 159,049 | 93 | 76 |
| 2025 | 160,386 | 136 | 125 |
| 2026 | 46,736 | 247 | 242 |
| Total | **606,878** | **590** | **537** |

There are **535 distinct cleaned text ids**, not 537 globally unique texts.
Cause: cleaning/deduplication runs **per year**; `34bcb582f0d1953f` occurs in
2023 and 2024, and `374886a0bce86c8e` in 2024 and 2025. Texts are identical
within each pair: cross-year repeated adverts, not hash collisions. Neither
pair enters the four main cells. `DATA_SOURCES.md` and TDD now state the
distinction; their yearly values and 606,878 raw total were correct.
Raw Parquet SHA-256:
`4d5e11b58490edc40900386986de71e844cd9f0f3a5fc714418747f66462f834`.

The lower 2026 volume is real in this snapshot. Whether it is a partial year
or a changed sample remains unknown; counting cannot validate collection
policy or the source's meaning of `year`.

## 5. Open risks and next decisions

1. **No agreement gate yet.** Run a second independent annotator and field-level
   kappa before full annotation. This pilot is not a substitute.
2. **Review semantics.** Quote presence is not proof of a correct label;
   reconcile regex warnings and required/preferred/mentioned choices.
3. **Token attribution.** Component counts are reproducible local estimates;
   server-exact prompt/posting attribution is unavailable through these CLIs.
4. **Transport drift and quotas.** Pi and Codex add different context. Pin the
   CLI/model/prompt, verify subscription allowance and retest after changes.
5. **Retry allowance.** Preserve all attempts, not just final successes. These
   clustered failures cannot reliably predict a full-run retry multiplier.
6. **Counts versus source validity.** Correct counts do not fix selection bias,
   unverified Tinix years or source comparability.

The pilot supports a base token estimate and identifies validation/transport
risks. It does **not** choose the full-run size, dates or model-access strategy.

Verification: **154 offline unit tests pass**, Ruff passes on the four added
Python files, the public-safety guard passes, and the standalone validator
accepts all 50 final records. Python was 3.12.11; validation used jsonschema
4.26.0 and PyYAML 6.0.3. Measurement dependencies and unabridged raw CLI events
are retained locally with the ignored pilot artifacts.
