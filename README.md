# Feed Mirrors (Journal.ie + Red Network)

Helper script + GitHub workflow that scrapes a few Irish left media sources and mirrors them into static RSS feeds you can host yourself (or via GitHub Pages). Each feed keeps a JSON cache so we can retain older entries and avoid duplicates.

| Slug           | Source URL                            | Output file             |
| -------------- | ------------------------------------- | ----------------------- |
| `journal9`     | https://www.thejournal.ie/topic/9-at-9/ | `data/journal9.xml`     |
| `red_articles` | https://rednetwork.net/articles/      | `data/red_articles.xml` |
| `red_theory`   | https://rednetwork.net/red-theory/    | `data/red_theory.xml`   |

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
python3 journal9.py                    # refresh every feed
python3 journal9.py --source red_theory
python3 journal9.py --dry-run --source journal9
python3 journal9.py --list-sources
```

Key flags:

- `--source <slug>` (repeatable) limits the run to specific feeds; defaults to all.
- `--max-items <n>` overrides the per-feed history length for this run.
- `--dry-run` prints the generated XML instead of writing files/saving history.
- `--list-sources` shows the available slugs and exits.

All output XML + history JSON lives under `data/`.

## GitHub Pages + Actions Hosting

1. Push the repo and enable GitHub Pages in *Settings → Pages*, choosing the `main` branch and `/data` folder. Every XML under `data/` will be reachable at `https://<user>.github.io/<repo>/data/<file>.xml`.
2. `.github/workflows/journal9.yml` (legacy name) runs daily at 09:15 UTC and on manual dispatch. It installs deps, executes `python3 journal9.py`, and commits any changed XML/history files back with the default `GITHUB_TOKEN`.
3. Kick off the workflow manually once so the feeds exist before sharing URLs with your reader (Inoreader, NetNewsWire, etc.).
4. Share the Pages URLs (`.../journal9.xml`, `.../red_articles.xml`, `.../red_theory.xml`). Every workflow run keeps them fresh automatically.

## Self-Hosted Scheduling

Prefer running it yourself? Drop a cron entry (example: every day at 09:05 local time):

```
5 9 * * * /usr/bin/env bash -lc 'cd /home/you/RSS-feed && source .venv/bin/activate && python3 journal9.py'
```

Point `data/` (or symlinked files) at whatever directory your web server exposes.

## Notes

- Journal.ie content is seeded from their official topic RSS feed and then we scrape the linked article to mirror the nine talking points.
- Red Network sections lack RSS, so we scrape their grid pages, follow the latest post, and mirror the intro paragraphs from `.reader__content`.
- The `<description>` HTML is entity-escaped to keep the XML simple; mainstream feed readers render it correctly.*** End Patch
