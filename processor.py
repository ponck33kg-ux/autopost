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
Отвечай только на русском языке. Без предисловий и пояснений — только текст поста.""",

    "кликбейт": """Ты редактор динамичного новостного Telegram-канала.
Тебе дают заголовок и краткое содержание статьи.
Напиши цепляющий пост для Telegram: броский первый абзац, ощущение срочности, 2-3 предложения.
В конце добавь 2-3 релевантных хэштега.
Отвечай только на русском языке. Без предисловий — только текст поста.""",
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


async def process_article(article: Article) -> str:
    system_prompt = PROMPTS.get(article.prompt_style, PROMPTS["деловой"])
    user_message  = build_user_message(article)
    content = await asyncio.to_thread(call_gpt, system_prompt, user_message)
    if content:
        print(f"[processor] ✓ {article.channel_name}: {article.title[:50]}...")
    else:
        print(f"[processor] ✗ GPT вернул пустой ответ: {article.title[:50]}...")
    return content


async def process_all(articles: list) -> list:
    results = []
    for article in articles:
        content = await process_article(article)
        if content:
            results.append((article, content))
    return results
