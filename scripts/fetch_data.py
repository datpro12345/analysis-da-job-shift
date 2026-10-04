#!/usr/bin/env python3
"""Download the public sources into <data root>/raw/ (ignored by git).

What it does
  * prints every source with its licence, URL and approximate size first;
  * reads robots.txt of each host (wildcard rules included) and refuses a URL
    that robots.txt disallows, also after a redirect;
  * waits between requests to the same host (default 3 s, Wayback 4 s);
  * needs no login, no API key, no cookie; Python standard library only;
  * writes DOWNLOAD_NOTE.txt (URL, UTC time, size, SHA-256) next to each file;
  * skips files that already exist (use --force to download again).

Sources that robots.txt forbids to automated clients (GitHub release files)
are listed as MANUAL: the script prints the URLs and you download them by hand.

Usage
  python scripts/fetch_data.py --list                  # offline: show sources and licences
  python scripts/fetch_data.py --dry-run               # HEAD requests: show real sizes
  python scripts/fetch_data.py                         # download everything automatic
  python scripts/fetch_data.py --only tinix_vn,us_open_2026
  python scripts/fetch_data.py --gsearch-mirror        # US 2022 from the big Hugging Face mirror

Data root: --data-root, else $DAJS_DATA_DIR, else ./data (see README.md).
Licences: DATA_SOURCES.md has the full record. Redistribute nothing you download.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

USER_AGENT = "da-job-shift-fetch/1.0 (open research; no login; respects robots.txt)"
AGENT_TOKEN = "da-job-shift-fetch"
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
CAPTURES_CSV = HERE / "wayback_vn_2022_captures.csv"
DATA_ENV_VAR = "DAJS_DATA_DIR"
CHUNK = 1 << 20


@dataclass
class RemoteFile:
    url: str
    name: str
    approx_mb: float


@dataclass
class Source:
    key: str
    title: str
    folder: str
    licence: str
    files: list[RemoteFile] = field(default_factory=list)
    kind: str = "files"          # "files", "wayback" or "manual"
    delay: float = 3.0
    note: str = ""


def md_files(months=range(1, 9)) -> list[RemoteFile]:
    return [RemoteFile(f"https://us.data.motherduck.com/job_postings/parquet/year=2026/month={m:02d}/jobs.parquet", f"jobs_2026_{m:02d}.parquet", 13.0) for m in months]


GH_RELEASE = "https://github.com/lukebarousse/dbt_Analytics_Engineering_Course/releases/download/dataset-v1"
SOURCES: list[Source] = [
    Source("gsearch_us_2022", "US 2022: 'Data Analyst Job Postings' (Luke Barousse), 2022 split", "gsearch_jobs_us_2022",
           "Apache 2.0 (original dataset on Kaggle)",
           [RemoteFile("https://raw.githubusercontent.com/iweld/data-analyst-job-postings/main/source_data/csv/gsearch_jobs_2022.csv", "gsearch_jobs_2022.csv", 27.0)],
           note="Copy of the Kaggle data. Alternative: --gsearch-mirror."),
    Source("us_open_2026", "US 2026: open job postings (public parquet files), months 01-08", "us_job_postings_2026",
           "Local use only. Publish aggregates only; never redistribute the files", md_files()),
    Source("tinix_vn", "Vietnam platform 2022-2026: Tinix Vietnamese Job Descriptions", "tinixai_vietnamese_job_descriptions",
           "CC BY-NC 4.0 (attribution, non-commercial)",
           [RemoteFile("https://huggingface.co/datasets/tinixai/vietnamese-job-descriptions/resolve/main/data.parquet", "data.parquet", 293.0),
            RemoteFile("https://huggingface.co/datasets/tinixai/vietnamese-job-descriptions/resolve/main/README.md", "README.md", 0.02)]),
    Source("wayback_vn_2022", "Vietnam 2022: archived portal pages (Internet Archive captures)", "wayback_vn_2022",
           "Third-party copyright of the portals. Aggregates only", kind="wayback", delay=4.0,
           note="Reads scripts/wayback_vn_2022_captures.csv; about 124 pages."),
    Source("datanerd_us_2025_2026", "US skills check: datanerd.tech 2026 release (skills only)", "datanerd_us_2025_2026",
           "Skill counts only; never redistribute the files", kind="manual",
           files=[RemoteFile(f"{GH_RELEASE}/raw_job_postings_2026-{m:02d}.parquet", f"raw_job_postings_2026-{m:02d}.parquet", 2.0) for m in range(1, 7)]
           + [RemoteFile(f"{GH_RELEASE}/raw_job_skills.parquet", "raw_job_skills.parquet", 58.0)],
           note="github.com robots.txt disallows automated release downloads: download these files by hand."),
]
GSEARCH_MIRROR = RemoteFile("https://huggingface.co/datasets/Etietop/data_analyst_jobs/resolve/main/gsearch_jobs.csv", "gsearch_jobs_hf_mirror.csv", 228.0)


# ------------------------------------------------------------------ robots.txt
class RobotsDenied(Exception):
    pass


def parse_robots(text: str, agent: str = AGENT_TOKEN) -> list[tuple[bool, str]]:
    """Allow/Disallow rules that apply to `agent`: its own group if present, else the '*' group."""
    groups: list[tuple[list[str], list[tuple[bool, str]]]] = []
    agents: list[str] = []
    rules: list[tuple[bool, str]] = []
    last_was_agent = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = (x.strip() for x in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if not last_was_agent:
                if agents:
                    groups.append((agents, rules))
                agents, rules = [], []
            agents.append(value.lower())
            last_was_agent = True
        elif key in ("allow", "disallow"):
            last_was_agent = False
            if value or key == "allow":
                rules.append((key == "allow", value))
            # an empty Disallow means "allow everything": no rule needed
        else:
            last_was_agent = False
    if agents:
        groups.append((agents, rules))
    own = [r for a, r in groups if any(x != "*" and x in agent.lower() for x in a)]
    star = [r for a, r in groups if "*" in a]
    chosen = own or star
    return [rule for r in chosen for rule in r]


def _pattern_regex(pattern: str) -> re.Pattern:
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    rx = "".join(".*" if ch == "*" else re.escape(ch) for ch in body)
    return re.compile("^" + rx + ("$" if anchored else ""))


def robots_allows(rules: list[tuple[bool, str]], path: str) -> bool:
    """Longest matching pattern wins; Allow wins a tie; no match means allowed."""
    best_len, allowed = -1, True
    for allow, pattern in rules:
        if pattern == "":
            continue
        if _pattern_regex(pattern).match(path):
            n = len(pattern)
            if n > best_len or (n == best_len and allow):
                best_len, allowed = n, allow
    return allowed


class Fetcher:
    """urllib wrapper: robots.txt check on every URL and redirect, per-host delay, fixed User-Agent."""

    def __init__(self, delay: float = 3.0, sleep=time.sleep, clock=time.monotonic, timeout: float = 60.0):
        self.delay, self.sleep, self.clock, self.timeout = delay, sleep, clock, timeout
        self._robots: dict[str, list[tuple[bool, str]]] = {}
        self._last: dict[str, float] = {}
        fetcher = self

        class Handler(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                fetcher.check(newurl)
                return super().redirect_request(req, fp, code, msg, headers, newurl)

        self.opener = urllib.request.build_opener(Handler)
        self.opener.addheaders = [("User-Agent", USER_AGENT)]

    def _wait(self, host: str, delay: float) -> None:
        last = self._last.get(host)
        if last is not None:
            gap = delay - (self.clock() - last)
            if gap > 0:
                self.sleep(gap)
        self._last[host] = self.clock()

    def rules_for(self, url: str) -> list[tuple[bool, str]]:
        parts = urllib.parse.urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            self._wait(parts.netloc, self.delay)
            try:
                with self.opener.open(origin + "/robots.txt", timeout=self.timeout) as resp:
                    self._robots[origin] = parse_robots(resp.read().decode("utf-8", "replace"))
            except urllib.error.HTTPError as exc:
                # 4xx (no robots.txt): everything allowed. 5xx: be safe, treat as disallow all.
                self._robots[origin] = [(False, "/")] if exc.code >= 500 else []
            except urllib.error.URLError:
                self._robots[origin] = [(False, "/")]
        return self._robots[origin]

    def check(self, url: str) -> None:
        parts = urllib.parse.urlsplit(url)
        path = parts.path + (("?" + parts.query) if parts.query else "")
        if not robots_allows(self.rules_for(url), path or "/"):
            raise RobotsDenied(f"robots.txt of {parts.netloc} disallows {parts.path}")

    def open(self, url: str, method: str = "GET", delay: float | None = None):
        self.check(url)
        self._wait(urllib.parse.urlsplit(url).netloc, self.delay if delay is None else delay)
        req = urllib.request.Request(url, method=method)
        return self.opener.open(req, timeout=self.timeout)


# --------------------------------------------------------------------- helpers
def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def data_root(cli_value: str | None) -> Path:
    if cli_value:
        return Path(cli_value).expanduser().resolve()
    env = os.environ.get(DATA_ENV_VAR)
    return Path(env).expanduser().resolve() if env else REPO_ROOT / "data"


def raw_dir_is_safe(raw: Path, repo: Path = REPO_ROOT) -> bool:
    """True when downloads cannot end up in git: outside the repository, or ignored by git."""
    raw = raw.resolve()
    try:
        raw.relative_to(repo.resolve())
    except ValueError:
        return True
    try:
        probe = raw / "probe.parquet"
        return subprocess.run(["git", "-C", str(repo), "check-ignore", "-q", str(probe)], capture_output=True).returncode == 0
    except OSError:
        return False


def print_plan(sources: list[Source], raw: Path) -> None:
    total = 0.0
    for s in sources:
        tag = {"manual": "MANUAL download", "wayback": "slow, rate-limited download from the Internet Archive", "files": "automatic"}[s.kind]
        mb = sum(f.approx_mb for f in s.files) if s.files else 3.0
        total += mb if s.kind != "manual" else 0
        print(f"[{s.key}] {s.title}")
        print(f"    licence : {s.licence}")
        print(f"    how     : {tag}; about {mb:,.0f} MB; into {raw / s.folder}")
        for f in s.files[:3]:
            print(f"    url     : {f.url}")
        if len(s.files) > 3:
            print(f"    url     : ... and {len(s.files) - 3} more like it")
        if s.note:
            print(f"    note    : {s.note}")
    print(f"automatic downloads total: about {total:,.0f} MB. Redistribute nothing you download (see DATA_SOURCES.md).")


def write_note(folder: Path, lines: list[str]) -> None:
    with (folder / "DOWNLOAD_NOTE.txt").open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def download_file(fetcher: Fetcher, rf: RemoteFile, folder: Path, force: bool, delay: float) -> Path:
    dest = folder / rf.name
    if dest.exists() and dest.stat().st_size > 0 and not force:
        print(f"    have {rf.name} ({dest.stat().st_size / 1048576:.1f} MB), skipped")
        return dest
    folder.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    digest, size = hashlib.sha256(), 0
    with fetcher.open(rf.url, delay=delay) as resp, part.open("wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        next_mark = 0.1
        while True:
            chunk = resp.read(CHUNK)
            if not chunk:
                break
            out.write(chunk)
            digest.update(chunk)
            size += len(chunk)
            if total and size / total >= next_mark:
                print(f"    {rf.name}: {100 * size / total:.0f} %")
                next_mark += 0.1
    part.replace(dest)
    write_note(folder, [f"downloaded: {utc_now()} from {rf.url}", f"file: {rf.name} bytes: {size} sha256: {digest.hexdigest()}"])
    print(f"    saved {rf.name}: {size / 1048576:.1f} MB, sha256 {digest.hexdigest()[:16]}...")
    return dest


def fetch_files(fetcher: Fetcher, src: Source, raw: Path, force: bool, files: list[RemoteFile] | None = None) -> None:
    for rf in files or src.files:
        download_file(fetcher, rf, raw / src.folder, force, src.delay)


MANIFEST_FIELDS = ["site", "timestamp", "original_url", "wayback_url", "file", "http_status", "bytes", "fetched_at_utc"]


def read_captures(path: Path = CAPTURES_CSV) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def fetch_wayback(fetcher: Fetcher, src: Source, raw: Path, force: bool, limit: int | None = None) -> None:
    """Fetch the listed captures (original HTML, `id_` form) one by one and write manifest.csv."""
    folder = raw / src.folder
    folder.mkdir(parents=True, exist_ok=True)
    manifest = folder / "manifest.csv"
    done: set[tuple[str, str]] = set()
    if manifest.exists() and not force:
        with manifest.open(encoding="utf-8") as fh:
            done = {(r["timestamp"], r["original_url"]) for r in csv.DictReader(fh) if r["http_status"] == "200"}
    new_file = not manifest.exists() or force
    captures = [c for c in read_captures() if (c["timestamp"], c["original_url"]) not in done]
    if limit is not None:
        captures = captures[:limit]
    print(f"    {len(captures)} captures to fetch, {src.delay:.0f} s apart")
    with manifest.open("w" if new_file else "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=MANIFEST_FIELDS)
        if new_file:
            writer.writeheader()
        for i, c in enumerate(captures, 1):
            wb = f"https://web.archive.org/web/{c['timestamp']}id_/{c['original_url']}"
            name = f"{c['site']}/{c['site']}_{c['timestamp']}_{hashlib.sha256(c['original_url'].encode()).hexdigest()[:10]}.html"
            status, body = 0, b""
            try:
                with fetcher.open(wb, delay=src.delay) as resp:
                    status, body = resp.status, resp.read()
            except urllib.error.HTTPError as exc:
                status = exc.code
            except urllib.error.URLError as exc:
                print(f"    network error on capture {i}: {exc.reason}")
            if status == 200:
                (folder / c["site"]).mkdir(exist_ok=True)
                (folder / name).write_bytes(body)
            writer.writerow({"site": c["site"], "timestamp": c["timestamp"], "original_url": c["original_url"], "wayback_url": wb,
                             "file": name if status == 200 else "", "http_status": status, "bytes": len(body), "fetched_at_utc": utc_now()})
            fh.flush()
            if i % 20 == 0:
                print(f"    {i}/{len(captures)}")
    write_note(folder, [f"fetched: {utc_now()} from web.archive.org, captures listed in scripts/wayback_vn_2022_captures.csv"])


def print_manual(src: Source, raw: Path) -> None:
    print(f"  MANUAL: download these files yourself into {raw / src.folder}")
    for f in src.files:
        print(f"    {f.url}")


def head_size(fetcher: Fetcher, rf: RemoteFile) -> str:
    try:
        with fetcher.open(rf.url, method="HEAD") as resp:
            n = resp.headers.get("Content-Length")
            return f"{int(n) / 1048576:.1f} MB" if n else "size unknown"
    except RobotsDenied as exc:
        return f"blocked by robots.txt ({exc})"
    except (urllib.error.URLError, OSError) as exc:
        return f"not reachable ({exc})"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-root", help="default: $DAJS_DATA_DIR or ./data")
    ap.add_argument("--only", help="comma-separated source keys: " + ", ".join(s.key for s in SOURCES))
    ap.add_argument("--list", action="store_true", help="show sources and licences, no network")
    ap.add_argument("--dry-run", action="store_true", help="HEAD requests only: show real sizes, download nothing")
    ap.add_argument("--force", action="store_true", help="download again even if the file exists")
    ap.add_argument("--delay", type=float, default=None, help="seconds between requests to one host (default 3, Wayback 4)")
    ap.add_argument("--gsearch-mirror", action="store_true", help="US 2022 from the large Hugging Face mirror instead of the 2022 split")
    ap.add_argument("--wayback-limit", type=int, default=None, help="fetch only the first N archive captures (testing)")
    args = ap.parse_args(argv)

    chosen = [s for s in SOURCES if not args.only or s.key in {k.strip() for k in args.only.split(",")}]
    unknown = {k.strip() for k in (args.only or "").split(",") if k.strip()} - {s.key for s in SOURCES}
    if unknown:
        print(f"unknown source key(s): {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2
    if args.gsearch_mirror:
        chosen = [Source(**{**s.__dict__, "files": [GSEARCH_MIRROR]}) if s.key == "gsearch_us_2022" else s for s in chosen]
    raw = data_root(args.data_root) / "raw"
    print(f"data folder: {raw}\n")
    print_plan(chosen, raw)
    if args.list:
        return 0
    if not raw_dir_is_safe(raw):
        print("refusing: the data folder is inside the repository and git does not ignore it", file=sys.stderr)
        return 2
    fetcher = Fetcher(delay=args.delay if args.delay is not None else 3.0)
    print()
    status = 0
    for s in chosen:
        print(f"== {s.key}")
        if args.delay is not None:
            s.delay = args.delay
        if s.kind == "manual":
            print_manual(s, raw)
            continue
        if args.dry_run:
            for f in (s.files[:3] if s.kind == "files" else []):
                print(f"    {f.name}: {head_size(fetcher, f)}")
            continue
        try:
            if s.kind == "wayback":
                fetch_wayback(fetcher, s, raw, args.force, args.wayback_limit)
            else:
                fetch_files(fetcher, s, raw, args.force)
        except RobotsDenied as exc:
            print(f"    skipped: {exc}. Download by hand from the URL above.")
            status = 1
        except (urllib.error.URLError, OSError) as exc:
            print(f"    failed: {exc}", file=sys.stderr)
            status = 1
    print("\ndone." if status == 0 else "\nfinished with problems (see above).")
    return status


if __name__ == "__main__":
    sys.exit(main())
