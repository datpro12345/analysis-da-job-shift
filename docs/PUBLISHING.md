# Publish the report with GitHub Pages

The report is one static file: `report/index.html`. No server, no build step on the
web side, no external script or font. Nothing is published until you do it yourself.

## Look at it locally first

Open `report/index.html` in a browser (double-click it). Or run
`python -m http.server 8000 --directory report` and open http://localhost:8000.

## Publish with the ready-made workflow

1. Push the repository to GitHub (your account, your repository name).
2. In the repository: **Settings > Pages > Build and deployment > Source: GitHub Actions**.
3. Open the **Actions** tab, choose **publish-report**, press **Run workflow**.
4. After about a minute the page is live at `https://<your-user>.github.io/<repository>/`.

The workflow (`.github/workflows/pages.yml`) runs only when you start it. It builds the
page from `results/` with `--repo-url`, so the links on the page point to your
repository, and it uploads that one file.

## After you change the results

```bash
.venv/bin/python scripts/build_report.py     # rewrites report/index.html
.venv/bin/python -m unittest tests.test_report
```

`tests/test_report.py` fails when the page is out of date, or when any number embedded in
the page differs from the CSV files in `results/`.

## Check before you publish

* `python tools/public_safety_check.py` passes (no e-mail, phone, private path, posting text).
* The page shows the repository name you want. Rebuild with `--repo-url` if you rename it.
* Repository name: `da-job-shift`. Choose the description and topics. Suggested topics: `data-analysis`, `text-analysis`, `nlp`, `job-postings`, `labor-market`, `vietnam`.
* Licences: code MIT, documentation and page text CC BY 4.0, results and the data in the page CC BY-NC 4.0 (non-commercial use only). Keep the Tinix citation on the page.
