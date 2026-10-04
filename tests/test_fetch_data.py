"""fetch_data.py: robots.txt rules, rate limit, download notes. Uses a local HTTP server only (no internet)."""
import contextlib
import hashlib
import io
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import fetch_data as fd  # noqa: E402

PAYLOAD = b"fictional,bytes\n1,2\n" * 50
ROBOTS = "User-agent: *\nDisallow: /closed/\nDisallow: /*/blocked$\n"
OWN_GROUP_ROBOTS = ROBOTS + "\nUser-agent: da-job-shift-fetch\nDisallow: /own-group-only/\n"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/robots.txt":
            body = ROBOTS.encode()
        elif self.path == "/redirect-to-closed":
            self.send_response(302); self.send_header("Location", "/closed/x.csv"); self.end_headers(); return
        elif self.path in ("/ok/data.csv", "/closed/x.csv", "/a/blocked"):
            body = PAYLOAD
        else:
            self.send_response(404); self.end_headers(); return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_HEAD = do_GET


@contextlib.contextmanager
def server():
    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}"
    finally:
        httpd.shutdown()


class RobotsTests(unittest.TestCase):
    def test_wildcard_and_anchor_rules(self):
        rules = fd.parse_robots("User-agent: *\nDisallow: /*/download\nDisallow: /search$\nAllow: /search/ok\n")
        self.assertFalse(fd.robots_allows(rules, "/owner/repo/releases/download/v1/file.parquet"))
        self.assertFalse(fd.robots_allows(rules, "/search"))
        self.assertTrue(fd.robots_allows(rules, "/search/page"))
        self.assertTrue(fd.robots_allows(rules, "/anything/else"))

    def test_longest_match_wins_and_allow_wins_ties(self):
        rules = fd.parse_robots("User-agent: *\nDisallow: /a/\nAllow: /a/b/\nDisallow: /same\nAllow: /same\n")
        self.assertTrue(fd.robots_allows(rules, "/a/b/c"))
        self.assertFalse(fd.robots_allows(rules, "/a/x"))
        self.assertTrue(fd.robots_allows(rules, "/same"))

    def test_own_group_beats_star_group(self):
        rules = fd.parse_robots(OWN_GROUP_ROBOTS)
        self.assertFalse(fd.robots_allows(rules, "/own-group-only/x"))
        self.assertTrue(fd.robots_allows(rules, "/closed/x"))  # the '*' group is not used when our own group exists

    def test_empty_disallow_and_comments(self):
        self.assertTrue(fd.robots_allows(fd.parse_robots("User-agent: *\nDisallow:   # nothing\n"), "/x"))
        self.assertTrue(fd.robots_allows(fd.parse_robots(""), "/x"))

    def test_github_release_download_is_blocked_by_github_style_rules(self):
        rules = fd.parse_robots("User-agent: *\nDisallow: /*/download\nDisallow: /*/archive/\n")
        for f in fd.SOURCES[-1].files:
            self.assertFalse(fd.robots_allows(rules, fd.urllib.parse.urlsplit(f.url).path), f.url)


