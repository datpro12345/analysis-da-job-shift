# Data sources

The study uses **publicly available job postings, Vietnam and US, 2022 and 2026**.
Source data stays on your own computer: it is git-ignored and local only, and
**nothing raw is committed**. This repository **redistributes nothing but
aggregates** (counts, rates, statistics, figures). You download the sources
yourself with `scripts/fetch_data.py`, which prints each source, its licence
and its size, and lists the exact download addresses.

Licences of this repository: code MIT, documentation CC BY 4.0, results and the
data embedded in the report page CC BY-NC 4.0 (see the README, section 10).
**Non-commercial note:** the results are derived from data licensed
CC BY-NC 4.0, so use them for non-commercial purposes only.

## Cells

Selection is the same in every cell: Data Analyst family **title**
(`common.is_da_family`), same cleaning, same taxonomy, same rules.

| Cell | Postings | Years | n (Data Analyst family) | Language |
|---|---|---|---|---|
| US_2022 | publicly available US job postings | 2022 (Nov to Dec) | 2,545 | English |
| US_2026 | publicly available US job postings | 2026 (Jan to Aug) | 6,381 | English |
| VN_2022 | publicly available Vietnamese job postings: 45 from a job platform and 96 archived pages | 2022 | 141 | mostly Vietnamese |
| VN_2026 | publicly available Vietnamese job postings from a job platform | 2026 | 242 | mostly Vietnamese |
| VN_platform_2022 / 2026 | the platform postings alone | 2022 / 2026 | 45 / 242 | Vietnamese |
| US same-pipeline check | skill counts only, no text | 2022 (Nov to Dec) and 2026 (Jan to Jun) | 4,239 and 20,638 | English |

Comparability limits: cells differ in text length, seniority mix and region mix
(Vietnam 2026 is 54 % Hanoi against 24 % in 2022 on the platform). The 2022 and
2026 US cells come from different datasets, so a same-pipeline skill check is
reported next to them. Vietnam 2022 is small (141 postings, 45 on the platform).

## Credits and licences

| # | Dataset (credit) | Used for | Licence |
|---|---|---|---|
| 1 | "Data Analyst Job Postings [Pay, Skills, Benefits]", Luke Barousse (Kaggle) | US 2022 cell and the US check | Apache 2.0 |
| 2 | Public US job postings, 2026 (dataset address in `scripts/fetch_data.py`) | US 2026 cell | local use only; aggregates published |
| 3 | "Vietnamese Job Descriptions", Tinix (Hugging Face) | Vietnam cells | CC BY-NC 4.0 ([licence text](https://creativecommons.org/licenses/by-nc/4.0/)) |
| 4 | Internet Archive (archived Vietnamese portal pages) | Vietnam 2022 cell | aggregates published |
| 5 | datanerd.tech 2025-2026 release, Luke Barousse | US same-pipeline check | skill counts only |

**Citation required by the Tinix dataset (CC BY-NC 4.0 requires credit):**
Le, Hoang, Tran, Vuong. "CareerPathKG: Knowledge Graph Integrated Framework for
Career Intelligence". EACL 2026 Industry Track, pp. 813-822.
doi:10.18653/v1/2026.eacl-industry.60.

`scripts/fetch_data.py` reads robots.txt for every host, waits between requests
and needs no login. Where a host's robots.txt forbids automated download (the
GitHub release files of source 5), the script prints the addresses and you
download them by hand.

## Counts by source

| Source | Rows or pages | After cleaning | Data Analyst family |
|---|---|---|---|
| US 2022 (source 1) | 5,488 rows dated 2022 | 3,450 (1,448 exact re-posts, 332 near-duplicates, 258 too short removed) | 2,545 |
| US 2026 (source 2) | 83,446 rows in 2026, 24,659 with a US location | 19,340 | 6,381 |
| Vietnam platform (source 3), 2022 / 2023 / 2024 / 2025 / 2026 | 59 / 55 / 93 / 136 / 247 rows with Data Analyst family titles | 45 / 49 / 76 / 125 / 242 | 45 / 49 / 76 / 125 / 242 |
| Vietnam 2022 archived pages (source 4) | 184 pages obtained, 124 parsed as job pages | 123 | 96 |
| US check, 2022 file and 2026 release (sources 1 and 5) | skills only | | 4,239 and 20,638 |

The Vietnamese platform has 606,878 postings in total, 2022 to 2026. Its
`year` field cannot be checked against the original pages. Benefits text is
left out on every Vietnamese source so cells stay comparable. For the US 2026
set a posting counts as US when its location text is "City, ST" with a real
state code, "United States" or "USA", or a US metro phrase; "Remote" alone is
dropped because the country is unknown.

## Tried and not used

| Source | Why not |
|---|---|
| Glints (29 archived pages) | The Vietnam path also lists Indonesian and Taiwanese jobs; body is client-rendered |
| VietnamWorks keyword pages (41) | Search listings, not postings |
| Other Vietnamese portals in the archive | Only listing pages, nothing for 2022, or the index timed out |
| NextGig multi-ATS snapshot (CC BY 4.0) | `job_description` is an LLM-written summary, not the posting |
| Tech jobs from 9 ATS platforms, Sept 2026 (CC BY 4.0) | Only 30 US Data Analyst family postings |
| Indeed sample 2026, USAJOBS, VietJobs, lukebarousse/data_jobs, Djinni | Too small, off-family, one season only, no text, or another market. Possible stage 3 extras |
| Kaggle Vietnamese job set, Adzuna, USAJobs API | Need a login or an API key |

## What could not be obtained

* Vietnamese 2022 postings with full text: 141 in total. Anything under about 10 % in 2022 cannot be told from zero.
* Vietnamese 2022 postings from LinkedIn: none retrievable.
* US 2026 postings with text from the same pipeline as US 2022: none. The skill-level check is the bridge.
