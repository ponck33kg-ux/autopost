import asyncio
import os
import yaml
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database import init_db, save_draft, set_moderation_message_id
from fetcher import Article, load_config, fetch_all
from processor import process_all


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
        channel_name=article.channel_name,
        channel_chat_id=article.channel_chat_id,
        title=article.title,
        content=content,
        source_url=article.url,
    )

    text = format_draft_message(article, content)

    try:
        msg = await bot.send_message(
            chat_id=moderation_group_id,
            message_thread_id=article.moderation_topic_id,
            text=text,
            parse_mode="HTML",
            reply_markup=moderation_keyboard(draft_id),
            disable_web_page_preview=True,
        )
        await set_moderation_message_id(draft_id, msg.message_id)
        print(f"[poster] ✓ Черновик #{draft_id} отправлен в топик {article.moderation_topic_id}")
    except Exception as e:
        print(f"[poster] ✗ Ошибка отправки черновика #{draft_id}: {e}")

    await asyncio.sleep(delay)


async def main():
    await init_db()
    config = load_config()

    bot_token          = os.getenv("TELEGRAM_BOT_TOKEN")
    moderation_group_id = config["telegram"]["moderation_group_id"]
    delay              = config["settings"].get("delay_between_posts", 1)

    bot = Bot(token=bot_token)

    articles = await fetch_all(config)
    if not articles:
        print("[poster] Нет новых статей для публикации")
        await bot.session.close()
        return

    processed = await process_all(articles)
    if not processed:
        print("[poster] GPT не вернул ни одного результата")
        await bot.session.close()
        return

    for article, content in processed:
        await post_draft(bot, article, content, moderation_group_id, delay)

    await bot.session.close()
    print(f"[poster] Готово. Отправлено черновиков: {len(processed)}")


if __name__ == "__main__":
    asyncio.run(main())
