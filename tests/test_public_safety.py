"""The public-safety guard: it must catch each kind of leak, and the repository itself must pass it."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import public_safety_check as psc  # noqa: E402

# Every "leak" below is built at run time from parts, so this file holds none of them as a literal.
AT = "@"
FAKE_EMAIL = "someone" + AT + "gmail.com"
FAKE_PHONE_VN = "09" + "12 345 678"
FAKE_PHONE_INTL = "+1 " + "212 5" + "55 0123"
HOME = "/" + "Users" + "/someone/project"
TMP = "/" + "private" + "/" + "var" + "/x/y"
NOREPLY_ADDR = "1234+someone" + AT + "users.noreply.github.com"


def scan(files: dict[str, str], **kw):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for name, content in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        return psc.run(root, denylist=[], **kw)


def rules(problems):
    return sorted({p[2] for p in problems})


class DetectionTests(unittest.TestCase):
    def test_clean_files_pass(self):
        self.assertEqual(scan({"README.md": "Aggregates only. Contact: see the issue tracker.\n", "results/a.csv": "skill,rate\nsql,0.5\n"}), [])

    def test_email_is_caught_but_example_domains_are_allowed(self):
        self.assertEqual(rules(scan({"a.md": f"write to {FAKE_EMAIL}\n"})), ["email"])
        self.assertEqual(scan({"a.md": "write to person" + AT + "example.com or x" + AT + "mail.example.invalid\n"}), [])

    def test_phone_numbers_are_caught(self):
        for number in (FAKE_PHONE_VN, FAKE_PHONE_INTL, "(212) " + "555-0123"):
            with self.subTest(number=number):
                self.assertEqual(rules(scan({"a.md": f"call {number} now\n"})), ["phone"])

    def test_obfuscated_emails_are_caught(self):
        for text in ("someone [a" + "t] gmail [d" + "ot] com", "someone(a" + "t)gmail.com", "someone%4" + "0gmail.com", "someone {a" + "t} gmail {d" + "ot} com"):
            with self.subTest(text=text):
                self.assertEqual(rules(scan({"a.md": f"write to {text} now\n"})), ["email"])
        self.assertEqual(scan({"a.md": "mail it available at github.com or at the office.\n"}), [])

    def test_more_phone_shapes_are_caught(self):
        for number in ("555 1" + "23 4567", "555.1" + "23.4567", "+84 (0) " + "91" + "2 345 678", "(555) 1" + "23-4567"):
            with self.subTest(number=number):
                self.assertEqual(rules(scan({"a.md": f"call {number} now\n"})), ["phone"])

    def test_svg_text_nodes_are_checked_but_coordinates_are_not(self):
        self.assertEqual(rules(scan({"results/f.svg": f'<svg><text x="1">call {FAKE_PHONE_VN} now</text></svg>'})), ["phone"])
        self.assertEqual(rules(scan({"results/f.svg": f'<svg><text>write {FAKE_EMAIL}</text></svg>'})), ["email"])
        coords = " ".join(["M", "0", "100", "288", "576.0", "0", "912", "345", "678"])
        self.assertEqual(scan({"results/f.svg": f'<svg><path d="{coords}"/><text>Dashboards</text></svg>'}), [])

    def test_pdf_is_blocked(self):
        self.assertEqual(rules(scan({"docs/a.pdf": "%PDF-1.4 fake"})), ["path"])

    def test_temp_and_home_relative_paths_are_caught(self):
        self.assertEqual(rules(scan({"run.sh": f"cd {TMP}\n"})), ["path-leak"])
        self.assertEqual(rules(scan({"run.sh": "cd ~/" + "Documents/project\n"})), ["path-leak"])

    def test_long_paragraphs_in_text_files_are_caught_but_tables_code_and_short_items_pass(self):
        long = "word " * 300
        self.assertEqual(rules(scan({"notes.md": f"Title\n\n{long}\n"})), ["long-text"])
        self.assertEqual(rules(scan({"notes.txt": "\n".join(["line of a pasted posting"] * 120)})), ["long-text"])
        self.assertEqual(rules(scan({"notes.md": f"- {long}\n"})), ["long-text"])
        self.assertEqual(scan({"notes.md": f"| a | b |\n|---|---|\n| {long} | x |\n\n```\n{long}\n```\n\n- short item\n- another\n"}), [])

    def test_long_strings_in_any_json_file_are_caught(self):
        long = "word " * 120
        self.assertEqual(rules(scan({"notes/a.json": '{"text": "' + long + '"}'})), ["long-text"])

    def test_ordinary_numbers_are_not_phones(self):
        text = "n=2545, rate 0.123456789, id 20221026204120, p=1.1e-300, hash 0123456789abcdef, 70,000,000 VND\n"
        self.assertEqual(scan({"a.md": text}), [])

    def test_private_path_is_caught(self):
        self.assertEqual(rules(scan({"run.sh": f"cd {HOME}\n"})), ["path-leak"])

    def test_secret_is_caught(self):
        self.assertEqual(rules(scan({"a.txt": "token = ghp_" + "a" * 36 + "\n"})), ["secret"])

    def test_data_and_raw_folders_are_forbidden(self):
        for name in ("data/x.txt", "raw/x.txt", "corpus/x.txt", "a/data/x.txt"):
            with self.subTest(name=name):
                self.assertEqual(rules(scan({name: "x\n"})), ["path"])

    def test_data_file_types_and_jsonl_location(self):
        self.assertEqual(rules(scan({"a.parquet": "x"})), ["path"])
        self.assertEqual(rules(scan({"results/a.jsonl": '{"a": 1}\n'})), ["path"])
        self.assertEqual(scan({"examples/synthetic/a.jsonl": '{"a": 1}\n'}), [])

    def test_html_only_for_the_report_and_it_must_be_self_contained(self):
        self.assertEqual(rules(scan({"pages/a.html": "<p>x</p>"})), ["path"])
        self.assertEqual(scan({"report/index.html": '<a href="https://example.org/">link</a><script>var a = 1;</script>'}), [])
        for bad in ('<script src="https://cdn.example.org/x.js"></script>', '<link rel="stylesheet" href="a.css">', "<style>@import url(x.css);</style>",
                    '<img src="https://example.org/a.png">', "<style>a{background:url(https://example.org/a.png)}</style>"):
            with self.subTest(bad=bad):
                self.assertEqual(rules(scan({"report/index.html": bad})), ["external"])

    def test_big_file_is_caught(self):
        self.assertEqual(rules(scan({"big.txt": "x\n\n" * 1000}, max_bytes=2000)), ["size"])

    def test_long_free_text_fields_are_caught(self):
        long = "word " * 120
        self.assertEqual(rules(scan({"results/a.csv": f"id,text\n1,{long}\n"})), ["long-text"])
        self.assertEqual(rules(scan({"examples/synthetic/c.jsonl": '{"text": "' + long + '"}\n'})), ["long-text"])
        self.assertEqual(rules(scan({"results/a.json": '{"note": "' + long + '"}'})), ["long-text"])
        self.assertEqual(scan({"schema/s.json": '{"description": "' + long + '"}'}), [])  # schema prose is documentation

    def test_output_never_echoes_the_secret_value(self):
        problems = scan({"a.md": f"{FAKE_EMAIL} {FAKE_PHONE_VN}\n"})
        shown = " ".join(p[3] for p in problems)
        self.assertNotIn("gmail", shown)
        self.assertNotIn("345", shown)

    def test_private_denylist_from_outside_the_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            deny = Path(tmp) / "deny.txt"
            deny.write_text("# private\nfictional\\s+person\n", encoding="utf-8")
            old = os.environ.get("DAJS_PRIVATE_DENYLIST")
            os.environ["DAJS_PRIVATE_DENYLIST"] = str(deny)
            try:
                loaded = psc.load_denylist()
                root = Path(tmp) / "repo"; root.mkdir()
                (root / "a.md").write_text("by Fictional Person\n", encoding="utf-8")
                self.assertEqual(rules(psc.run(root, denylist=loaded)), ["denylist"])
            finally:
                os.environ.pop("DAJS_PRIVATE_DENYLIST", None)
                if old is not None:
                    os.environ["DAJS_PRIVATE_DENYLIST"] = old


class HistoryTests(unittest.TestCase):
    def repo(self, tmp, files_per_commit, author=NOREPLY_ADDR, message="add files"):
        env = {**os.environ, "GIT_AUTHOR_NAME": "A", "GIT_AUTHOR_EMAIL": author, "GIT_COMMITTER_NAME": "A", "GIT_COMMITTER_EMAIL": author}
        root = Path(tmp)
        subprocess.run(["git", "init", "-q", str(root)], check=True, env=env)
        for files in files_per_commit:
            for name, content in files.items():
                path = root / name
                if content is None:
                    path.unlink()
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content, encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "-A"], check=True, env=env)
            subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", message], check=True, env=env)
        return root

    def test_clean_history_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.repo(tmp, [{"a.md": "hello\n"}])
            self.assertEqual(psc.run_history(root, denylist=[]), [])

    def test_a_secret_that_was_committed_and_deleted_is_still_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.repo(tmp, [{"a.md": f"mail {FAKE_EMAIL}\n"}, {"a.md": None, "b.md": "clean\n"}])
            self.assertEqual(psc.run(root, denylist=[]), [])                       # the working tree is clean
            self.assertEqual(rules(psc.run_history(root, denylist=[])), ["email"])  # the history is not

    def test_identities_and_coauthor_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.repo(tmp, [{"a.md": "x\n"}], author="someone" + AT + "gmail.com")
            self.assertEqual(rules(psc.run_history(root, denylist=[])), ["identity"])
        with tempfile.TemporaryDirectory() as tmp:
            root = self.repo(tmp, [{"a.md": "x\n"}], message="add\n\nCo-authored-by: Bot <" + NOREPLY_ADDR + ">")
            self.assertEqual(rules(psc.run_history(root, denylist=[])), ["email", "identity"])

    def test_deny_list_applies_to_history_and_messages(self):
        deny = [__import__("re").compile("fictional person", __import__("re").I)]
        with tempfile.TemporaryDirectory() as tmp:
            root = self.repo(tmp, [{"a.md": "by Fictional Person\n"}], message="by Fictional Person")
            self.assertEqual(rules(psc.run_history(root, denylist=deny)), ["denylist"])


class RepositoryTests(unittest.TestCase):
    def test_this_repository_is_clean(self):
        problems = psc.run(ROOT, denylist=[])
        self.assertEqual(problems, [], "\n".join(f"{n}:{l}: {r}: {d}" for n, l, r, d in problems))

    def test_this_repository_history_is_clean(self):
        problems = psc.run_history(ROOT, denylist=[])
        # during development the history may hold older commits; the squashed release commit must pass
        self.assertEqual(problems, [], "\n".join(f"{n}:{l}: {r}: {d}" for n, l, r, d in problems))

    def test_command_line_exit_codes(self):
        ok = subprocess.run([sys.executable, str(ROOT / "tools" / "public_safety_check.py"), "--root", str(ROOT)], capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0, ok.stdout)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.md").write_text(f"mail {FAKE_EMAIL}\n", encoding="utf-8")
            bad = subprocess.run([sys.executable, str(ROOT / "tools" / "public_safety_check.py"), "--root", tmp], capture_output=True, text=True)
        self.assertEqual(bad.returncode, 1)
        self.assertIn("FAIL", bad.stdout)


if __name__ == "__main__":
    unittest.main()
