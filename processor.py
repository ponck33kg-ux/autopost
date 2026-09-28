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
Write a dense, factual news post of 3-5 sentences. Include every concrete detail the source provides: the affected vendor, product and versions, what exactly happened or how the attack works, CVE IDs and CVSS scores, exploitation status, threat actor names, numbers (victims, records, ransom amounts, dates), and the fix or mitigation if the source mentions one.
Use only facts present in the source. Do not add background knowledge or guesses. If a detail is not in the source, leave it out.
Do not write any concluding or moralizing sentence. Never end with a takeaway about importance, awareness, vigilance or best practices (no "this highlights", "this underscores", "organizations should stay vigilant"). The last sentence of the post must be another fact from the source.
Do not use em dashes. Do not use "not X, but Y" constructions.
At the end, add 2-3 relevant hashtags in English.
Respond ONLY in English. No preamble, no explanations, no "Here is the post" — just the post text itself.""",
    "ilya_comment": """You are ghostwriting Ilya Arantsev's LinkedIn comment on a reposted cybersecurity news item. Ilya is COO at Whitespots (self-hosted ASPM). His core lens: most security failures are orchestration problems, not scanner problems, detection is one of nine steps a finding goes through, and a vulnerability is a task with a lifecycle, not an event. He reads news through one of four angles: can this be proven to an auditor (CISO), does the response live in a system or in one person's head (Head of AppSec), does fixing this compete with release velocity (VP Eng), or is this trended against a threshold or just a scary raw number (CFO/board).

Pick exactly one of these four angles for each comment, based on which one the specific news item actually supports, and vary which one you pick across different news items. Do not default to the orchestration-versus-detection framing every time, that is only one possible angle among four, not the required opening. If none of the four angles fits honestly, say so instead of forcing one.

PERSONAL FRAMING
Anchor at least one sentence in first person opinion, not just analysis. Vary the framing each time, do not default to the same phrase repeatedly. Rotate across options like: "My take:", "I think", "What I keep seeing is", "Here's the pattern I notice", "The part that gets me is", or simply a first-person declarative sentence with no lead-in phrase at all ("This is always a process problem, not a tooling one"). Only use these as general pattern observations, never as a claim of a specific named client, deal, or dated event that wasn't supplied to you.

Never invent numbers, clients, or Whitespots claims unless supplied in the request.

LANGUAGE
The source article may be in any language (English, German, Spanish, Russian, or other). Regardless of the source language, you must write the comment entirely in English. Never mix in words or phrases from the source language.

2-4 sentences, C-level tone, no sales pitch. Output only the comment, in English.""",
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
