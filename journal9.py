#!/usr/bin/env python3
"""
Scrape a set of news sources (Journal.ie 9-at-9 + Red Network sections) and mirror
them into static RSS feeds that can be self-hosted or published via GitHub Pages.

Typical usage:
    python journal9.py                       # refresh every feed
    python journal9.py --source journal9     # refresh one feed
    python journal9.py --dry-run             # print feeds without writing
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
from typing import Callable, Dict, Iterable, List, Optional, Sequence
from urllib.parse import urljoin
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).resolve().parent
USER_AGENT = (
    "rss-feed-mirror/2.0 "
    "(https://github.com/your-handle; contact: you@example.com)"
)
JOURNAL_FEED_URL = "https://www.thejournal.ie/topic/9-at-9/feed/"
REDNETWORK_BASE = "https://rednetwork.net"


@dataclass
class Entry:
    title: str
    link: str
    published: datetime
    summary: str
    content_html: str
    author: Optional[str] = None

    @property
    def guid(self) -> str:
        digest = hashlib.sha1(self.link.encode("utf-8"), usedforsecurity=False)
        return digest.hexdigest()

    def to_record(self) -> dict:
        return {
            "id": self.guid,
            "title": self.title,
            "link": self.link,
            "published": self.published.isoformat(),
            "summary": self.summary,
            "content_html": self.content_html,
            "author": self.author,
        }

    @classmethod
    def from_record(cls, record: dict) -> "Entry":
        return cls(
            title=record["title"],
            link=record["link"],
            published=datetime.fromisoformat(record["published"]),
            summary=record.get("summary", ""),
            content_html=record.get("content_html", ""),
            author=record.get("author"),
        )


@dataclass
class FeedConfig:
    slug: str
    title: str
    link: str
    description: str
    history_path: Path
    output_path: Path
    max_items: int
    fetcher: Callable[[], Entry]


def _clean_text(value: str) -> str:
    return " ".join(value.split())


def _match_tag(element: ET.Element, name: str) -> bool:
    if "}" in element.tag:
        return element.tag.split("}", 1)[1].lower() == name
    return element.tag.lower() == name


def _find_child(element: ET.Element, name: str) -> Optional[ET.Element]:
    for child in element:
        if _match_tag(child, name):
            return child
    return None


def load_history(path: Path) -> List[dict]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def save_history(path: Path, entries: Sequence[Entry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [entry.to_record() for entry in entries]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def render_rss(config: FeedConfig, entries: Sequence[Entry]) -> str:
    rss = ET.Element("rss", attrib={"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = config.title
    ET.SubElement(channel, "link").text = config.link
    ET.SubElement(channel, "description").text = config.description
    ET.SubElement(channel, "language").text = "en"

    for entry in entries:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = entry.title
        ET.SubElement(item, "link").text = entry.link
        ET.SubElement(item, "guid", attrib={"isPermaLink": "false"}).text = entry.guid
        pub_date = entry.published.astimezone(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
        ET.SubElement(item, "pubDate").text = pub_date
        if entry.author:
            ET.SubElement(item, "author").text = entry.author
        description = entry.content_html or entry.summary
        ET.SubElement(item, "description").text = description

    return ET.tostring(rss, encoding="utf-8", xml_declaration=True).decode("utf-8")


# ---------------------------------------------------------------------------
# Journal.ie helpers
# ---------------------------------------------------------------------------

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


def extract_journal_article(article_html: str) -> tuple[str, List[str]]:
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


def format_journal_description(summary: str, points: Sequence[str]) -> str:
    lines: List[str] = []
    if summary:
        lines.append(f"<p>{summary}</p>")
    if points:
        bullets = "".join(f"<li>{point}</li>" for point in points)
        lines.append(f"<ol>{bullets}</ol>")
    return "".join(lines)


def fetch_journal_entry() -> Entry:
    meta = fetch_latest_topic_entry(JOURNAL_FEED_URL)
    resp = requests.get(meta["link"], headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    summary, points = extract_journal_article(resp.text)

    return Entry(
        title=meta["title"],
        link=meta["link"],
        published=meta["published"],
        summary=summary,
        content_html=format_journal_description(summary, points),
    )


# ---------------------------------------------------------------------------
# Red Network helpers
# ---------------------------------------------------------------------------

def parse_red_date(value: str) -> datetime:
    dt = datetime.strptime(value, "%d %B %Y")
    return dt.replace(tzinfo=ZoneInfo("Europe/Dublin"))


def extract_red_article(article_html: str) -> tuple[str, List[str]]:
    soup = BeautifulSoup(article_html, "html.parser")
    summary = ""
    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc and meta_desc.get("content"):
        summary = meta_desc["content"].strip()
    if not summary:
        first_para = soup.select_one(".reader__content p")
        if first_para:
            summary = _clean_text(first_para.get_text(" ", strip=True))

    paragraphs = [
        _clean_text(p.get_text(" ", strip=True))
        for p in soup.select(".reader__content p")
        if p.get_text(strip=True)
    ]
    return summary, paragraphs[:15]


def format_red_description(summary: str, paragraphs: Sequence[str]) -> str:
    lines: List[str] = []
    if summary:
        lines.append(f"<p>{summary}</p>")
    for para in paragraphs:
        lines.append(f"<p>{para}</p>")
    return "".join(lines)


def fetch_rednetwork_entry(section_slug: str, section_name: str) -> Entry:
    listing_url = f"{REDNETWORK_BASE}/{section_slug.strip('/')}/"
    resp = requests.get(listing_url, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    card = soup.select_one(".articles__grid a.article-link")
    if card is None:
        raise RuntimeError(f"No articles found for {section_name}")

    link = urljoin(REDNETWORK_BASE, card.get("href", ""))
    title_node = card.select_one(".headline")
    author_node = card.select_one(".author")
    date_node = card.select_one(".date")

    title = _clean_text(title_node.get_text(" ", strip=True)) if title_node else card.get("href", "")
    author = _clean_text(author_node.get_text(" ", strip=True)) if author_node else None
    date_text = _clean_text(date_node.get_text(" ", strip=True)) if date_node else ""
    published = parse_red_date(date_text) if date_text else datetime.now(timezone.utc)

    article_resp = requests.get(link, headers={"User-Agent": USER_AGENT}, timeout=30)
    article_resp.raise_for_status()
    summary, paragraphs = extract_red_article(article_resp.text)

    return Entry(
        title=title,
        link=link,
        author=author,
        published=published,
        summary=summary,
        content_html=format_red_description(summary, paragraphs),
    )


# ---------------------------------------------------------------------------
# Feed runner
# ---------------------------------------------------------------------------

def build_feed_configs() -> Dict[str, FeedConfig]:
    data_dir = BASE_DIR / "data"
    return {
        "journal9": FeedConfig(
            slug="journal9",
            title="Journal.ie – Daily 9-at-9 Mirror",
            link="https://www.thejournal.ie/topic/9-at-9/",
            description="Locally mirrored feed of TheJournal.ie Daily 9-at-9 bulletins.",
            history_path=data_dir / "journal9_history.json",
            output_path=data_dir / "journal9.xml",
            max_items=30,
            fetcher=fetch_journal_entry,
        ),
        "red_articles": FeedConfig(
            slug="red_articles",
            title="Red Network – Articles",
            link=f"{REDNETWORK_BASE}/articles/",
            description="Mirror of the main Red Network articles section.",
            history_path=data_dir / "red_articles_history.json",
            output_path=data_dir / "red_articles.xml",
            max_items=30,
            fetcher=lambda: fetch_rednetwork_entry("articles", "Articles"),
        ),
        "red_theory": FeedConfig(
            slug="red_theory",
            title="Red Network – Red Theory",
            link=f"{REDNETWORK_BASE}/red-theory/",
            description="Mirror of the Red Theory long-form pieces.",
            history_path=data_dir / "red_theory_history.json",
            output_path=data_dir / "red_theory.xml",
            max_items=30,
            fetcher=lambda: fetch_rednetwork_entry("red-theory", "Red Theory"),
        ),
    }


def mirror_feed(config: FeedConfig, max_items_override: Optional[int], dry_run: bool) -> None:
    latest_entry = config.fetcher()
    history_records = load_history(config.history_path)
    entries_by_id = {record["id"]: record for record in history_records}

    if latest_entry.guid not in entries_by_id:
        print(f"[{config.slug}] Adding new entry: {latest_entry.title}")
        history_records.insert(0, latest_entry.to_record())
    else:
        print(f"[{config.slug}] Latest entry already mirrored; keeping history order.")

    limit = max_items_override or config.max_items
    trimmed = history_records[:limit]
    entries = [Entry.from_record(record) for record in trimmed]
    rss_payload = render_rss(config, entries)

    if dry_run:
        print(f"\n--- {config.slug} ---")
        print(rss_payload)
        return

    config.output_path.parent.mkdir(parents=True, exist_ok=True)
    config.output_path.write_text(rss_payload, encoding="utf-8")
    save_history(config.history_path, entries)
    print(f"[{config.slug}] Wrote RSS feed to {config.output_path}")


def parse_args(configs: Dict[str, FeedConfig]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mirror multiple sources into local RSS feeds.")
    parser.add_argument(
        "--source",
        action="append",
        choices=sorted(configs.keys()),
        help="Limit to one or more feed slugs. Defaults to all.",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        help="Override the default max history length for every feed run.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print generated RSS instead of writing files/saving history.",
    )
    parser.add_argument(
        "--list-sources",
        action="store_true",
        help="Show available feed slugs and exit.",
    )
    return parser.parse_args()


def main() -> int:
    configs = build_feed_configs()
    args = parse_args(configs)

    if args.list_sources:
        for slug, cfg in configs.items():
            print(f"{slug:12} -> {cfg.title}")
        return 0

    selected = args.source or sorted(configs.keys())
    for slug in selected:
        mirror_feed(configs[slug], args.max_items, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
