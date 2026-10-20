# TDD: How the Data Analyst job changed, 2022 to 2026

Project: `da-job-shift`
Document type: Technical Design Document
Companion: `BRD.md` (requirements BR-01 to BR-16). Appendix A maps each requirement to its design and test.
Status: stage 1 is built and rerun on public data only. Stage 2 has a 50-posting pilot and validator (see `PILOT50.md`); full annotation and agreement checks remain pending. Stage 3 is designed, not built.

**How to read this document.** It explains how the problem was solved and teaches each method. Every method has the same parts: what it is, why we chose it, where it lives in the code, what it can tell you, what it cannot, and a small worked example. Numbers marked "real" come from `results/`. Numbers marked "toy" are invented to show the arithmetic.

> **Mentions, not requirements.** Every skill number from stage 1 counts postings that MENTION a term at least once. "Python is a plus" and "Python is required" both count. A stage 1 percentage is therefore an upper bound on how many employers require the skill. Stage 2 adds the field `requirement_level` (required, preferred, mentioned) to fix this. Until then, write "mention", never "require".

---

## 1. Solution overview and architecture

### 1.1 The problem in one paragraph
We want to know how the Data Analyst job changed. The only evidence is the text of job postings from different sources, years and countries. The sources do not follow one design. So the design has two jobs: (a) make the postings as comparable as we can, and (b) measure change with methods that say how sure we are.

### 1.2 Five layers

| Layer | Name | Question it answers | Main files | Stage |
|---|---|---|---|---|
| 1 | Corpus building | Are the postings clean and comparable? | `src/build_corpus.py`, `src/common.py` | 1 done |
| 2 | Deterministic extraction | Which listed skills and fields appear in each posting? | `src/extract_deterministic.py`, `taxonomy/skills.yaml` | 1 done |
| 3 | LLM structured annotation | What does the job holder do? Is a skill required? How is AI used? | `schema/jd_annotation.schema.json`, `docs/ANNOTATION_GUIDE.md`, `src/validate_annotations.py` | 2 pilot; full run pending |
| 4 | Statistical comparison | Did a rate really change, and by how much? | `src/stats.py`, `src/compare_eras.py` | 1 done |
| 5 | Unsupervised themes | What groups form that we did not plan for? | `src/themes.py` | 1 done |

Plus a robustness script, `src/us_instrument_check.py` (section 5.2).

### 1.3 Data flow

```mermaid
flowchart TD
  subgraph IN["Data folder (downloaded, outside git)"]
    S1["US 2022 postings (csv)"]
    S2["US 2026 postings (parquet)"]
    S3["Vietnam platform parquet 2022 to 2026"]
    S4["Vietnam archived pages 2022"]
    S6["US skill release 2025 to 2026"]
  end
  S1 --> L1
  S2 --> L1
  S3 --> L1
  S4 --> L1
  L1["Layer 1: build_corpus.py<br/>clean, dedupe, label"] --> C["corpus.jsonl (not in git)"]
  C --> L2["Layer 2: extract_deterministic.py<br/>skill flags and fields"]
  L2 --> E["extracted.csv (not in git)"]
  L2 --> R1["results: skill_prevalence_by_cell.csv<br/>requirements_by_cell.csv, panels.json"]
  E --> L4["Layer 4: compare_eras.py + stats.py"]
  C --> L4
  R1 --> L4
  C --> L5["Layer 5: themes.py<br/>TF-IDF + NMF"]
  C -.-> L3["Layer 3 (stage 2): LLM annotation<br/>schema + guide + validator"]
  L3 -.-> L4
  S6 --> CHK["us_instrument_check.py"]
  S1 --> CHK
  L4 --> R2["results: skill_shift_*.csv, word_log_odds, power_check, figures"]
  L5 --> R3["results: themes_*.csv and stability"]
  CHK --> R4["results: us_same_instrument_*"]
```

Plain description: sources on the top feed layer 1. Layer 1 writes one private corpus file. Layer 2 reads it and writes flags and the first result tables. Layer 4 reads the flags and the corpus and writes the comparison tables. Layer 5 reads the corpus and writes theme tables. A separate check reads the 2022 file and the 2025-2026 skill release. The dotted lines are stage 2: an annotation layer will read the corpus and feed layer 4 again. Only the "results" boxes go into git.

### 1.4 Rules that shape the whole design
1. Raw text never enters git. Only aggregates do. `tools/public_safety_check.py` enforces it.
2. Only public downloads are read. Nothing collected by hand is part of the pipeline.
3. One selection rule everywhere: the title must be in the Data Analyst family.
4. One cleaning pipeline everywhere.
5. Every comparison gets a count, an interval, a test, an effect size, and a robustness check.
6. Every result file names the taxonomy version (1.0.0) so old numbers do not change silently.

---

## 2. Data model and cleaning rules

### 2.1 Cells and real sample sizes
A **cell** is one country and one era, built with the same selection rule. A **panel** compares two cells.

| Cell | Sources | n (cleaned, Data Analyst family) | Vietnamese text |
|---|---|---|---|
| US_2022 | `gsearch_us_2022` | 2,545 | 0% |
| US_2026 | `us_open_2026` | 6,381 | 0% |
| VN_2022 | `tinix_vn` 2022 (45) + `wayback_vn_2022` (96) | 141 | 68.8% |
| VN_2026 | `tinix_vn` 2026 | 242 | 74.4% |
| VN_platform_2022 | `tinix_vn` 2022 | 45 | 73.3% |
| VN_platform_2026 | `tinix_vn` 2026 | 242 | 74.4% |

Source: `panels.json`. The four main cells hold 9,309 postings. The corpus (kept outside git) has 23,450 documents in all, because it also keeps postings with titles outside the family (for example 12,959 in the 2026 US set).

**Funnel per source** (from `corpus_meta.json` and `role_family_filter.csv`):

| Source | Raw rows | Exact duplicates | Near duplicates | Too short | Kept | Data Analyst family |
|---|---|---|---|---|---|---|
| gsearch_us_2022 | 5,488 | 1,448 | 332 | 258 | 3,450 | 2,545 |
| us_open_2026 (US rows only) | 24,659 | 4,019 | 1,283 | 17 | 19,340 | 6,381 |
| wayback_vn_2022 | 124 | 1 | 0 | 0 | 123 | 96 |
| tinix_vn 2022 | 59 | 5 | 9 | 0 | 45 | 45 |
| tinix_vn 2023 | 55 | 3 | 2 | 1 | 49 | 49 |
| tinix_vn 2024 | 93 | 10 | 7 | 0 | 76 | 76 |
| tinix_vn 2025 | 136 | 7 | 2 | 2 | 125 | 125 |
| tinix_vn 2026 | 247 | 0 | 2 | 3 | 242 | 242 |

Notes: the US 2026 files had 83,446 rows in 2026 and 24,659 passed the US location rule. The Tinix file has 606,878 rows. The cleaned Tinix rows sum to 537 across years, representing 535 distinct text ids: two texts recur in adjacent years because cleaning runs per year. Neither recurrence is in the four main cells. The pilot count audit (`PILOT50.md`) reproduces these counts and US_2022 = 2,545 from the raw source. The loader keeps only titles in the family, so its "raw" count is already filtered. The Tinix total postings per year are 111,033 (2022), 129,674 (2023), 159,049 (2024), 160,386 (2025) and 46,736 (2026). The 2026 total is much lower. The sources do not say why (open question 3).

### 2.2 The corpus record
One JSON line per posting in `corpus.jsonl` (private).

