import asyncio
import feedparser
import os
import yaml
from dataclasses import dataclass
from typing import List
from database import init_db, is_url_seen, mark_url_seen


@dataclass
class Article:
    channel_name: str
    channel_chat_id: str
    moderation_topic_id: int
    prompt_style: str
    title: str
    summary: str
    url: str
    source: str


def load_config() -> dict:
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        raw = f.read()
    for key, val in os.environ.items():
        raw = raw.replace(f"${{{key}}}", val)
    return yaml.safe_load(raw)


def keyword_match(text: str, keywords: List[str]) -> bool:
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in keywords)


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


async def fetch_for_channel(channel: dict) -> List[Article]:
    name         = channel["name"]
    chat_id      = channel["chat_id"]
    topic_id     = channel["moderation_topic_id"]
    prompt_style = channel.get("prompt_style", "деловой")
    keywords     = channel.get("keywords", [])
    sources      = channel.get("sources", [])
    max_posts    = channel.get("max_posts_per_run", 5)

    candidates: List[Article] = []

    for source_url in sources:
        raw_articles = await asyncio.to_thread(parse_feed, source_url)
        for a in raw_articles:
            if not a["url"]:
                continue
            if await is_url_seen(a["url"], name):
                continue
            text = f"{a['title']} {a['summary']}"
            if keywords and not keyword_match(text, keywords):
                continue
            candidates.append(Article(
                channel_name=name,
                channel_chat_id=chat_id,
                moderation_topic_id=topic_id,
                prompt_style=prompt_style,
                title=a["title"],
                summary=a["summary"],
                url=a["url"],
                source=a["source"],
            ))

    result = candidates[:max_posts]
    for article in result:
        await mark_url_seen(article.url, name)

    print(f"[fetcher] {name}: найдено {len(result)} новых статей")
    return result


async def fetch_all(config: dict) -> List[Article]:
    tasks = [fetch_for_channel(ch) for ch in config["channels"]]
    results = await asyncio.gather(*tasks)
    articles = [a for batch in results for a in batch]
    return articles


async def main():
    await init_db()
    config = load_config()
    articles = await fetch_all(config)
    print(f"[fetcher] Итого статей для обработки: {len(articles)}")
    return articles


if __name__ == "__main__":
    asyncio.run(main())
