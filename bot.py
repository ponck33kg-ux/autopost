import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiohttp import web
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from database import (
    init_db,
    get_draft_by_id,
    update_draft_content,
    update_draft_status,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_HOST    = os.getenv("WEBHOOK_HOST")
WEBHOOK_SECRET  = os.getenv("WEBHOOK_SECRET")
PORT            = int(os.getenv("PORT", 8080))
WEBHOOK_PATH    = "/webhook"
WEBHOOK_URL     = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"
logger.info(f"WEBHOOK_HOST={WEBHOOK_HOST}, WEBHOOK_URL={WEBHOOK_URL}")

bot = Bot(token=TELEGRAM_TOKEN)
dp  = Dispatcher(storage=MemoryStorage())


class EditState(StatesGroup):
    waiting_for_text = State()


# ── /start ─────────────────────────────────────────────────────────────────────

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "👋 Привет! Я <b>Autopost Bot</b> — бот для автоматического сбора и публикации новостей в Telegram-каналы.\n\n"
        "📋 Как это работает:\n"
        "1. По расписанию собираю новости из RSS-источников\n"
        "2. Обрабатываю их через AI\n"
        "3. Отправляю черновики в группу модерации\n"
        "4. После твоего одобрения — публикую в канал\n\n"
        "Жди черновики в группе модерации 🚀",
        parse_mode="HTML",
    )


# ── Кнопки ────────────────────────────────────────────────────────────────────

def confirm_keyboard(draft_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Опубликовать",  callback_data=f"draft:approve:{draft_id}"),
        InlineKeyboardButton(text="✏️ Ещё раз",       callback_data=f"draft:edit:{draft_id}"),
        InlineKeyboardButton(text="❌ Отклонить",     callback_data=f"draft:reject:{draft_id}"),
    ]])


# ── Callback: Опубликовать ─────────────────────────────────────────────────────

@dp.callback_query(F.data.startswith("draft:approve:"))
async def handle_approve(callback: CallbackQuery):
    draft_id = int(callback.data.split(":")[2])
    draft    = await get_draft_by_id(draft_id)

    if not draft:
        await callback.answer("Черновик не найден.", show_alert=True)
        return

    if draft["status"] in ("published", "rejected"):
        await callback.answer("Этот пост уже обработан.", show_alert=True)
        return

    try:
        await bot.send_message(
            chat_id=draft["channel_chat_id"],
            text=draft["content"],
            parse_mode="HTML",
            disable_web_page_preview=False,
        )
        await update_draft_status(draft_id, "published")
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.reply(f"✅ Опубликовано в {draft['channel_chat_id']}")
        await callback.answer()
        logger.info(f"Draft #{draft_id} published to {draft['channel_chat_id']}")
    except Exception as e:
        await callback.answer(f"Ошибка публикации: {e}", show_alert=True)
        logger.error(f"Failed to publish draft #{draft_id}: {e}")


# ── Callback: Редактировать ────────────────────────────────────────────────────

@dp.callback_query(F.data.startswith("draft:edit:"))
async def handle_edit(callback: CallbackQuery, state: FSMContext):
    draft_id = int(callback.data.split(":")[2])
    draft    = await get_draft_by_id(draft_id)

    if not draft:
        await callback.answer("Черновик не найден.", show_alert=True)
        return

    await state.set_state(EditState.waiting_for_text)
    await state.update_data(draft_id=draft_id, original_message_id=callback.message.message_id)

    await callback.message.reply(
        "✏️ Пришли новый текст поста. Когда пришлёшь — покажу для подтверждения.\n\n"
        "Текущий текст:\n\n"
        f"<blockquote>{draft['content']}</blockquote>",
        parse_mode="HTML",
    )
    await callback.answer()


@dp.message(EditState.waiting_for_text)
async def handle_new_text(message: Message, state: FSMContext):
    data     = await state.get_data()
    draft_id = data["draft_id"]
    new_text = message.text

    await update_draft_content(draft_id, new_text)
    await state.clear()

    await message.reply(
        f"Новый текст сохранён:\n\n{new_text}",
        reply_markup=confirm_keyboard(draft_id),
        parse_mode="HTML",
    )


# ── Callback: Отклонить ────────────────────────────────────────────────────────

@dp.callback_query(F.data.startswith("draft:reject:"))
async def handle_reject(callback: CallbackQuery):
    draft_id = int(callback.data.split(":")[2])
    draft    = await get_draft_by_id(draft_id)

    if not draft:
        await callback.answer("Черновик не найден.", show_alert=True)
        return

    if draft["status"] in ("published", "rejected"):
        await callback.answer("Этот пост уже обработан.", show_alert=True)
        return

    await update_draft_status(draft_id, "rejected")
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.reply(f"❌ Черновик #{draft_id} отклонён")
    await callback.answer()
    logger.info(f"Draft #{draft_id} rejected")


# ── Startup / Webhook ──────────────────────────────────────────────────────────

async def on_startup(app: web.Application):
    await init_db()
    asyncio.create_task(set_webhook_delayed())


async def set_webhook_delayed():
    await asyncio.sleep(10)
    for attempt in range(5):
        try:
            await bot.set_webhook(
                url=WEBHOOK_URL,
                secret_token=WEBHOOK_SECRET,
            )
            logger.info(f"Webhook set: {WEBHOOK_URL}")
            return
        except Exception as e:
            logger.warning(f"set_webhook attempt {attempt + 1}/5 failed: {e}")
            await asyncio.sleep(5)
    logger.error("Failed to set webhook after 5 attempts")


def main_webhook():
    app = web.Application()
    app.on_startup.append(on_startup)

    SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=WEBHOOK_SECRET,
    ).register(app, path=WEBHOOK_PATH)

    setup_application(app, dp, bot=bot)
    web.run_app(app, host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main_webhook()