| Field | Meaning | Source |
|---|---|---|
| `doc_id` | First 16 hex characters of the SHA-256 of the cleaned text | `common.doc_id_for` |
| `source`, `era`, `posted_year` | Where it came from, era label ("2022", "2026", or the year for Tinix), year | loaders |
| `title`, `company`, `location`, `url` | As found. `company` and `url` may be empty | loaders |
| `region` | `US`, `VN-HCM`, `VN-HN`, `VN`, `other`, or `-remote` forms | `build_corpus.region_of` |
| `language` | `vi` or `en` | `common.detect_language` |
| `da_family` | Title is in the Data Analyst family | `common.is_da_family` |
| `n_chars` | Length of the cleaned text | `process` |
| `work_mode_declared` | Declared work mode, where the source has it | loaders |
| `declared_experience`, `declared_position`, `declared_education`, `declared_salary` | Tinix structured fields, kept for stage 3, not used in stage 1 counts | `load_tinix_vn` |
| `site` | Portal name (archived pages only) | `load_wayback_vn` |
| `text` | Cleaned posting text | `process` |

`extract_deterministic.extract_document` adds one row per posting to `extracted.csv`: flags `skill__<id>` for each of the 91 taxonomy skills, `any_ai`, `years_min`, `years_max`, `seniority`, `degree`, `english`, `work_mode`, `salary`.

### 2.3 Cleaning rules, in the order they run
Code: `build_corpus.process` unless noted.

| # | Rule | Detail |
|---|---|---|
| 1 | Normalise text | Unicode NFC, one line-ending style, collapse spaces and blank lines (`common.normalize_text`) |
| 2 | Strip personal data | Delete lines starting with Contact, Liên hệ, Hotline, Email, Phone, Zalo and similar. Replace URLs with a user part, e-mails, chat handles (Zalo, Telegram, Skype, WhatsApp, Viber, Line), phone numbers of 9 or more digits, and honorific names (Ms, Mr, Anh, Chị, Cô, Chú plus a name) with markers such as `[email]` (`common.strip_personal_data`) |
| 3 | Remove exact duplicates | Same cleaned text means same `doc_id`. Done BEFORE the boilerplate count |
| 4 | Remove boilerplate by frequency | A line of 20 or more characters that appears in at least `max(3, 5% of the source's documents)` documents is removed. Run per source; for Tinix, per year |
| 5 | Drop short texts | Under 200 characters (stubs and teasers) |
| 6 | Remove near-duplicates | Word 5-shingle Jaccard similarity of 0.8 or more, inside the same company bucket (or same title and first 40 characters when the company is unknown) |
| 7 | Label | `language`, `region`, `da_family`, `n_chars` |
| 8 | US filter (US 2026 only) | Location must be "City, ST" with a real state code, "United States"/"USA", or a US metro phrase. "Remote" alone is dropped. `corpus_meta.json` counts such rows (`rows_remote_country_unknown`) |
| 9 | Archived page rules (Wayback only) | Keep HTTP 200 only; decompress gzip; skip VietnamWorks keyword pages and Glints; cut the job text between a duties heading and a benefits or footer heading |

Why the order matters: removing exact duplicates before counting boilerplate stops a re-posted advert from pushing its own lines over the threshold and deleting itself. The tests caught this bug.

---

## 3. The comparison designs

| Panel | Baseline a | Comparison b | n a | n b | Reads as | Why it is in the design |
|---|---|---|---|---|---|---|
| **P1** | US_2022 | US_2026 | 2,545 | 6,381 | How the US posting changed | The 2022 US window is exactly the ChatGPT launch. Big samples give narrow intervals |
| **P2** | VN_2022 | VN_2026 | 141 | 242 | How the Vietnam posting changed | This is the main question and the weakest data |
| **P3** | US_2026 | VN_2026 | 6,381 | 242 | Where Vietnam stands against the US today | Shows what Vietnam does and does not yet ask. A market difference, not a time lag |
| S1 | VN_platform_2022 | VN_platform_2026 | 45 | 242 | P2 with no change of portal | Cleanest Vietnam check. Smallest 2022 cell |

Panels P1, P2 and P3 are the three designs the study is built on. S1 is a check.

```mermaid
flowchart LR
  A["US 2022<br/>n=2545"] -->|P1| B["US 2026<br/>n=6381"]
  C["VN 2022<br/>n=141"] -->|P2| D["VN 2026<br/>n=242"]
  B -->|P3| D
  E["VN platform 2022<br/>n=45"] -->|S1| F["VN platform 2026<br/>n=242"]
```

Plain description: four main boxes in two rows (US on top, Vietnam below; 2022 left, 2026 right). Arrow P1 goes across the top, arrow P2 across the bottom. Arrow P3 joins the two 2026 boxes. S1 is a separate pair that uses the platform only.

Each panel's summary (real, mentions at q of 0.10 or less):

| Panel | Skills tested | Skills that differ | Any AI mention, a to b |
|---|---|---|---|
| P1 | 92 | 76 | 3.9% (99 of 2,545) to 41.1% (2,624 of 6,381) |
| P2 | 92 | 29 | 4.3% (6 of 141) to 16.1% (39 of 242) |
| P3 | 92 | 57 | US 41.1% vs Vietnam 16.1% |
| S1 | 92 | 13 | 0% (0 of 45) to 16.1% (39 of 242) |

(The 92 tests are the 91 taxonomy skills plus the combined flag `any_ai`.)

Why not one model that adjusts for everything? A table of rates with a test is something a reader can check by hand. The project is also meant for learning, and the data are too uneven for a large model to be trusted. The design instead adjusts for the two mixes we can measure (seniority and region) and checks the rest with robustness runs.

---

## 4. The five method layers

### 4.1 Layer 1: corpus building and comparability

**What it is.** A pipeline that reads five differently shaped sources and turns them into one list of clean postings with the same labels.

**Why we chose it.** A comparison across time is only fair when both sides were cleaned the same way. Two choices matter:
- Boilerplate is removed by a frequency rule, not a hand list. The same rule runs on every source and is auditable: the number of removed lines is in `corpus_meta.json`.
- The title decides whether a posting is in the family. Bodies of data engineer or data scientist postings also talk about SQL and dashboards, so a body-based rule would blur the role.

**Where it lives.** `src/build_corpus.py`: loaders `load_gsearch_us`, `load_us_open_2026`, `load_tinix_vn`, `load_wayback_vn` with `html_to_job_text`; the shared steps in `process`, `boilerplate_lines`, `shingles`, `jaccard`, `region_of`, `summarise`. `src/common.py`: `normalize_text`, `strip_personal_data`, `detect_language`, `is_da_family`.

**What it can tell you.** That each cell was built by the same rules, and how many postings each step removed. It also writes `corpus_summary.csv` so you can compare text length, language and region mix per source.

**What it cannot tell you.** Whether a cell represents the real market. Each dataset holds only what it happens to contain. The Tinix `year` cannot be checked. The archive holds only the pages it happened to save. Cleaning cannot fix selection.

**Worked example 1 (real): the funnel for US 2022.** 5,488 rows. Minus 1,448 exact copies, 332 near copies and 258 stubs gives 3,450. The title rule keeps 2,545 and drops 905 (the role-family table). So 3,450 of 5,488 rows (63%) survive cleaning, and 2,545 (46%) end up in cell US_2022: unique, long enough, and a Data Analyst title.

**Worked example 2 (real): the boilerplate threshold.** Tinix 2022 has 59 rows, 54 after exact duplicates. 5% of 54 is 2.7, rounded down to 2. The floor of 3 wins. So a line must appear in 3 or more documents. The result: 1 distinct line removed, 3 times in all. For the 2026 US set, 20,640 documents remain after exact duplicates, so the threshold is 1,032 documents. The result: 3 distinct lines removed, 4,959 times.

