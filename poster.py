import asyncio
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database import save_draft, set_moderation_message_id, get_channel
from fetcher import Article
from processor import process_article

def moderation_keyboard(draft_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"draft:approve:{draft_id}"),
            InlineKeyboardButton(text="❌ Отклонить",    callback_data=f"draft:reject:{draft_id}"),
        ],
        [
            InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"draft:edit:{draft_id}"),
            InlineKeyboardButton(text="🖼 Иллюстрация",   callback_data=f"draft:photo:{draft_id}"),
        ],
    ])


def comment_keyboard(draft_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"draft:edit:{draft_id}"),
            InlineKeyboardButton(text="❌ Отклонить",     callback_data=f"draft:reject:{draft_id}"),
        ],
    ])


def format_draft_message(article: Article, content: str, draft_type: str = "primary") -> str:
    if draft_type == "ilya":
        return (
            f"💬 <b>Комментарий Ильи</b> (к посту выше)\n"
            f"🔗 <a href='{article.url}'>{article.title}</a>\n\n"
            f"{content}"
        )
    source_label = "Source" if article.prompt_style == "english" else "Источник"
    return (
        f"📋 <b>Черновик</b> → <code>{article.channel_chat_id}</code>\n"
        f"🔗 <a href='{article.url}'>{article.title}</a>\n\n"
        f"{content}\n\n"
        f"<i>{source_label}: {article.source}</i>"
    )


async def post_draft(bot: Bot, article: Article, content: str, moderation_group_id: int, delay: float, draft_type: str = "primary"):
    draft_id = await save_draft(
        channel_id=article.channel_id,
        title=article.title,
        content=content,
        source_url=article.url,
        draft_type=draft_type,
    )

    text     = format_draft_message(article, content, draft_type)
    keyboard = comment_keyboard(draft_id) if draft_type == "ilya" else moderation_keyboard(draft_id)

    try:
        msg = await bot.send_message(
            chat_id=moderation_group_id,
            message_thread_id=article.topic_id,
            text=text,
            parse_mode="HTML",
            reply_markup=keyboard,
            disable_web_page_preview=True,
        )
        await set_moderation_message_id(draft_id, msg.message_id)
        print(f"[poster] ✓ Черновик #{draft_id} [{draft_type}] → топик {article.topic_id}")
    except Exception as e:
        print(f"[poster] ✗ Ошибка черновика #{draft_id}: {e}")

    await asyncio.sleep(delay)


async def run_cycle(bot: Bot, moderation_group_id: int, user_id: int, delay: float = 1):
    from fetcher import fetch_all_for_user
    from processor import process_all

    articles = await fetch_all_for_user(user_id)
    if not articles:
        print(f"[poster] user {user_id}: нет новых статей")
        return

    processed = await process_all(articles)
    if not processed:
        print(f"[poster] user {user_id}: AI не вернул результатов")
        return

    # индекс статьи -> voice style канала, чтобы не запрашивать канал на каждую статью повторно
    voice_cache = {}

    total_sent = 0
    for article, content in processed:
        await post_draft(bot, article, content, moderation_group_id, delay, draft_type="primary")
        total_sent += 1

        if article.channel_id not in voice_cache:
            channel = await get_channel(article.channel_id)
            voice_cache[article.channel_id] = channel.get("secondary_prompt_style") if channel else None
        voice_style = voice_cache[article.channel_id]

        if voice_style:
            voice_content = await process_article(article, style_override=voice_style)
            if voice_content:
                await post_draft(bot, article, voice_content, moderation_group_id, delay, draft_type="ilya")
                total_sent += 1

    print(f"[poster] user {user_id}: отправлено черновиков: {total_sent}")