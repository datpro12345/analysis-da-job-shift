"""Shared helpers for the Data Analyst job-shift study.

Everything here is deterministic and dependency-light (stdlib + PyYAML) so the
tests run fast and the rules are easy to read. The heavy lifting (pandas,
scipy, scikit-learn) lives in the scripts that need it.

Paths
-----
The repository never stores job-description text. Scripts read raw sources from
and write the corpus to a *data root* chosen in this order:

1. ``--data-root`` on the command line;
2. the ``DAJS_DATA_DIR`` environment variable;
3. ``<repo>/data/`` (gitignored fallback, see .gitignore).

Inside the data root: ``raw/<source folder>/`` holds the downloads
(``scripts/fetch_data.py`` fills it) and ``corpus/`` holds the cleaned corpus
and the per-document table. Only ``results/`` (aggregated counts, no text) is
committed.

Text cleaning
-------------
* Unicode NFC normalisation. Some Vietnamese sources store letters in
  decomposed form ("ị" = "i" + a combining mark). Regex word boundaries then
  misfire: "BI" matches the start of "bị". NFC first, always.
* Personal data stripping: e-mails, phone numbers, Zalo/Telegram handles,
  "Contact: Ms. X" lines. Job text is data about a role, not about a person.
* Boilerplate: lines repeated across many postings of one source (EEO notices,
  "apply now" footers) are removed in build_corpus.py by frequency, not by a
  hand list, so the rule is the same for every source.
"""
from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent
REPO_ROOT = SRC_DIR.parent
TAXONOMY_PATH = REPO_ROOT / "taxonomy" / "skills.yaml"
STOPWORDS_VI_PATH = REPO_ROOT / "taxonomy" / "stopwords_vi.txt"
RESULTS_DIR = REPO_ROOT / "results"
DATA_ENV_VAR = "DAJS_DATA_DIR"

ERAS = ("2022", "2026")


def data_root(cli_value: str | None = None) -> Path:
    """Resolve where raw inputs and the corpus live (never inside git)."""
    if cli_value:
        return Path(cli_value).expanduser().resolve()
    env = os.environ.get(DATA_ENV_VAR)
    if env:
        return Path(env).expanduser().resolve()
    return REPO_ROOT / "data"


def raw_dir(root: Path) -> Path:
    """Downloads live in <data root>/raw/<source folder>/."""
    return root / "raw"


def corpus_dir(root: Path) -> Path:
    """The cleaned corpus and the per-document table live in <data root>/corpus/."""
    return root / "corpus"