**Worked example 3 (toy): near-duplicates.** A shingle is a run of 5 words. Posting A has shingles {a, b, c, d}. Posting B has {b, c, d, e}. They share 3 and together hold 5, so Jaccard = 3 / 5 = 0.6. That is below 0.8, so both stay. A multi-city copy of one advert shares nearly all shingles and scores above 0.8, so one copy goes.

**Worked example 4 (real): why text length matters.** Median characters of a Data Analyst posting: Tinix 2022, 1,081; Tinix 2026, 1,804; archived Vietnam 2022 pages, 1,308; US 2022, 3,015; US 2026, 5,196. A longer posting has more room to name tools. Part of any rise may be longer adverts. Stage 3 adds a rate per 1,000 characters to test this.

**Things to learn.** Vietnamese letters can be stored as a base letter plus a mark. Then a word boundary test sees "BI" inside "bị" (a Vietnamese word). Always normalise first, then match.

### 4.2 Layer 2: deterministic extraction (taxonomy, regex, mention vs requirement)

**What it is.** For each posting, one yes or no per skill, plus a few fields read by rules. A **taxonomy** is a list of skills with ids and labels. A **regex** (regular expression) is a text pattern, for example `\bpython\b`, that finds a word. Rules are deterministic: the same text always gives the same answer.

**Why we chose it.** Rules are cheap, repeatable and checkable. A doubtful hit can be traced to one pattern in a versioned file. The same pattern runs on 2022 and 2026 text. In stage 2 the rules also act as a floor: a tool the regex saw but the model missed gets flagged.

**Where it lives.** `taxonomy/skills.yaml` (version 1.0.0, 91 skills in 14 groups, English and Vietnamese patterns), loaded by `common.load_taxonomy`. `src/extract_deterministic.py`: `skill_flags`, `extract_document`, `years_of_experience`, `seniority_from_title`, `degree_level`, `english_requirement`, `work_mode`, `salary_mention`, `prevalence_rows`, `distribution_rows`. The cells and panels are in `CELLS` and `PANELS`.

**How a posting is flagged.** A skill is 1 if any of its patterns hits at least once. Short tokens use case-sensitive patterns (`patterns_cs`): R, SAS (not SaaS), AI (not Vietnamese "ai", meaning "who"), BI (not "bị"). A document counts once however often it repeats a word. A combined flag `any_ai` is `generative_ai` OR `ai_general`. In tables, "AI (any mention)" is `ai_general` alone (the word AI or "artificial intelligence"). "Any AI mention" is either flag, so it is slightly higher.

**What it can tell you.** Which share of postings mention a term, the same way in every cell. It is the recall floor and the baseline for stage 2.

**What it cannot tell you.**
- **Required or not.** The flag does not read the sentence. "Python is a plus" and "Python is required" count the same. This is why every stage 1 skill number is a mention rate.
- **Role of AI.** "Use ChatGPT to speed up SQL" and "we are an AI-first bank" both flag AI.
- **Context errors that remain.** Patterns need context for generic words. The tests cover known cases (pipeline, lean, fabric, "chi tiết"). Unknown ones remain. For example, the English rule reads the Vietnamese word "tốt" (good) near "tiếng Anh" as fluent English.

**Worked example 1 (toy): mention vs requirement.** Posting 1: "Python is a plus." Posting 2: "Python is required." Both set `skill__python` to 1. A stage 1 table says 2 of 2 postings mention Python. A stage 2 table says 1 required, 1 preferred.

**Worked example 2 (real): a rate from the flags.** Python in VN_2022: 49 of 141 postings, 34.8%. In VN_2026: 98 of 242, 40.5%. Both are mention rates. (Section 4.4 shows the test says this rise is not clearly real.)

**Worked example 3 (toy): years of experience.** "2-4 năm kinh nghiệm" gives min 2, max 4. "5+ years" gives min 5, max none. "13th-month salary" and "2-year contract" are not counted, because "năm" counts only with "kinh nghiệm" or "experience" within 80 characters. Real result: median stated minimum 3 years (US 2022), 4 (US 2026), 2 (Vietnam 2022), 2 (Vietnam 2026), when stated.

**Seniority from the title.** Rules run in this order and the first hit wins: intern, head or director, manager, lead, senior, junior, mid. No hit gives "unspecified" (counted as mid for weighting).

### 4.3 Layer 3: LLM structured annotation (stage 2 design)

**What it is.** A language model reads one posting and returns one JSON record that follows a fixed schema. A **schema** is a contract: which fields exist, which values are allowed. It is written for JSON Schema 2020-12 in `schema/jd_annotation.schema.json` (schema version 1.0.0). **Annotation** means labelling.

**Why we chose it.** Rules cannot read meaning. A model can say what the job holder does, whether a skill is required, and how AI is used. The risk is that models over-read. So the design adds three guards: every judgement carries a verbatim quote, a program checks each record, and two independent annotators are compared.

**Where it lives.** The schema, `docs/ANNOTATION_GUIDE.md`, `src/validate_annotations.py`, `tools/run_annotation_pilot.py`, and `stats.cohens_kappa`. The validator and 50-posting pilot are built; see `docs/PILOT50.md`. Full annotation and second-annotator agreement remain pending.

**The record** (all of these fields are required):

| Field | Allowed values |
|---|---|
| `tasks` | 18 categories, for example `reporting_dashboards`, `ad_hoc_analysis_insights`, `data_preparation_cleaning`, `building_ai_ml_features` |
| `ai_roles` | 7 categories: `ai_as_analyst_tool`, `ai_as_product_team_builds`, `ai_governance_ethics_risk`, `ai_data_preparation_for_models`, `ai_literacy_expected`, `ai_in_company_description_only`, `ai_mentioned_only`; plus `named_tools` |
| `skills` | `skill_id` from the taxonomy (or `other` with `raw_term`) and `requirement_level`: `required`, `preferred`, `mentioned` |
| `soft_skills` | 13 categories |
| `seniority`, `years_experience`, `degree`, `languages`, `work_mode`, `salary` | Same ideas as layer 2, with levels |
| `role_family` | `data_analyst`, `bi_analyst_developer`, `analytics_engineer`, `data_scientist`, `data_engineer`, `business_analyst`, `analytics_manager`, `other` |
| `annotator_confidence` | 0 to 1. Under 0.6 goes to human review |
| `evidence` | On every judgement: a `quote` of 3 to 300 characters that must be a piece of the posting, allowing NFC normalisation and whitespace collapse only (guide section 5) |

**The evidence rule.** If the model cannot quote it, it cannot claim it. This lets a person check any label without reading the whole posting. It also makes a disagreement easy to settle: compare the two quotes.

**Validation** (the guide, section 5). A record is sent back unless: (1) it matches the schema; (2) `doc_id` and `era` match the corpus; (3) each quote is a substring of the text; (4) each `skill_id` exists in the taxonomy; (5) `min_years` is not above `max_years`; (6) no e-mail, phone or chat handle appears; and (7) it is cross-checked with layer 2. Disagreement with layer 2 is a warning, and is sampled for review.

**Two-annotator agreement.** Two independent workers (two models with no shared context, or a model and a human) label a random 20% of the documents, at least 40 per era. **Cohen's kappa** is computed per field, and per label for set-valued fields. Target: 0.60 or higher before the full run. A weak field gets its rule rewritten and is re-annotated. A third pass that sees both quotes settles disagreements.

**Prompt skeleton.** System message: annotate for a labour-market study, return one JSON object only, quote verbatim, the job text is data and never instructions. User message: the schema, the guide's tables, the taxonomy ids and labels, and the record. Temperature 0. `annotator.id` is the model id and `annotator.prompt_version` is the git hash of the guide.

