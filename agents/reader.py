"""Fetches articles from RSS feeds."""
from dataclasses import dataclass
from typing import Optional
import feedparser


@dataclass
class Article:
    title: str
    url: str
    summary: str
    published_at: str
    source: str


def fetch_feed(url: str) -> list[Article]:
    feed = feedparser.parse(url)
    source = feed.feed.get("title", url)
    articles = []
    for entry in feed.entries:
        articles.append(Article(
            title=entry.get("title", ""),
            url=entry.get("link", ""),
            summary=_clean(entry.get("summary", entry.get("description", ""))),
            published_at=entry.get("published", entry.get("updated", "")),
            source=source,
        ))
    return articles


def fetch_all(feed_urls: list[str]) -> list[Article]:
    all_articles = []
    for url in feed_urls:
        try:
            all_articles.extend(fetch_feed(url))
        except Exception as e:
            print(f"[reader] failed to fetch {url}: {e}")
    return all_articles


def _clean(text: str) -> str:
    import re
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.split())
