# Journal.ie 9-at-9 Mirror

Small helper script that grabs TheJournal.ie's daily **9-at-9** bulletin and regenerates it into a custom RSS feed you can self-host or plug into a reader that expects a regular RSS endpoint.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
python journal9.py --output data/journal9.xml
```

Flags:

- `--feed-url` (default `https://www.thejournal.ie/topic/9-at-9/feed/`) to point at a different topic feed.
- `--history` path for the JSON cache that prevents duplicate entries.
- `--output` path for the generated RSS feed file.
- `--max-items` number of mirrored items to keep (default 30).
- `--dry-run` prints the RSS payload to stdout for quick inspection.

The script keeps a small JSON history so reruns do not create duplicates and older entries remain available.

## GitHub Pages + Actions Hosting

1. **Fork/copy this repo** and enable GitHub Pages in *Settings → Pages*, selecting the `main` branch and `/data` folder. The generated feed will then be served from `https://<user>.github.io/<repo>/journal9.xml`.
2. **Review `.github/workflows/journal9.yml`:**
   - Runs daily at 09:15 UTC (`cron: 15 9 * * *`). Adjust to your timezone.
   - Installs dependencies, runs the scraper, and commits updated `data/journal9.xml` + `data/journal9_history.json`.
   - Uses the default `GITHUB_TOKEN` with `contents: write` permission, so no personal token is required.
3. **Optional secrets:** if you need to call authenticated APIs later, add them under *Settings → Secrets and variables → Actions* and reference them in the workflow.
4. **Kick off a manual run** via the *Actions* tab (`workflow_dispatch`) to generate the first live feed before sharing the Pages URL.

## Scheduling

Add a cron entry (for example, run every day at 8:00 a.m.):

```
0 8 * * * /usr/bin/env bash -lc 'cd /home/you/path/to/RSS-feed && source .venv/bin/activate && python journal9.py --output /var/www/html/journal9.xml'
```

Point the `--output` flag wherever your RSS host or static site expects the file to live.

## Notes

- The scraper prefers the official topic RSS feed and then fetches the linked article, so it is resilient to most site layout tweaks.
- The generated RSS description bundles the article summary and an ordered list of the nine talking points so readers can preview everything without leaving their reader.*** End Patch