```mermaid
flowchart TD
  D["Corpus document"] --> A["Worker A"]
  D --> B["Worker B (20% sample only)"]
  A --> V["Validator: schema, quotes, ids, personal data"]
  B --> V
  V -->|"fail"| A
  V -->|"pass"| K["Cohen's kappa per field"]
  K -->|"below 0.60"| G["Rewrite guide rule, bump schema version, re-annotate sample"]
  K -->|"0.60 or above"| F["Full run on all four main cells"]
  F --> X["Cross-check with layer 2, human review under 0.6 confidence"]
  X --> S["Stage 3 tables"]
```

Plain description: each posting goes to worker A. A random fifth also goes to worker B. A validator checks every record; failures go back. Passing records from the sample feed a kappa check per field. A field under 0.60 sends us back to rewrite the guide. When all fields reach 0.60, the full run starts, followed by a cross-check with layer 2 and human review of low-confidence records.

**What it can tell you.** What the job holder does, how AI is used (tool, product, governance, data preparation, literacy, blurb), and whether a skill is required, preferred or only mentioned.

**What it cannot tell you.** Whether a model's reading is right in general. Kappa shows that two annotators agree, not that both are right. Quotes show where a label came from, not that the label is correct. Model versions drift: the same prompt can give different results on a later model, so the model id is stored.

**Worked example (toy): kappa.** 40 postings. Field: "AI used as an analyst tool". Worker A says yes for 10. Worker B says yes for 12. Both say yes for 8, so both say no for 26.
- Observed agreement: (8 + 26) / 40 = 0.85.
- Chance agreement: (10/40 × 12/40) + (30/40 × 28/40) = 0.075 + 0.525 = 0.60.
- Kappa = (0.85 - 0.60) / (1 - 0.60) = 0.625.

85% agreement looks high, but 60% of it is what two annotators would reach by chance because "no" is the common answer. Kappa 0.625 just passes the 0.60 target. Caution: when a label is very rare, kappa can look low even when agreement is high, so report counts and raw agreement beside kappa.

**Worked example (toy): an evidence quote.** Posting text: "Experience with Power BI is a plus." Record: `skill_id` `power_bi`, `requirement_level` `preferred`, `quote` "Experience with Power BI is a plus". The validator checks that this string is in the text after NFC normalisation and whitespace collapse, as specified by the guide.

**Cost and risk.**
- Volume per the plan: all 9,309 postings in the four main cells, plus a 20% double-annotated sample (about 1,862). That is about 11,200 calls. Open question 2 asks if a smaller US sample is enough.
- Cost per call = tokens in (fixed prompt + posting text) + tokens out (the JSON). `docs/PILOT50.md` reports measured subscription-CLI usage, component token estimates, runtime and validation failures for 50 postings. A fixed prompt prefix may be cached; do not assume its observed cache rate holds for a full run. Full-run size and dates remain undecided.
- Risks: a company blurb read as "AI as a tool" (guide categories and quotes); a posting that contains instructions (the prompt says the text is data); invented quotes (the validator); personal data in output (the validator); different results on a new model version (store model id, rerun the sample when it changes).

### 4.4 Layer 4: statistical comparison

The whole problem: a skill appears in k of n postings in cell a and in k of n in cell b. Is b really different, by how much, and how sure are we?

**Where it lives.** `src/stats.py` (every function has a test in `tests/test_stats.py`). `src/compare_eras.py`: `skill_comparison` (one table per panel), `word_log_odds`, `power_rows`, `draw_figures`.

**How to read one row of `skill_shift_<panel>.csv`.** Take Dashboards in P2:

| Column | Value | Meaning |
|---|---|---|
| `k_a` / `n_a`, `rate_a` | 37 / 141, 26.2% | VN_2022 mention rate |
| `wilson_a` | 19.7% to 34.1% | Likely range for the true 2022 rate |
| `k_b` / `n_b`, `rate_b` | 135 / 242, 55.8% | VN_2026 mention rate |
| `wilson_b` | 49.5% to 61.9% | Likely range for the true 2026 rate |
| `risk_difference_pp` | 29.5 | b minus a, in percentage points |
| `bootstrap_rd_pp` | 19.4 to 39.1 | Range for that difference by resampling |
| `weighted_rd_pp` | 33.3 | Difference after matching the 2022 seniority and region mix |
| `size_matched_share_p_lt_05` | 1.0 | Share of 200 equal-size subsamples with p below 0.05 |
| `risk_ratio` | 2.13 | 55.8 / 26.2 |
| `odds_ratio` (CI) | 3.55 (2.25 to 5.58) | Odds of a mention, b against a |
| `cohens_h` | 0.61 | Effect size on a common scale |
| `fisher_p` | 2.3e-8 | Exact test p-value |
| `bh_q` | 2.1e-6 | p-value corrected for 92 tests |

#### 4.4.1 Prevalence and the Wilson interval
- **What it is.** Prevalence is k out of n. An interval says how far the true rate could be from the measured one, given n is small.
- **Why Wilson.** The textbook interval (p plus or minus 1.96 times the standard error) has zero width when k is 0 and can go below 0. Wilson stays sensible at the edges and for small n.
- **Code.** `stats.wilson_interval`.
- **Tells you.** A range for each rate. Wide range means little information.
- **Cannot tell you.** It does not fix bias. A tight interval around a biased sample is still biased.
- **Worked example (real).** Any AI mention in VN_2022: 6 of 141 is 4.3%. Wilson: 2.0% to 9.0%. The textbook interval would give 0.9% to 7.6%. For 0 of 45 (any AI, platform 2022) the textbook interval is 0 to 0, while Wilson gives 0% to 7.9%: "zero in this sample" is not "zero in the market".

#### 4.4.2 Two-proportion comparison and Fisher's exact test
- **What it is.** Put the counts in a 2 by 2 table: rows are eras, columns are mention and no mention. The test asks: if both eras had the same true rate, how likely is a gap this large?
- **Why Fisher.** It uses the exact count of possible tables, so it is valid for small cells. A chi-square test needs expected counts of about 5 or more per cell.
- **Code.** `stats.fisher_exact` (scipy, two-sided), `stats.compare_prevalence`.
- **Tells you.** Whether a gap is bigger than chance alone would produce.
- **Cannot tell you.** The p-value is not the chance that the finding is true. It says nothing about size. With 6,381 postings, a 1 point change can give a tiny p-value.
- **Worked example (toy).** 3 of 4 postings mention a skill in era a, against 1 of 4 in era b. There are 4 mentions in all. By how many fall in era a (4, 3, 2, 1 or 0), the 5 possible tables have chances 1, 16, 36, 16 and 1 out of 70. The observed table (3 mentions in a) has 16 out of 70. Tables as rare or rarer: 1 + 16 + 16 + 1 = 34 out of 70, so p = 0.486. A 3-versus-1 split on 8 postings is no evidence at all.
- **Worked example (real).** Dashboards P2: table [[37, 104], [135, 107]], p = 2.3e-8. The odds are 135/107 = 1.26 in 2026 and 37/104 = 0.356 in 2022, a ratio of 3.55.

