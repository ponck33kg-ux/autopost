import asyncio
import feedparser
from dataclasses import dataclass
from typing import List
from database import (
    get_user_channels, get_channel_sources,
    is_url_seen, mark_url_seen,
)


@dataclass
class Article:
    channel_id:   int
    channel_chat_id: str
    topic_id:     int
    prompt_style: str
    max_posts:    int
    title:        str
    summary:      str
    url:          str
    source:       str


def parse_feed(url: str) -> List[dict]:
    try:
        feed = feedparser.parse(url)
        articles = []
        for entry in feed.entries:
            articles.append({
                "title":   getattr(entry, "title",   ""),
                "summary": getattr(entry, "summary", ""),
                "url":     getattr(entry, "link",    ""),
                "source":  getattr(feed.feed, "title", url),
            })
        return articles
    except Exception as e:
        print(f"[fetcher] Ошибка парсинга {url}: {e}")
        return []


def keyword_match(text: str, keywords: List[str]) -> bool:
    if not keywords:
        return True
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in keywords)


async def fetch_for_channel(channel: dict) -> List[Article]:
    channel_id   = channel["id"]
    chat_id      = channel["chat_id"]
    topic_id     = channel["topic_id"]
    prompt_style = channel.get("prompt_style", "деловой")
    max_posts    = channel.get("max_posts", 5)

    sources = await get_channel_sources(channel_id)
    if not sources:
        print(f"[fetcher] Канал {chat_id}: нет источников")
        return []

    per_source_limit = max(1, max_posts // len(sources))
    candidates: List[Article] = []
    for source in sources:
        url          = source["url"]
        raw_articles = await asyncio.to_thread(parse_feed, url)
        source_count = 0
        for a in raw_articles:
            if source_count >= per_source_limit:
                break
            if not a["url"]:
                continue
            if await is_url_seen(a["url"], channel_id):
                continue
            candidates.append(Article(
                channel_id=channel_id,
                channel_chat_id=chat_id,
                topic_id=topic_id,
                prompt_style=prompt_style,
                max_posts=max_posts,
                title=a["title"],
                summary=a["summary"],
                url=a["url"],
                source=a["source"],
            ))
            source_count += 1
    result = candidates[:max_posts]
    for article in result:
        await mark_url_seen(article.url, channel_id)

    print(f"[fetcher] {chat_id}: найдено {len(result)} новых статей")
    return result


async def fetch_all_for_user(user_id: int) -> List[Article]:
    channels = await get_user_channels(user_id)
    if not channels:
        return []
    tasks   = [fetch_for_channel(ch) for ch in channels]
    results = await asyncio.gather(*tasks)
    return [a for batch in results for a in batch]