# ----------------------------------------------------------------- text basics
_WS = re.compile(r"[ \t ​]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def normalize_text(text: str) -> str:
    """NFC-normalise, unify line endings, collapse runs of spaces and blank lines."""
    text = unicodedata.normalize("NFC", text or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(_WS.sub(" ", line).strip() for line in text.split("\n"))
    text = _BLANK_LINES.sub("\n\n", text)
    return text.strip()


def doc_id_for(text: str) -> str:
    """Stable 16-hex id from the cleaned text (SHA-256 prefix)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


_VI_LETTERS = re.compile(r"[ăâđêôơưàáảãạèéẻẽẹìíỉĩịòóỏõọùúủũụỳýỷỹỵ]", re.I)


def detect_language(text: str) -> str:
    """'vi' when Vietnamese letters are common, else 'en'.

    Tool names and English requirements appear inside Vietnamese postings, so
    the rule is a share of alphabetic characters that carry Vietnamese marks:
    above 2 % reads as Vietnamese. A mixed posting counts as 'vi' because its
    duties are written in Vietnamese even when the tools are English.
    """
    letters = sum(ch.isalpha() for ch in text)
    if letters == 0:
        return "en"
    return "vi" if len(_VI_LETTERS.findall(text)) / letters > 0.02 else "en"


# ------------------------------------------------------- personal-data removal
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Vietnamese mobiles (0xx / +84), international numbers, and dotted or spaced
# groups. Requires at least 9 digits so ordinary numbers (years, salaries)
# survive.
PHONE = re.compile(r"(?<![\w])(?:\+?84|0)(?:[\s.\-]?\d){8,10}(?!\d)|(?<![\w])\+\d{1,3}(?:[\s.\-]?\d){8,12}(?!\d)")
HANDLE = re.compile(r"\b(?:zalo|telegram|skype|whatsapp|viber|line)\s*[:\-]?\s*[@\w.+\-]{3,}", re.I)
CONTACT_LINE = re.compile(
    r"^(?:contact|contact person|liên hệ|lh|người liên hệ|hotline|recruiter|hr contact|email|e-mail|phone|tel|mobile|zalo|skype)\b.*$",
    re.I | re.M,
)
HONORIFIC_NAME = re.compile(r"\b(?:Ms|Mr|Mrs|Miss|Anh|Chị|Cô|Chú)\.?\s+[A-ZÀ-Ỹ][\w'À-ỹ]+(?:\s+[A-ZÀ-Ỹ][\w'À-ỹ]+){0,3}")
URL_WITH_USER = re.compile(r"[a-z][a-z0-9+.-]*://[^/\s@]+@\S+", re.I)


def strip_personal_data(text: str) -> str:
    """Remove recruiter contacts. Replaces with a marker so sentence structure survives."""
    text = CONTACT_LINE.sub("", text)
    text = URL_WITH_USER.sub("[url]", text)
    text = EMAIL.sub("[email]", text)
    text = HANDLE.sub("[handle]", text)
    text = PHONE.sub("[phone]", text)
    text = HONORIFIC_NAME.sub("[name]", text)
    return normalize_text(text)


# ----------------------------------------------------------- role-family rules
# The study is about the Data Analyst family. Titles decide membership because
# bodies of adjacent roles (engineer, scientist) also talk about SQL and
# dashboards. The exclusion list wins over the inclusion list. The same rule is
# applied to every cell (US and Vietnam, 2022 and 2026). Vietnamese variants:
# "phân tích dữ liệu / số liệu" (data / figures analysis), "chuyên viên BI",
# "chuyên viên MIS" (bank reporting analysts), "báo cáo và phân tích".
DA_FAMILY_INCLUDE = re.compile(
    r"(data\s*analy|business\s*intelligence|\bBI\s*(?:analyst|developer|engineer|specialist|consultant|lead|manager|intern|expert|report)"
    r"|(?:senior|junior|lead|data|analytics|intern|thực\s*tập)\s*-?\s*BI\b"
    r"|ph[âa]n\s*t[íi]ch\s*(?:d[ữu]|s[ốo])\s*li[ệe]u|data\s*analytics|\banalytics\b|insights?\s*(?:analyst|manager|lead|specialist|consultant)"
    r"|(?:chuy[êe]n\s*vi[êe]n|nh[âa]n\s*vi[êe]n|chuy[êe]n\s*gia)\s*(?:BI|MIS)\b|\bMIS\s*(?:analyst|report|&|and)|\bBI\s*(?:&|and|/)\s*(?:MIS|report|data)"
    r"|reporting\s*analyst|data\s*&\s*insights?|data\s*and\s*insights?|data\s*reporting|reporting\s*(?:&|and)\s*insights?"
    r"|chuy[êe]n\s*vi[êe]n\s*d[ữu]\s*li[ệe]u|b[áa]o\s*c[áa]o\s*v[àa]\s*ph[âa]n\s*t[íi]ch)",
    re.I,
)
DA_FAMILY_EXCLUDE = re.compile(
    r"(data\s*engineer|data\s*scien|machine\s*learning|\bML\b|k[ỹy]\s*s[ưu]\s*d[ữu]\s*li[ệe]u|khoa\s*h[ọo]c\s*d[ữu]\s*li[ệe]u|\bAI\s*engineer"
    r"|software\s*engineer|\bdeveloper\b(?!.*\bBI\b)|thi[ếe]t\s*b[ịi]|v[òo]ng\s*bi\b|bida\b|bi[êe]n\s*t[ậa]p)",
    re.I,
)


def is_da_family(title: str) -> bool:
    t = normalize_text(title)
    return bool(DA_FAMILY_INCLUDE.search(t)) and not DA_FAMILY_EXCLUDE.search(t)


# ------------------------------------------------------------------ taxonomy
def load_taxonomy(path: Path = TAXONOMY_PATH) -> dict:
    import yaml  # local import keeps common.py importable without PyYAML for the pure-regex helpers

    with open(path, encoding="utf-8") as fh:
        tax = yaml.safe_load(fh)
    ids = [s["id"] for s in tax["skills"]]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate skill ids in taxonomy")
    for skill in tax["skills"]:
        if skill["group"] not in tax["groups"]:
            raise ValueError(f"{skill['id']}: unknown group {skill['group']!r}")
        skill["_ci"] = [re.compile(p, re.I) for p in skill.get("patterns", [])]
        skill["_cs"] = [re.compile(p) for p in skill.get("patterns_cs", [])]
    return tax


def load_stopwords_vi(path: Path = STOPWORDS_VI_PATH) -> list[str]:
    words = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            words.append(normalize_text(line).lower())
    return sorted(set(words))