#### 4.4.3 Benjamini-Hochberg false discovery rate
- **What it is.** We test 92 skills per panel. If nothing changed at all, 5% would still pass at p below 0.05: about 4.6 false calls. **False discovery rate** is the expected share of false calls among the skills we call changed. Benjamini-Hochberg (BH) controls it. The adjusted p-value is the **q-value**. We call a skill changed when q is 0.10 or less (column `significant_q10`), meaning about 10% of the calls are expected to be false.
- **Why BH.** It is less strict than Bonferroni (which divides alpha by 92 and misses real changes), and it fits the aim: a shortlist where most items are real.
- **Code.** `stats.benjamini_hochberg`.
- **Tells you.** Which of 92 results survive after we admit we looked 92 times.
- **Cannot tell you.** Which individual call is wrong. The guarantee is proven for independent tests and for tests that move together in the same direction. Skill mentions are linked (for example, Power BI and dashboards), so this is a reasonable assumption, not a proof.
- **Worked example (toy).** p-values 0.001, 0.008, 0.039, 0.041, 0.60 (m = 5). Rank, then p times m divided by rank: 0.005, 0.02, 0.065, 0.0513, 0.60. Going from the largest rank down, keep the running minimum: q = 0.005, 0.02, 0.0513, 0.0513, 0.60. Four of five pass at q of 0.10.
- **Worked example (real).** P2 Power BI: p = 0.00067, q = 0.0056, so it passes. P2 Python: p = 0.28, q = 0.44, so it does not. In P2, 29 of 92 skills pass.

#### 4.4.4 Effect sizes
- **What it is.** The p-value says "probably not zero". Effect sizes say "how big": risk difference (percentage points), risk ratio (b divided by a), odds ratio with a Woolf interval (Haldane correction adds 0.5 to every cell when a cell is 0), and Cohen's h (difference of arcsine-square-root-transformed rates, comparable across skills with different base rates; rough guide: 0.2 small, 0.5 medium, 0.8 large).
- **Why.** A reader decides with size, not with p.
- **Code.** `stats.risk_difference`, `risk_ratio`, `odds_ratio_ci`, `cohens_h`.
- **Cannot tell you.** Importance to your career. A 20 point rise in a rare skill may matter less than a 5 point rise in a core one.
- **Worked example (real).** Dashboards P2: 55.8% vs 26.2% is +29.5 points, ratio 2.1, h = 0.61 (medium to large). Generative AI in P2: 0 of 141 to 8 of 242 (3.3%). The ratio is infinite and the odds ratio interval is 0.59 to 179 (a huge range). Only the point difference (+3.3 points) and its bootstrap range (1.2 to 5.8) are useful there.

#### 4.4.5 Bootstrap
- **What it is.** Redo the calculation on many random re-samples of the same data. Draw n postings with replacement from each cell, recompute the difference, repeat. The 2.5th and 97.5th percentiles of the results give an interval.
- **Why.** No formula is needed, so it works for odd statistics and small n. It is also a second opinion on the Fisher result.
- **Code.** `stats.bootstrap_ci`. `compare_eras.skill_comparison` uses 500 resamples and seed 0 (the function default is 2,000).
- **Cannot tell you.** It cannot create information. Resampling 45 postings still only knows those 45.
- **Worked example (toy).** Cell a: 5 postings, 2 mention (0.4). Cell b: 5 postings, 4 mention (0.8). Difference 0.4. One resample might draw a as 1,1,0,1,0 (0.6) and b as 1,1,1,0,1 (0.8), difference 0.2. Repeat 500 times, sort the differences, read the 2.5th and 97.5th percentiles.
- **Worked example (real).** Dashboards P2: +29.5 points, bootstrap 19.4 to 39.1. Python P2: +5.7 points, bootstrap -4.9 to 15.1. That range includes 0, which agrees with q of 0.44.

#### 4.4.6 Smallest detectable difference (power)
- **What it is.** For given sample sizes and a starting rate, the smallest rise a two-sided test (alpha 0.05) would see with 80% probability.
- **Why.** So "not significant" is never read as "no change".
- **Code.** `stats.minimum_detectable_difference`, `compare_eras.power_rows`, output `power_check.csv`.
- **Real values** (percentage points, starting rate 5% / 20% / 50%):

| Panel | n a | n b | 5% | 20% | 50% |
|---|---|---|---|---|---|
| P1 | 2,545 | 6,381 | 1.5 | 2.7 | 3.3 |
| P2 | 141 | 242 | 8.8 | 13.2 | 14.6 |
| P3 | 6,381 | 242 | 4.4 | 7.6 | 9.1 |
| S1 | 45 | 242 | 15.8 | 21.1 | 21.6 |

- **Worked example (real).** Python in P2 started near 35% and rose 5.7 points. P2 needs about 13 to 15 points at that start (between the 20% and 50% rows). So the test could not reliably see a 6 point rise. "No clear change" here means "too small a sample to tell", not "no change".

#### 4.4.7 Robustness: mix weights and size matching
- **Post-stratification (weights).** The 2026 cells hold more senior titles (and more Hanoi postings) than the 2022 cells. Part of a raw gap is "different mix". We re-weight cell b so its seniority mix (plus region for Vietnam) equals cell a's, then recompute the rate. `stats.post_stratified_rate`, `strata_shares`; strata are set in `extract_deterministic.stratum_of` (junior, mid, senior, lead_plus; Vietnam adds VN-HCM, VN-HN or other). Baseline strata missing from b are dropped and the rest are re-scaled; `strata_coverage` shows how much was kept (0.94 in P2, 1.0 in P1, P3, S1).
  - *Toy.* 2022 mix: 70% non-senior, 30% senior. 2026 mix: 50 and 50. 2026 rates for a skill: 20% (non-senior), 40% (senior). Raw 2026 rate = 0.5 × 0.2 + 0.5 × 0.4 = 30%. Re-weighted to the 2022 mix = 0.7 × 0.2 + 0.3 × 0.4 = 26%. So 4 points of the 2026 level came from having more seniors.
  - *Real.* Any AI in P1: raw +37.2 points, weighted +33.4. The rise holds after removing the seniority mix.
- **Size-matched replication.** When one cell is 50 times larger, the test is driven by the small cell. We draw 200 random subsamples of the larger cell at the smaller cell's size, repeat the test, and record the share with p below 0.05 (and the share with the same sign). `stats.size_matched_replication`, seed 0.
  - *Real.* Dashboards P2: 1.0 (holds every time). Python P2: 0.01 (almost never). S1 Power BI: 0.42 (passes the BH test at q of 0.074, but is fragile when sizes are matched at 45 against 45). S1 any AI: 0.72.
- **Cannot tell you.** Weights fix only the two mixes we measure. Platform, text length and wording are not fixed.

