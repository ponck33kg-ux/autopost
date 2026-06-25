import asyncio
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database import save_draft, set_moderation_message_id, get_channel
from fetcher import Article


def moderation_keyboard(draft_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"draft:approve:{draft_id}"),
        InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"draft:edit:{draft_id}"),
        InlineKeyboardButton(text="❌ Отклонить",    callback_data=f"draft:reject:{draft_id}"),
    ]])


def format_draft_message(article: Article, content: str) -> str:
    return (
        f"📋 <b>Черновик</b> → <code>{article.channel_chat_id}</code>\n"
        f"🔗 <a href='{article.url}'>{article.title}</a>\n\n"
        f"{content}\n\n"
        f"<i>Источник: {article.source}</i>"
    )


async def post_draft(bot: Bot, article: Article, content: str, moderation_group_id: int, delay: float):
    draft_id = await save_draft(
        channel_id=article.channel_id,
        title=article.title,
        content=content,
        source_url=article.url,
    )

    text = format_draft_message(article, content)

    try:
        msg = await bot.send_message(
            chat_id=moderation_group_id,
            message_thread_id=article.topic_id,
            text=text,
            parse_mode="HTML",
            reply_markup=moderation_keyboard(draft_id),
            disable_web_page_preview=True,
        )
        await set_moderation_message_id(draft_id, msg.message_id)
        print(f"[poster] ✓ Черновик #{draft_id} → топик {article.topic_id}")
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

    for article, content in processed:
        await post_draft(bot, article, content, moderation_group_id, delay)

    print(f"[poster] user {user_id}: отправлено черновиков: {len(processed)}")