class FetcherTests(unittest.TestCase):
    def make(self, delay=0.0):
        sleeps, now = [], [0.0]
        f = fd.Fetcher(delay=delay, sleep=lambda s: (sleeps.append(s), now.__setitem__(0, now[0] + s)), clock=lambda: now[0])
        return f, sleeps

    def test_download_writes_file_note_and_hash(self):
        with server() as base, tempfile.TemporaryDirectory() as tmp:
            f, _ = self.make()
            rf = fd.RemoteFile(base + "/ok/data.csv", "data.csv", 0.0)
            path = fd.download_file(f, rf, Path(tmp) / "src", force=False, delay=0.0)
            self.assertEqual(path.read_bytes(), PAYLOAD)
            note = (Path(tmp) / "src" / "DOWNLOAD_NOTE.txt").read_text()
            self.assertIn(hashlib.sha256(PAYLOAD).hexdigest(), note)
            self.assertIn(base + "/ok/data.csv", note)
            fd.download_file(f, rf, Path(tmp) / "src", force=False, delay=0.0)   # second call skips
            self.assertEqual(note, (Path(tmp) / "src" / "DOWNLOAD_NOTE.txt").read_text())

    def test_disallowed_url_and_redirect_are_refused(self):
        with server() as base, tempfile.TemporaryDirectory() as tmp:
            f, _ = self.make()
            with self.assertRaises(fd.RobotsDenied):
                fd.download_file(f, fd.RemoteFile(base + "/closed/x.csv", "x.csv", 0), Path(tmp), False, 0.0)
            with self.assertRaises(fd.RobotsDenied):
                fd.download_file(f, fd.RemoteFile(base + "/a/blocked", "y.csv", 0), Path(tmp), False, 0.0)
            with self.assertRaises(fd.RobotsDenied):
                fd.download_file(f, fd.RemoteFile(base + "/redirect-to-closed", "z.csv", 0), Path(tmp), False, 0.0)
            self.assertEqual([p.name for p in Path(tmp).iterdir()], [])

    def test_delay_between_requests_to_one_host(self):
        with server() as base:
            f, sleeps = self.make(delay=3.0)
            for _ in range(3):
                with f.open(base + "/ok/data.csv"):
                    pass
            # robots.txt fetch + 3 requests = 4 requests, so 3 waits of the full delay (the fake clock does not advance on its own)
            self.assertEqual(sleeps, [3.0, 3.0, 3.0])

    def test_missing_robots_means_allowed_and_server_error_means_denied(self):
        f, _ = self.make()
        f._robots["http://a.test"] = []
        self.assertIsNone(f.check("http://a.test/anything"))
        f._robots["http://b.test"] = [(False, "/")]
        with self.assertRaises(fd.RobotsDenied):
            f.check("http://b.test/anything")


class PlanTests(unittest.TestCase):
    def run_main(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = fd.main(list(args))
        return code, out.getvalue()

    def test_list_is_offline_and_shows_licences(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, text = self.run_main("--list", "--data-root", tmp)
        self.assertEqual(code, 0)
        for needle in ("Apache 2.0", "CC BY-NC 4.0", "Local use only", "MANUAL", "Internet Archive", "MB"):
            self.assertIn(needle, text)
        self.assertEqual(sum(1 for s in fd.SOURCES), 5)

    def test_unknown_source_key_fails(self):
        code, _ = self.run_main("--list", "--only", "nope")
        self.assertEqual(code, 2)

    def test_gsearch_mirror_option_changes_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, text = self.run_main("--list", "--only", "gsearch_us_2022", "--gsearch-mirror", "--data-root", tmp)
        self.assertIn("Etietop", text)

    def test_download_folder_must_be_outside_git_or_ignored(self):
        import subprocess
        self.assertTrue(fd.raw_dir_is_safe(ROOT / "data" / "raw"))
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as other:
            repo = Path(tmp)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            self.assertFalse(fd.raw_dir_is_safe(repo / "downloads", repo))      # inside, not ignored
            (repo / ".gitignore").write_text("downloads/\n")
            self.assertTrue(fd.raw_dir_is_safe(repo / "downloads", repo))       # inside, ignored
            self.assertTrue(fd.raw_dir_is_safe(Path(other) / "raw", repo))      # outside

    def test_capture_list_is_clean(self):
        rows = fd.read_captures()
        self.assertGreater(len(rows), 100)
        self.assertEqual({r["site"] for r in rows}, {"topcv", "topdev", "careerbuilder", "vietnamworks"})
        for r in rows:
            self.assertRegex(r["timestamp"], r"^2022\d{10}$")
            self.assertTrue(r["original_url"].startswith("https://"))
        self.assertTrue(all(r["original_url"].split("?")[0].endswith("-jd") for r in rows if r["site"] == "vietnamworks"))


if __name__ == "__main__":
    unittest.main()