#### 4.4.8 Word-level log-odds with an informative Dirichlet prior
- **What it is.** For WORDS (unigrams and bigrams) rather than taxonomy skills. It ranks words by how typical they are of one cell over the other (Monroe, Colaresi and Quinn, 2008). Counts are the number of documents that contain the word.
- **Why.** A raw log-odds ratio explodes for rare words: a word in 3 postings of one era and 0 of the other looks "infinitely" typical. The prior adds pseudo-counts in proportion to how common the word is in both cells together, which pulls rare words toward zero. The z-score divides by the estimated spread, so words are ranked by evidence, not by raw gap.
- **Code.** `stats.log_odds_informative_dirichlet`; `compare_eras._word_log_odds_lang`. Done per language (English and Vietnamese separately, because mixing them only ranks each language's function words). Only terms in 3 or more documents and longer than 2 characters enter the tables. The top 40 per side are kept.
- **Tells you.** Words and phrases we did not list in the taxonomy that distinguish the cells.
- **Cannot tell you.** Meaning. A word is a clue to read in context. Boilerplate (equal-opportunity notices) can rank high.
- **Worked example (toy).** Each group has 1,000 word tokens. Word x: 3 in A, 0 in B. Word y: 300 in A, 200 in B. Pooled prior with alpha0 = 2,000 gives pseudo-counts 3 for x and 500 for y. Word x: log-odds difference 0.694, spread 0.707, z = 0.98. Word y: difference 0.178, spread 0.052, z = 3.44. The rare word that looked "infinitely distinctive" has the weaker evidence.
- **Worked example (real).** P1 English, more typical of 2026: "into clear" (in 14 of 2,545 US 2022 postings, 1,396 of 6,379 US 2026 postings, z = 8.35) and "translate" (249 vs 2,651, z = 7.19). This is the phrase "translate ... into clear, actionable insights". More typical of 2022: "remote", "covid", "vaccination" (README section 6.5).

### 4.5 Layer 5: unsupervised themes (TF-IDF, NMF, stability)

**What it is.** Layers 2 to 4 count only what we already knew to look for. A theme model lets the postings group themselves.
- **TF-IDF** gives each word in each document a weight. The weight rises with how often the word appears in that document and falls with how many documents use it. We use sub-linear term frequency (1 + ln of the count), words and word pairs, words in at least 3 documents (a name cannot define a theme) and at most 80% of documents.
- **NMF** (non-negative matrix factorisation) splits the document by word table into two smaller tables: documents by themes and themes by words. All values are 0 or more, so a theme is an additive list of words, and a document is a mix of themes.

**Why we chose it.** NMF on TF-IDF reads well for short documents and gives term weights you can read straight off the list. One alternative is LDA. Another option is k-means clustering. K-means gives each posting one cluster only; NMF lets a posting be a mix. We also report the "dominant" theme (the one with the highest weight) per posting for counting.

**Where it lives.** `src/themes.py`: `tokenize`, `fit_nmf` (8 themes, init `nndsvda`, up to 600 iterations), `stability`, `run_language`, `main --panel`. Output: `themes_<lang>_<panel>.csv` and `_stability.csv`. Two-word entries in `stopwords_vi.txt` ("cơ hội", "bảo hiểm") do not act as phrase stop words: scikit-learn warns about them and only the whole-token matches count.

**Stability check.** The model is fitted three times (seeds 0, 1, 2). Each theme of fit 0 is matched to its closest theme in the other fits by cosine similarity of the word weights. A score near 1 means the theme came back. A low score means the theme is noise.

**What it can tell you.** Themes you did not plan for, and how each cell's mix of themes differs.

**What it cannot tell you.**
- Whether 8 is the right number. K is a free choice and is not tuned in the code.
- Whether the themes would survive different documents. The stability test changes the random seed, not the data. A check that re-samples documents would be a stronger test.
- Vietnamese words. No word segmenter is used, so one-syllable pieces appear (for example "xây", "dựng", "xây dựng"). Two-syllable words appear through the word pairs; longer words are split.

**Worked example (toy): the IDF part.** 4 documents. "sql" appears in 3, "looker" in 1. The scikit-learn IDF is ln((1 + 4) / (1 + df)) + 1. So sql = ln(5/4) + 1 = 1.22 and looker = ln(5/2) + 1 = 1.92. A rare word weighs more. (Each document row is then scaled to length 1.)

**Worked example (real): Vietnam, Vietnamese text, P2** (97 postings in 2022, 180 in 2026; stability 1.0 for all 8 themes). The share of postings whose dominant theme is the one below (theme names are a plain-English reading of the top terms; the Vietnamese theme tables are produced locally and not published, so these numbers come from the local run):

| Theme (top terms, translated) | 2022 | 2026 |
|---|---|---|
| Sales, revenue, stock, Excel, figures | 13.4% | 25.0% |
| Insight, visual, statistics, effective | 11.3% | 18.9% |
| Banking, risk, operations, rollout | 16.5% | 25.6% |
| Independent research, learn, software | 6.2% | 0.6% |

**Worked example (real): what leaks.** English P1 (2,545 vs 6,379 postings): theme 7 (analytics, AI, insights, product, engineering, models, growth) is dominant in 6.1% of 2022 postings and 37.5% of 2026 postings. Theme 1 (analyst, reports, Excel, remote) falls from 75.7% to 25.9%. But theme 0 (equal-opportunity wording: "protected", "disability", "veteran") is also a theme, at 15.8% and 27.9%. This is boilerplate that survived the frequency rule. It is useful: it shows what is left to clean, and why themes are read beside the taxonomy, not instead of it. Stability for that panel: mean 0.96, lowest 0.69 (a theme about city residency and loan forgiveness). English P2 has a theme that is a job portal's sign-up footer (jobs, register, e-mail, password).

---

## 5. Validation and test strategy

### 5.1 The tests

`unittest`, no network, no downloads. 154 test methods in ten files (`.venv/bin/python -m unittest discover -s tests`). They also run in CI on every push.

| File | Methods | What it checks |
|---|---|---|
| `tests/test_build_corpus.py` | 16 | Boilerplate by frequency; rare line kept; exact and near duplicates dropped; short texts dropped; personal data never survives; HTML section cutting; missing values do not become "nan"; US location rule; the four loaders (US 2022 file, US 2026, Tinix, Wayback with gzip) on tiny fictional files; no loader for private collections; summary |
| `tests/test_common_and_extract.py` | 17 | NFC fixes word boundaries; personal data and phone stripping (years kept); language detection; role-family include and exclude; taxonomy is well formed; tricky tokens (R, SAS, AI, BI); years, seniority, degree, English, work mode and salary rules; cells are disjoint within a panel; no private cell or panel exists; stratum labels |
| `tests/test_stats.py` | 30 | Wilson (zero successes, all successes, empty, invalid); Fisher; BH (monotone, order kept, empty); effect sizes; log-odds (sign, shrinkage, symmetry); bootstrap (deterministic); kappa; minimum detectable difference; weights; size matching |
| `tests/test_compare_themes_check.py` | 8 | `compare_eras` rows, columns and sorting; power rows; word log-odds ranking; theme tokenizer, stability score and file output; both loaders of `us_instrument_check.py` on tiny fictional files |
| `tests/test_schema_and_docs.py` | 15 | Schema has all required fields, 3 key AI categories, an evidence quote on every judgement; guide names kappa and validation; committed results hold no e-mail or phone, no text column, only terms seen in 3 or more documents; docs have no placeholders; README names every script; data folder settings; `.gitignore` entries ; source wording, credits and licences say the same everywhere; Vietnamese theme tables are not tracked |
| `tests/test_public_safety.py` | 27 | The guard catches each leak type (e-mail also written "[at]" or "%40", phone shapes, private and temp paths, secrets, data folders and file types including PDF, SVG text, big files, long fields, long paragraphs, any long JSON string, private deny-list); history mode finds a secret that was committed and deleted, non-noreply identities and co-author lines; it never prints the matched value; this repository passes it |
| `tests/test_report.py` | 19 | The report page: embedded data equals the CSV files cell by cell, the "limits and risks" box under the title comes first and its numbers trace to the results files, the footer names the repository, the page equals a fresh build, prose numbers are looked up not typed, the platform-share note traces to `corpus_summary.csv`, only published theme tables are used, unglossed Vietnamese words are hidden, wording rules, nothing loads from outside, accessibility markup |
| `tests/test_demo_and_fixture.py` | 4 | The synthetic corpus equals what its generator writes, every document is marked fictional and short, every cell is covered, and the demo runs layers 2, 4 and 5 end to end |
| `tests/test_validate_annotations.py` | 11 | Schema, identity, taxonomy, quotes, years, evidence, personal data, warnings and CLI failure exit; fictional fixtures only |
| `tests/test_annotation_pilot.py` | 7 | Fixed-seed balanced public sampling, order independence, duplicate rejection, prompt separation, Unicode JSONL and single-count usage including recovered transport failures |

**Gaps.** The `html_to_job_text` rules are tested on small synthetic HTML only. The figure drawing and the full-size runs (millions of rows) are checked by reading the outputs, not by unit tests. Real-data numbers are not asserted in tests, because the downloads are not part of the repository.


### 5.2 The same-instrument US check
**Problem.** P1 sets a 2022 dataset against a 2026 dataset from another source. A platform change could look like a time change.

**Check.** Luke Barousse's datasets cover both eras with the same method and the same skill extraction. We compare the 2022 file (4,239 postings, Nov to Dec 2022) with the 2025-2026 release (20,638 postings, Jan to Jun 2026) on the 97 keywords that exist in both vocabularies. It has skills only, no text. Output: `us_same_instrument_skills.csv`, `us_same_instrument_meta.json`.

**Result, real** (mention rate change in points, 2022 to 2026):

| Skill | P1 (our text rules) | Same-instrument (author's skill tags) |
|---|---|---|
| Python | +14.8 | +7.9 |
| SQL | +6.5 | +4.0 |
| Excel | -5.4 | -8.3 |
| SAS | -4.1 | -7.7 |
| SPSS (P1: SPSS / Stata) | -1.4 | -6.2 |
| R | -0.7 (q = 0.45, not significant) | -5.3 |

The direction agrees for Python, SQL, Excel and SAS. The sizes differ, and the Python rise is about half in the same-instrument data. R and SPSS differ more. Likely reasons (not verified): the author's 2022 file is not de-duplicated (4,239 vs our 2,545), and our regex and his tags define skills differently. Reading: the direction of the main US findings does not depend on the source; the size does. Quote a range, not one number.

Two traps in this check. (1) "power bi" shows 0% in 2022 only because the 2022 vocabulary spells the tag differently, so it is not in the shared list. (2) Terms that exist only in the 2026 vocabulary (Claude 1.7%, ChatGPT 0.8%, Claude Code 0.6%) show 0 in 2022 by construction.

### 5.3 Sanity checks built into the design
1. **Tool-level checks.** Counts per source and per step are printed and written to `corpus_meta.json`.
2. **Funnel arithmetic.** Raw minus exact, near and short equals kept for every source (checked here: the sum of kept is 23,450, equal to `n_corpus`).
3. **Read the contexts.** Every pattern fix in the taxonomy came from counting hits per source and reading them.
4. **Directional agreement** between panels (P1 vs the same-instrument check; P2 vs S1). Example: SQL, Power BI and dashboards rise in both P2 and S1.
5. **Hygiene scan.** `tools/public_safety_check.py` scans every tracked file (and the tests run it) for e-mails, phones, private paths, long free-text fields, big files and data folders.
6. **Cells disjoint.** No posting is in both cells of a panel (tested).

---

## 6. Reproducibility

**Environment.** Python 3.12 virtual environment in `.venv` (ignored by git). Pinned in `requirements.txt` (main packages): numpy 2.5.3, pandas 3.0.6, scipy 1.18.1, scikit-learn 1.9.1, PyYAML 6.0.3, matplotlib 3.11.2, pyarrow 25.0.1.

**Commands** (from the README):

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests      # no downloads needed
.venv/bin/python tools/public_safety_check.py
export DAJS_DATA_DIR=/path/outside/the/repo/data    # or pass --data-root to each script
# put your own copy of the public data in $DAJS_DATA_DIR/raw/ first (see DATA_SOURCES.md)
sh run_all.sh                                       # or: sh run_all.sh <data-root> <results-dir>
.venv/bin/python tools/run_demo.py                  # synthetic demo, no downloads
```

`run_all.sh` runs, in order: `build_corpus.py`, `extract_deterministic.py`, `compare_eras.py`, `themes.py` once for each of P1, P2, P3 and S1, then `us_instrument_check.py`.

**Data folder layout.** `<data root>/raw/<source>/` holds your own copy of the public data (the download scripts are not published; folders are listed in `DATA_SOURCES.md`). `<data root>/corpus/` holds `corpus.jsonl`, `corpus_meta.json` and `extracted.csv`. The data root comes from `--data-root`, then `$DAJS_DATA_DIR`, then `./data/`.

**Fixed seeds.** Bootstrap 0 (500 resamples), size matching 0 (200 draws), NMF seeds 0, 1, 2. Results are the same on a rerun with the same package versions. The committed `results/` were produced by `run_all.sh` on the public downloads, and a second full run gave identical tables.

**Synthetic demo.** `examples/synthetic/corpus.jsonl` holds 268 fictional postings written by `tools/make_synthetic.py` (fixed seed, a test checks the file). `tools/run_demo.py` runs layers 2, 4 and 5 on it. The numbers are invented and only show that the machinery works.

**Gaps.** (1) The download scripts are not published, so you need your own copy of the public data. (2) Run time is about 10 minutes on a laptop; it is not benchmarked. (3) Raw downloads are snapshots: the US 2026 files and the Tinix set may change after 2026-10-04.

### 6.4 The report page

`scripts/build_report.py` reads only the aggregated files in `results/` and the group names in `taxonomy/skills.yaml`. It fills `scripts/report_template.html` and writes `report/index.html`, one file with the data embedded as JSON (about 80 KB) and all CSS and JavaScript inline. There is no external script, font, image or request, and no tracking. Numbers in the page text are looked up at build time with double-brace fields in the template (for example a cell size or a skill rate), so none is typed by hand. The charts are plain HTML and SVG (dots with 95% Wilson ranges, lines for the year-by-year view), each row is keyboard-focusable and has a text label, and a sortable table carries the same numbers.

Directly under the title sits a box headed "Read this first: limits and risks" (small samples, platform samples, platform mix, mentions not requirements, different periods, q-value above 0.10, exploratory, non-commercial). Its numbers come from the same fields. It has a high-contrast amber style in light and dark mode and one column on a phone.

Light and dark mode follow the system and a button. `tests/test_report.py` checks, cell by cell, that the embedded JSON equals the CSV files, that the committed page equals a fresh build, that the page loads nothing from outside, and that basic accessibility markup is present. `docs/PUBLISHING.md` explains how to publish it with GitHub Pages.

---

## 7. Known limitations and threats to validity (plain language)

| # | Threat | Plain meaning | What we did | What remains |
|---|---|---|---|---|
| 1 | Mentions are not requirements | A skill listed once as "nice to have" counts the same as a must-have | Stage 2 adds `requirement_level` | All stage 1 numbers are upper bounds |
| 2 | Selection bias | None of the sources is a random sample: each holds only what it happens to contain | Reported per source | Cells are not random samples of the market |
| 3 | Different instruments | US 2022 and US 2026 come from different pipelines. Vietnam 2022 mixes a short-text platform with longer portal pages | Same-instrument check, panel S1, weights | Sizes of changes are uncertain; directions are firmer |
| 4 | Small Vietnam 2022 sample | 141 postings (45 on the platform). A skill under about 10% in 2022 cannot be told from zero | Wilson intervals, power table | Only changes of about 9 to 15 points or more show in P2 (by starting rate) |
| 5 | Text length | A longer posting names more tools. Tinix medians are 1,081 and 1,804 characters, against 3,015 and 5,196 for the US cells | Lengths published | Rate per 1,000 characters is planned for stage 3 |
| 6 | Mix change | 2026 cells have more senior titles. Vietnam 2026 is 54% Hanoi on the platform against 24% in 2022 | Re-weighting | Weights fix mix only, not what Hanoi postings say |
| 7 | Regex errors | Misspellings and new product names are missed. Some generic words still match | Tests, context patterns, stage 2 cross-check | Unknown errors remain |
| 8 | LLM errors | Models over-read | Quotes, validation, kappa | Agreement is not accuracy |
| 9 | Many tests | 92 per panel | BH at q of 0.10 | About 10% of "changed" calls may be false |
| 10 | Dependence | Postings re-posted by the same company are not independent, and tests assume independence | Duplicates removed | Repeat employers with different adverts remain |
| 11 | No cause | We see change, not the reason | Claims limited to "mention rose" | Do not write "AI caused" |
| 12 | Unknown source detail | Tinix does not name the portal or confirm `year` | Same-instrument check | The year field stays unverified |
| 13 | Different eras and laws | US and Vietnam postings differ in what must be said (for example English: 3% of US 2026 postings and 24% of Vietnam 2026 postings mention English) | Reported | A difference in what needs saying, not in the role |

---

## 8. What stages 2 and 3 will add

| Stage | Adds | Needs |
|---|---|---|
| 2 | Annotate the four main cells with the schema; double-annotate 20%; kappa per field; `validate_annotations.py`; rerun layer 4 on annotated fields | A model and budget (open question 2). A pilot on about 50 postings |
| 3 | For each panel, mentioned and required side by side; AI split by role; rates per 1,000 characters; themes read against the taxonomy; limits beside every table; the report; reader notes on how to quote the numbers (BRD section 12) | Stage 2 output |
| 3, optional | A public-sector US panel from federal postings; a 2025 Vietnam reference set (48,092 postings, July to October 2025); a September 2026 multi-platform set (only 30 US Data Analyst family postings, so too small for a cell) | Licence and fit checks (see `DATA_SOURCES.md`) |

---

## 9. Glossary

| Term | Meaning |
|---|---|
| Annotation | Labelling a posting with the schema's fields |
| Benjamini-Hochberg (BH) | A method that controls the false discovery rate when many tests are run |
| Boilerplate | Text repeated across many postings (equal-opportunity notices, "apply now" footers) that says nothing about the role |
| Bootstrap | Redo a calculation on many random re-samples of the data to see how much it moves |
| Cell | One country and one era, built with one selection rule |
| Cohen's h | Effect size for a difference of two rates, comparable across different base rates |
| Cohen's kappa | Agreement between two annotators after removing the agreement expected by chance |
| Corpus | The set of cleaned postings |
| Effect size | How big a difference is, apart from how sure we are |
| False discovery rate | The expected share of false calls among the findings called significant |
| Fisher's exact test | A test for a 2 by 2 table that is valid for small counts |
| Jaccard similarity | Size of the overlap of two sets divided by the size of their union |
| Log-odds ratio | The log of the odds of a word in one group divided by the odds in another |
| Mention | A posting contains the term at least once. It does not mean the employer requires it |
| Minimum detectable difference | The smallest change the sample sizes can reliably show |
| NMF | Splits a document by word table into additive themes |
| Odds ratio | Odds of a mention in b divided by odds in a. Odds = k / (n - k) |
| p-value | Chance of a gap this large if there were no real difference. Not the chance the finding is true |
| Panel | A comparison of two cells |
| Percentage point (pp) | A difference between two percentages. 26% to 58% is +32 points |
| Post-stratification | Re-weighting one group so its mix (for example seniority) matches another |
| Prevalence | The share of postings that mention a term |
| Prior (Dirichlet) | Pseudo-counts added to word counts to shrink rare words toward zero |
| Q-value | A p-value adjusted for the number of tests |
| Regex | A text pattern used to find words |
| Requirement level | Stage 2 label: required, preferred or mentioned |
| Schema | A contract for the shape of a record |
| Shingle | A run of 5 words, used to compare texts |
| Stability (themes) | How well a theme returns when the model is refitted |
| Taxonomy | The versioned list of 91 skills and their patterns |
| TF-IDF | Word weight that rises with count in a document and falls with the number of documents using it |
| Wilson interval | A confidence interval for a rate that works for small n and rates near 0 or 1 |
| z-score | A gap divided by its estimated spread. Larger means more evidence |

---

## Appendix A. Requirement trace

| BR | Design element | TDD section | Code or file | Test or check |
|---|---|---|---|---|
| BR-01 | Panel P1, 92-skill table | 3, 4.4 | `compare_eras.skill_comparison`, `skill_shift_P1_us_2022_vs_2026.csv` | `test_stats.py`; same-instrument check (5.2) |
| BR-02 | Panel P2 and S1, yearly trend | 3, 4.4 | `skill_shift_P2_*.csv`, `skill_shift_S1_*.csv`, `tinix_vn_yearly_trend.csv` | `test_stats.py`; P2 vs S1 direction check |
| BR-03 | Panel P3 | 3, 4.4 | `skill_shift_P3_*.csv` | `test_stats.py` |
| BR-04 | `requirement_level` field, guide rules | 4.3 | `schema/jd_annotation.schema.json`, `docs/ANNOTATION_GUIDE.md` | `test_schema_and_docs.py` (schema); validator tests built; kappa pending |
| BR-05 | `ai_roles` field, 7 categories | 4.3 | Same | `test_ai_role_categories`; annotation pending |
| BR-06 | Wilson, Fisher, BH, bootstrap, power | 4.4.1 to 4.4.6 | `stats.py`, `power_check.csv` | `test_stats.py` |
| BR-07 | Weights, size matching, S1, same-instrument | 3, 4.4.7, 5.2 | `stats.post_stratified_rate`, `size_matched_replication`, `us_instrument_check.py` | Weighting tests in `test_stats.py`; `CellAndStratumTests`; `UsInstrumentTests` |
| BR-08 | Anyone can try the project without downloads | 6 | `examples/synthetic/corpus.jsonl`, `tools/make_synthetic.py`, `tools/run_demo.py` | `test_demo_and_fixture.py` |
| BR-09 | TF-IDF, NMF, stability | 4.5 | `themes.py`, `themes_*.csv` | `ThemeTests`; stability scores in `_stability.csv` |
| BR-10 | Stripping, data folder outside git, public-safety guard | 2.3 | `common.strip_personal_data`, `tools/public_safety_check.py` | `test_personal_data_never_survives`, `test_results_have_no_personal_data`, `test_public_safety.py` |
| BR-11 | Licence record, aggregates only | 2.1, 7 | `DATA_SOURCES.md` | `test_docs_have_no_unfilled_placeholders_or_personal_data` |
| BR-12 | `run_all.sh`, pinned versions, seeds, synthetic demo | 6 | `run_all.sh`, `requirements.txt`, `tools/run_demo.py` | `test_demo_and_fixture.py`; two full runs gave the same tables |
| BR-13 | This document, README glossary | 4, 9 | `docs/TDD.md`, `README.md` | `test_readme_names_every_script`; reader review (AC-10) |
| BR-14 | Limits section, power table | 4.4.6, 7 | README 6.4, this document | Review in stage 3 |
| BR-15 | Reader notes: how to read and quote the results | 8 and BRD 12 | Not built | Reader review |
| BR-17 | Interactive report page, numbers traced to results | 6.4 | `scripts/build_report.py`, `scripts/report_template.html`, `report/index.html` | `tests/test_report.py` |
| BR-16 | Rate per 1,000 characters | 4.1, 7, 8 | Not built. `corpus_summary.csv` has lengths | Stage 3 |

---

## Open questions

1. **Dates.** When should stage 2 and stage 3 be done? No dates are set.
2. **Stage 2 size.** Annotate all 9,309 postings (about 11,200 calls with the 20% second pass), or all 383 Vietnam postings plus a sample of the US cells? Which model and what budget?
3. **Tinix 2026 total.** The platform has 46,736 postings for 2026 against 160,386 for 2025, and the Data Analyst share goes from 0.04% (2022) to 0.52% (2026). Is 2026 a partial year, or a different sample? The dataset card does not say. This affects how far VN_2026 is comparable.
4. **Question wording.** Is "how the Data Analyst role moved from the late-2022 AI baseline to 2026" the wording to keep?
5. **US 2022 count (resolved by pilot audit).** 2,545 is correct, not 2,544: independent raw-source cleaning, the corpus and the extracted table agree, with 2,545 distinct ids. See `PILOT50.md` for the evidence and the Tinix record-versus-unique-text distinction.
