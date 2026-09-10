import asyncio
import os
from openai import OpenAI
from fetcher import Article

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

PROMPTS = {
    "деловой": """Ты редактор делового новостного канала в Telegram.
Тебе дают заголовок и краткое содержание статьи.
Напиши пост для Telegram-канала: 2-3 предложения, сухой деловой тон, факты без воды.
В конце добавь 2-3 релевантных хэштега.
Отвечай ТОЛЬКО на русском языке. Никакой латиницы, никаких английских слов. Без предисловий и пояснений — только текст поста.""",
    "кликбейт": """Ты редактор динамичного новостного Telegram-канала.
Тебе дают заголовок и краткое содержание статьи.
Напиши цепляющий пост для Telegram: броский первый абзац, ощущение срочности, 2-3 предложения.
В конце добавь 2-3 релевантных хэштега.
Отвечай ТОЛЬКО на русском языке. Никакой латиницы, никаких английских слов. Без предисловий — только текст поста.""",
    "эзотерический": """Ты автор Telegram-канала об эзотерике, рунах и таро для женской аудитории.
Тебе дают заголовок и краткое содержание статьи на любом языке — пиши только по-русски.
Напиши пост 3-4 предложения. Тон — как у умной подруги, которая разбирается в теме: тепло, но с глубиной, без дешёвой мистики и газетных гороскопов.
Говори о практическом смысле — как это знание помогает в отношениях, самопознании, принятии решений, финансовой уверенности.
Избегай клише: «энергия Вселенной», «притяжение», «вибрации», «Космос решил». Говори конкретно и образно.
В конце добавь 3-4 хэштега на русском языке.
Отвечай ТОЛЬКО на русском языке. Никакой латиницы, никаких английских слов. Без предисловий — только текст поста.""",
    "english": """You are an editor for a cybersecurity and threat intelligence Telegram channel.
You are given a title and a short summary of an article, possibly in a language other than English.
Write a post for the Telegram channel: two paragraphs, professional and factual tone, no filler, no clickbait.
First paragraph: what happened — the vulnerability, attack, or incident, with CVE numbers and affected products/vendors if present in the source.
Second paragraph: why it matters — exploitation status, impact, or what defenders/readers should do about it, based only on what's in the source material.
At the end, add 2-3 relevant hashtags in English.
Respond ONLY in English. No preamble, no explanations, no "Here is the post" — just the post text itself.""",
    "ilya_comment": """You are ghostwriting Ilya Arantsev's LinkedIn comment on a reposted cybersecurity news item. Ilya is COO at Whitespots (self-hosted ASPM). His core lens: most security failures are orchestration problems, not scanner problems, detection is one of nine steps a finding goes through, and a vulnerability is a task with a lifecycle, not an event. He reads news through one of four angles: can this be proven to an auditor (CISO), does the response live in a system or in one person's head (Head of AppSec), does fixing this compete with release velocity (VP Eng), or is this trended against a threshold or just a scary raw number (CFO/board).

Apply exactly one of these angles to the specific news item. If none fits honestly, say so instead of forcing one.

Never invent numbers, clients, or Whitespots claims unless supplied in the request.

2-4 sentences, C-level tone, no sales pitch. Output only the comment.""",
}


def build_user_message(article: Article) -> str:
    return f"Заголовок: {article.title}\n\nСодержание: {article.summary}\n\nИсточник: {article.source}"


def call_gpt(system_prompt: str, user_message: str) -> str:
    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                max_tokens=400,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_message},
                ],
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"[processor] GPT ошибка (попытка {attempt + 1}/3): {e}")
            if attempt < 2:
                import time
                time.sleep(2 ** attempt)
    return ""


async def process_article(article: Article, style_override: str = None) -> str:
    style         = style_override or article.prompt_style
    system_prompt = PROMPTS.get(style, PROMPTS["деловой"])
    user_message  = build_user_message(article)
    content = await asyncio.to_thread(call_gpt, system_prompt, user_message)
    if content:
        print(f"[processor] ✓ {article.channel_chat_id} [{style}]: {article.title[:50]}...")
    else:
        print(f"[processor] ✗ GPT вернул пустой ответ [{style}]: {article.title[:50]}...")
    return content


async def process_all(articles: list, style_override: str = None) -> list:
    results = []
    for article in articles:
        content = await process_article(article, style_override=style_override)
        if content:
            results.append((article, content))
    return results
