#!/usr/bin/env python3
"""
Utility script for scraping TheJournal.ie daily 9-at-9 article and mirroring it
into a lightweight RSS feed that you can self-host.

Typical usage:
    python journal9.py --output data/journal9.xml
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Iterable, List, Optional
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_FEED_URL = "https://www.thejournal.ie/topic/9-at-9/feed/"
DEFAULT_HISTORY_PATH = BASE_DIR / "data" / "journal9_history.json"
DEFAULT_OUTPUT_PATH = BASE_DIR / "data" / "journal9.xml"
USER_AGENT = (
    "journal9-fetcher/1.0 "
    "(https://github.com/your-handle; contact: you@example.com)"
)


@dataclass
class Entry:
    title: str
    link: str
    published: datetime
    summary: str
    points: List[str]

    @property
    def guid(self) -> str:
        digest = hashlib.sha1(self.link.encode("utf-8"), usedforsecurity=False)
        return digest.hexdigest()


def _match_tag(element: ET.Element, name: str) -> bool:
    if "}" in element.tag:
        return element.tag.split("}", 1)[1].lower() == name
    return element.tag.lower() == name


def _find_child(element: ET.Element, name: str) -> Optional[ET.Element]:
    for child in element:
        if _match_tag(child, name):
            return child
    return None


def fetch_latest_topic_entry(feed_url: str) -> dict:
    resp = requests.get(feed_url, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()

    root = ET.fromstring(resp.content)
    channel = _find_child(root, "channel")
    if channel is None:
        raise RuntimeError("Unexpected RSS feed shape (no channel)")
    item = _find_child(channel, "item")
    if item is None:
        raise RuntimeError("No items found in feed")

    def text(name: str) -> str:
        child = _find_child(item, name)
        return (child.text or "").strip() if child is not None else ""

    title = text("title")
    link = text("link")
    pub_date_raw = text("pubDate")
    published = parsedate_to_datetime(pub_date_raw) if pub_date_raw else datetime.now(timezone.utc)

    return {"title": title, "link": link, "published": published}


def _clean_text(value: str) -> str:
    return " ".join(value.split())


def extract_article_points(article_html: str) -> tuple[str, List[str]]:
    soup = BeautifulSoup(article_html, "html.parser")

    summary = ""
    summary_node = soup.find("meta", attrs={"property": "og:description"})
    if summary_node and summary_node.get("content"):
        summary = summary_node["content"].strip()
    if not summary:
        first_para = soup.select_one("article p")
        if first_para:
            summary = _clean_text(first_para.get_text(" ", strip=True))

    selectors = [
        "article ol",
        "article ul",
        ".article_body ol",
        ".article_body ul",
        ".article-content ol",
        ".article-content ul",
    ]
    bullet_points: List[str] = []
    for selector in selectors:
        container = soup.select_one(selector)
        if container:
            items = [_clean_text(li.get_text(" ", strip=True)) for li in container.find_all("li")]
            bullet_points = [text for text in items if text]
            if len(bullet_points) >= 5:
                break

    if not bullet_points:
        paragraphs = [
            _clean_text(p.get_text(" ", strip=True))
            for p in soup.select("article p")
            if p.get_text(strip=True)
        ]
        bullet_points = paragraphs[:9]

    return summary, bullet_points[:9]


def fetch_entry(feed_url: str) -> Entry:
    meta = fetch_latest_topic_entry(feed_url)
    resp = requests.get(meta["link"], headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    summary, points = extract_article_points(resp.text)

    return Entry(
        title=meta["title"],
        link=meta["link"],
        published=meta["published"],
        summary=summary,
        points=points,
    )


def load_history(path: Path) -> List[dict]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def save_history(path: Path, entries: Iterable[Entry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "id": entry.guid,
            "title": entry.title,
            "link": entry.link,
            "published": entry.published.isoformat(),
            "summary": entry.summary,
            "points": entry.points,
        }
        for entry in entries
    ]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def render_description(entry: Entry) -> str:
    lines = []
    if entry.summary:
        lines.append(f"<p>{entry.summary}</p>")
    if entry.points:
        bullets = "".join(f"<li>{point}</li>" for point in entry.points)
        lines.append(f"<ol>{bullets}</ol>")
    return "".join(lines)


def render_rss(entries: Iterable[Entry]) -> str:
    rss = ET.Element("rss", attrib={"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "Journal.ie – Daily 9-at-9 Mirror"
    ET.SubElement(channel, "link").text = "https://www.thejournal.ie/topic/9-at-9/"
    ET.SubElement(channel, "description").text = (
        "Locally mirrored feed of TheJournal.ie Daily 9-at-9 bulletins."
    )
    ET.SubElement(channel, "language").text = "en"

    for entry in entries:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = entry.title
        ET.SubElement(item, "link").text = entry.link
        ET.SubElement(item, "guid", attrib={"isPermaLink": "false"}).text = entry.guid
        pub_date = entry.published.astimezone(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
        ET.SubElement(item, "pubDate").text = pub_date
        ET.SubElement(item, "description").text = render_description(entry)

    return ET.tostring(rss, encoding="utf-8", xml_declaration=True).decode("utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mirror TheJournal.ie 9-at-9 into a custom RSS feed.")
    parser.add_argument("--feed-url", default=DEFAULT_FEED_URL, help="Topic feed to follow.")
    parser.add_argument(
        "--history",
        default=str(DEFAULT_HISTORY_PATH),
        help="JSON file used to deduplicate already mirrored entries.",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_PATH),
        help="Path to write the generated RSS feed.",
    )
    parser.add_argument("--max-items", type=int, default=30, help="Maximum entries to keep.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the generated RSS instead of writing to disk.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    history_path = Path(args.history)
    output_path = Path(args.output)

    latest_entry = fetch_entry(args.feed_url)

    history_records = load_history(history_path)
    entries_by_id = {record["id"]: record for record in history_records}

    if latest_entry.guid not in entries_by_id:
        print(f"Adding new entry for {latest_entry.title}")
        history_records.insert(
            0,
            {
                "id": latest_entry.guid,
                "title": latest_entry.title,
                "link": latest_entry.link,
                "published": latest_entry.published.isoformat(),
                "summary": latest_entry.summary,
                "points": latest_entry.points,
            },
        )
    else:
        print("Latest entry already mirrored; refreshing timestamps.")

    trimmed = history_records[: args.max_items]
    entries = [
        Entry(
            title=record["title"],
            link=record["link"],
            published=datetime.fromisoformat(record["published"]),
            summary=record.get("summary", ""),
            points=record.get("points", []),
        )
        for record in trimmed
    ]

    rss_payload = render_rss(entries)

    if args.dry_run:
        print(rss_payload)
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rss_payload, encoding="utf-8")
        save_history(history_path, entries)
        print(f"Wrote RSS feed to {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
