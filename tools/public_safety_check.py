#!/usr/bin/env python3
"""Public-safety guard: fail when the repository holds anything that must not be public.

Checks every tracked file (and every untracked file that git does not ignore):

  path       a file under a data/, raw/ or corpus/ folder, or a data-file type
             (parquet, sqlite, zip, pdf, ...); .jsonl only under examples/synthetic/;
             .html only for the report (report/ and scripts/report_template.html)
  external   a report page that loads anything from outside (script, stylesheet,
             font, image, frame, @import); plain links (<a href>) are fine
  size       a file over 2 MB
  email      an e-mail address, also written "[at]", "(at)" or "%40" (only RFC 2606
             example domains are allowed)
  phone      a phone-number pattern (Vietnamese, international, US style, also with
             spaces or dots and "+84 (0)")
  path-leak  a private path: a user home folder, a system temp folder or a home-relative folder
  long-text  a csv/tsv/jsonl cell, or a json string (outside schema/), longer than
             400 characters; a prose paragraph or list item over 1200 characters in
             a .md or .txt file. That is job-posting text, not an aggregate
  secret     a private key or an API-token pattern
  denylist   any line of the optional private deny-list file (a regex per line)
             named by $DAJS_PRIVATE_DENYLIST. Keep that file OUTSIDE the repo: it
             is where you list your own name, employers and so on.

In SVG files the text nodes are checked too (drawing coordinates are not).
With --history the same checks run on every file in every commit, and every
author and committer address must be a GitHub noreply address, with no
Co-authored-by line.

Output never prints the matched value in full (it is masked), so a log of this
tool cannot leak what it found. Exit code 0 = clean, 1 = violations.

Usage:  python tools/public_safety_check.py [--root DIR] [--history] [--max-field 400] [--max-mb 2]
Standard library only.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

MAX_BYTES = 2 * 1024 * 1024
MAX_FIELD = 400
MAX_PARAGRAPH = 1200
FORBIDDEN_DIRS = {"data", "raw", "corpus"}
DATA_SUFFIXES = {".parquet", ".feather", ".pkl", ".pickle", ".sqlite", ".sqlite3", ".db", ".zip", ".gz", ".tar", ".7z", ".xlsx", ".xls", ".docx", ".pdf", ".html", ".htm", ".warc"}
REPORT_DIR = "report"
REPORT_TEMPLATE = ("scripts", "report_template.html")
EXTERNAL = re.compile(r"<script[^>]+\bsrc\s*=|<link\b|<iframe|<embed|<object|<img[^>]+\bsrc\s*=\s*[\"']?(?:https?:)?//|@import|url\(\s*[\"']?(?:https?:)?//|<form[^>]+\baction\s*=\s*[\"']?https?:", re.I)
SYNTHETIC_DIR = ("examples", "synthetic")
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules"}
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico"}
NOREPLY = re.compile(r"@users\.noreply\.github\.com$", re.I)

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
EMAIL_OBFUSCATED = re.compile(r"[\w.+-]{2,}\s*(?:\[at\]|\(at\)|\{at\}|<at>|%40)\s*[\w-]{2,}(?:\s*(?:\[dot\]|\(dot\)|\{dot\}|<dot>|\.)\s*[a-z]{2,})+", re.I)
ALLOWED_EMAIL_DOMAIN = re.compile(r"@(?:[\w-]+\.)*(?:example\.(?:com|org|net)|[\w-]+\.invalid|example|test|localhost)$", re.I)
PHONES = [
    re.compile(r"(?<![\w.])(?:\+?84|0)[\s.-]?\d{2,3}[\s.-]?\d{3}[\s.-]?\d{3,4}(?![\w])"),          # Vietnamese
    re.compile(r"(?<![\w.])\+\d{1,3}[\s.-]?\(0\)[\s.-]?\d{2,4}[\s.-]?\d{3,4}[\s.-]?\d{3,4}(?![\w])"),  # +84 (0) 90 ...
    re.compile(r"(?<![\w.])\+\d{1,3}[\s.-]?\(?\d{2,4}\)?[\s.-]?\d{3,4}[\s.-]?\d{3,4}(?![\w])"),   # international
    re.compile(r"(?<![\w.])\(?\d{3}\)[\s.-]?\d{3}[\s.-]?\d{4}(?![\w])|(?<![\w.])\d{3}[-\s.]\d{3}[-\s.]\d{4}(?![\w])"),  # US style
]
PATH_LEAKS = [re.compile("/" + "Users" + "/"), re.compile(r"[A-Za-z]:\\" + "Users" + r"\\"), re.compile("/" + "home" + r"/[a-z][\w.-]+/"),
              re.compile("/" + "private" + "/"), re.compile("/" + "var" + "/" + "folders" + "/"), re.compile("~/(?:Documents|Desktop|Downloads|Library)\\b")]
SECRETS = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----|\bAKIA[0-9A-Z]{16}\b|\bghp_[A-Za-z0-9]{30,}|\bsk-[A-Za-z0-9]{32,}|\bhf_[A-Za-z0-9]{30,}")
SVG_TEXT = re.compile(r">([^<>]{3,})<")


def mask(value: str) -> str:
    value = value.strip()
    return value[:2] + "*" * max(3, min(len(value) - 2, 8))


def list_files(root: Path) -> list[Path]:
    """Tracked plus untracked-not-ignored files when root is a git repo, else a plain walk."""
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                             capture_output=True, check=True).stdout.decode("utf-8", "replace")
        rels = [r for r in out.split("\0") if r]
        return sorted(root / r for r in rels if (root / r).is_file())
    except (OSError, subprocess.CalledProcessError):
        found = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            found += [Path(dirpath) / f for f in filenames]
        return sorted(found)


def load_denylist() -> list[re.Pattern]:
    path = os.environ.get("DAJS_PRIVATE_DENYLIST")
    if not path or not Path(path).is_file():
        return []
    pats = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            pats.append(re.compile(line, re.I))
    return pats


# ------------------------------------------------------------ structured data
def long_fields(suffix: str, text: str, rel: tuple[str, ...], max_field: int) -> list[tuple[int, int]]:
    """(line, length) of every free-text field over max_field characters in a data-like file."""
    hits = []
    if suffix in (".csv", ".tsv"):
        reader = csv.reader(io.StringIO(text), delimiter="\t" if suffix == ".tsv" else ",")
        try:
            for row in reader:
                for cell in row:
                    if len(cell) > max_field:
                        hits.append((reader.line_num, len(cell)))
        except csv.Error:
            pass
    elif suffix in (".jsonl", ".ndjson"):
        for n, line in enumerate(text.splitlines(), 1):
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            hits += [(n, length) for length in _string_lengths(obj) if length > max_field]
    elif suffix == ".json" and rel[0] != "schema":  # schema prose is documentation
        try:
            hits += [(1, length) for length in _string_lengths(json.loads(text)) if length > max_field]
        except ValueError:
            pass
    return hits


def _string_lengths(obj):
    if isinstance(obj, str):
        yield len(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _string_lengths(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _string_lengths(v)


def long_paragraphs(text: str, limit: int = MAX_PARAGRAPH) -> list[tuple[int, int]]:
    """(line, length) of prose paragraphs or list items over `limit` characters. Tables, headings and code fences are skipped."""
    hits, fence = [], False
    cur_start, cur_len = 0, 0

    def close():
        nonlocal cur_len
        if cur_len > limit:
            hits.append((cur_start, cur_len))
        cur_len = 0

    for n, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith("```"):
            close(); fence = not fence
            continue
        if fence or not line.strip() or line.lstrip().startswith(("|", "#")):
            close()
            continue
        if re.match(r"\s*(?:[-*+]|\d+\.)\s", line):
            close()
        if cur_len == 0:
            cur_start = n
        cur_len += len(line.strip()) + 1
    close()
    return hits


# ------------------------------------------------------------------- checkers
def scan_text(name: str, text: str, line_offset_text: str | None, denylist: list[re.Pattern], skip_phone: bool = False) -> list[tuple[str, int, str, str]]:
    """Email, phone, path, secret and deny-list checks, line by line."""
    problems: list[tuple[str, int, str, str]] = []
    for n, line in enumerate(text.splitlines(), 1):
        for m in EMAIL.finditer(line):
            if not ALLOWED_EMAIL_DOMAIN.search(m.group(0)):
                problems.append((name, n, "email", mask(m.group(0))))
        for m in EMAIL_OBFUSCATED.finditer(line):
            plain = re.sub(r"\s*(?:\[at\]|\(at\)|\{at\}|<at>|%40)\s*", "@", m.group(0), flags=re.I)
            plain = re.sub(r"\s*(?:\[dot\]|\(dot\)|\{dot\}|<dot>)\s*", ".", plain, flags=re.I)
            if not ALLOWED_EMAIL_DOMAIN.search(plain):
                problems.append((name, n, "email", mask(m.group(0))))
        if not skip_phone:
            for rx in PHONES:
                for m in rx.finditer(line):
                    digits = sum(ch.isdigit() for ch in m.group(0))
                    if digits >= 9 and not re.fullmatch(r"\d+\.\d+", m.group(0)):  # one dot = a decimal number
                        problems.append((name, n, "phone", mask(m.group(0))))
        for rx in PATH_LEAKS:
            m = rx.search(line)
            if m:
                problems.append((name, n, "path-leak", mask(m.group(0))))
        m = SECRETS.search(line)
        if m:
            problems.append((name, n, "secret", mask(m.group(0))))
        for rx in denylist:
            m = rx.search(line)
            if m:
                problems.append((name, n, "denylist", mask(m.group(0))))
    return problems


def check_content(name: str, rel: tuple[str, ...], data: bytes, max_bytes: int, max_field: int, denylist: list[re.Pattern]) -> list[tuple[str, int, str, str]]:
    """All checks for one file given its repository path and bytes (a working-tree file or a blob from history)."""
    problems: list[tuple[str, int, str, str]] = []
    suffix = Path(name).suffix.lower()
    if FORBIDDEN_DIRS & set(rel[:-1]):
        problems.append((name, 0, "path", "file under a data/, raw/ or corpus/ folder"))
    is_report = suffix in (".html", ".htm") and (rel[0] == REPORT_DIR or rel == REPORT_TEMPLATE)
    if suffix in DATA_SUFFIXES and not is_report:
        problems.append((name, 0, "path", f"data-file type {suffix}"))
    if suffix in (".jsonl", ".ndjson") and rel[:2] != SYNTHETIC_DIR:
        problems.append((name, 0, "path", ".jsonl is only allowed under examples/synthetic/"))
    if len(data) > max_bytes:
        problems.append((name, 0, "size", f"{len(data) / 1048576:.1f} MB is over the limit"))
    if suffix in BINARY_SUFFIXES or (suffix in DATA_SUFFIXES and not is_report):
        return problems
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        problems.append((name, 0, "path", "binary or non-UTF-8 file"))
        return problems
    if suffix == ".svg":
        # drawing coordinates look like numbers: check only the text nodes (and e-mails everywhere)
        for m in EMAIL.finditer(text):
            if not ALLOWED_EMAIL_DOMAIN.search(m.group(0)):
                problems.append((name, 0, "email", mask(m.group(0))))
        texts = "\n".join(SVG_TEXT.findall(text))
        problems += [(name, 0, r, d) for _, _, r, d in scan_text(name, texts, None, denylist) if r in ("phone", "denylist", "path-leak", "secret")]
        for rx in PATH_LEAKS:
            if rx.search(text):
                problems.append((name, 0, "path-leak", "private path in SVG"))
    else:
        if is_report:
            for n, line in enumerate(text.splitlines(), 1):
                if EXTERNAL.search(line):
                    problems.append((name, n, "external", "the report loads something from outside"))
        problems += scan_text(name, text, None, denylist)
    for n, length in long_fields(suffix, text, rel, max_field):
        problems.append((name, n, "long-text", f"field of {length} characters (limit {max_field})"))
    if suffix in (".md", ".txt"):
        for n, length in long_paragraphs(text):
            problems.append((name, n, "long-text", f"paragraph of {length} characters (limit {MAX_PARAGRAPH})"))
    return problems


def check_file(root: Path, path: Path, max_bytes: int, max_field: int, denylist: list[re.Pattern]) -> list[tuple[str, int, str, str]]:
    rel_path = path.relative_to(root)
    return check_content(rel_path.as_posix(), rel_path.parts, path.read_bytes(), max_bytes, max_field, denylist)


def run(root: Path, max_bytes: int = MAX_BYTES, max_field: int = MAX_FIELD, denylist: list[re.Pattern] | None = None) -> list[tuple[str, int, str, str]]:
    root = root.resolve()
    deny = load_denylist() if denylist is None else denylist
    problems = []
    for path in list_files(root):
        problems += check_file(root, path, max_bytes, max_field, deny)
    return problems


# -------------------------------------------------------------------- history
def git_bytes(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=True).stdout


def run_history(root: Path, max_bytes: int = MAX_BYTES, max_field: int = MAX_FIELD, denylist: list[re.Pattern] | None = None) -> list[tuple[str, int, str, str]]:
    """The same checks on every distinct file version in every commit, plus identities and messages."""
    root = root.resolve()
    deny = load_denylist() if denylist is None else denylist
    problems: list[tuple[str, int, str, str]] = []
    # what a push can send: HEAD, branches, tags and remote branches (not stashes or other worktrees)
    commits = git_bytes(root, "rev-list", "HEAD", "--branches", "--tags", "--remotes").decode().split()
    seen: set[tuple[str, str]] = set()
    for c in commits:
        short = c[:8]
        meta = git_bytes(root, "log", "-1", "--format=%an%n%ae%n%cn%n%ce%n%B", c).decode("utf-8", "replace").split("\n")
        for who, addr in ((meta[0], meta[1]), (meta[2], meta[3])):
            if not NOREPLY.search(addr):
                problems.append((f"commit {short}", 0, "identity", f"address {mask(addr)} is not a GitHub noreply address"))
        message = "\n".join(meta[4:])
        if re.search(r"co-authored-by", message, re.I):
            problems.append((f"commit {short}", 0, "identity", "Co-authored-by line"))
        problems += [(f"commit {short} message", n, r, d) for _, n, r, d in scan_text("message", message, None, deny)]
        for entry in git_bytes(root, "ls-tree", "-r", "-z", c).split(b"\0"):
            if not entry:
                continue
            head, _, path = entry.partition(b"\t")
            sha = head.split()[2].decode()
            name = path.decode("utf-8", "replace")
            if (sha, name) in seen:
                continue
            seen.add((sha, name))
            data = git_bytes(root, "cat-file", "blob", sha)
            for p in check_content(name, tuple(Path(name).parts), data, max_bytes, max_field, deny):
                problems.append((f"{p[0]} (in {short})", p[1], p[2], p[3]))
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--max-field", type=int, default=MAX_FIELD, help="longest allowed csv/jsonl field in characters")
    ap.add_argument("--max-mb", type=float, default=MAX_BYTES / 1048576, help="largest allowed file in MB")
    ap.add_argument("--history", action="store_true", help="also check every file version in every commit, and commit identities")
    args = ap.parse_args(argv)
    root = Path(args.root)
    problems = run(root, int(args.max_mb * 1048576), args.max_field)
    if args.history:
        problems += run_history(root, int(args.max_mb * 1048576), args.max_field)
    for name, line, rule, detail in problems:
        print(f"{name}{':' + str(line) if line else ''}: {rule}: {detail}")
    n_files = len(list_files(root.resolve()))
    if problems:
        print(f"FAIL: {len(problems)} problem(s) in {n_files} files")
        return 1
    print(f"OK: {n_files} files checked{' and the full history' if args.history else ''}, nothing private found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
