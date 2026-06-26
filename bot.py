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
    get_or_create_user,
    get_user_channels,
    count_user_channels,
    add_channel,
    delete_channel,
    get_channel,
    get_channel_sources,
    add_source,
    delete_source,
    get_draft_by_id,
    update_draft_content,
    update_draft_status,
    MAX_CHANNELS_PER_USER,
)

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN      = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_HOST        = os.getenv("WEBHOOK_HOST")
WEBHOOK_SECRET      = os.getenv("WEBHOOK_SECRET")
MODERATION_GROUP_ID = int(os.getenv("MODERATION_GROUP_ID", 0))
PORT                = int(os.getenv("PORT", 8080))
WEBHOOK_PATH        = "/webhook"
WEBHOOK_URL         = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

bot = Bot(token=TELEGRAM_TOKEN)
dp  = Dispatcher(storage=MemoryStorage())


# ── FSM ────────────────────────────────────────────────────────────────────────

class AddChannelState(StatesGroup):
    waiting_chat_id      = State()
    waiting_topic_id     = State()
    waiting_prompt_style = State()
    waiting_interval     = State()
    waiting_night_mode   = State()
    waiting_timezone     = State()

class AddSourceState(StatesGroup):
    waiting_channel = State()
    waiting_url     = State()

class DeleteSourceState(StatesGroup):
    waiting_channel = State()
    waiting_source  = State()

class EditState(StatesGroup):
    waiting_for_text = State()


# ── Клавиатуры ────────────────────────────────────────────────────────────────

def channels_keyboard(channels: list) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(
            text=f"📢 {ch['name']} ({ch['chat_id']})",
            callback_data=f"channel:{ch['id']}"
        )]
        for ch in channels
    ]
    buttons.append([InlineKeyboardButton(text="➕ Добавить канал", callback_data="addchannel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def channel_keyboard(channel_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Источники",      callback_data=f"sources:{channel_id}")],
        [InlineKeyboardButton(text="➕ Добавить источник", callback_data=f"addsource:{channel_id}")],
        [InlineKeyboardButton(text="🗑 Удалить канал",  callback_data=f"deletechannel:{channel_id}")],
        [InlineKeyboardButton(text="◀️ Назад",          callback_data="back_channels")],
    ])


def sources_keyboard(sources: list, channel_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(
            text=f"🗑 {s['url'][:40]}...",
            callback_data=f"deletesource:{s['id']}:{channel_id}"
        )]
        for s in sources
    ]
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data=f"channel:{channel_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def prompt_style_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📰 Деловой",  callback_data="style:деловой")],
        [InlineKeyboardButton(text="🔥 Кликбейт", callback_data="style:кликбейт")],
    ])
    
def interval_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡ Каждые 3 часа",  callback_data="interval:3")],
        [InlineKeyboardButton(text="🕐 Каждые 6 часов", callback_data="interval:6")],
        [InlineKeyboardButton(text="🕛 Каждые 12 часов", callback_data="interval:12")],
        [InlineKeyboardButton(text="📅 Раз в сутки",    callback_data="interval:24")],
    ])


def night_mode_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌙 Включить (нет постов с 23:00 до 8:00)", callback_data="night:on")],
        [InlineKeyboardButton(text="☀️ Выключить", callback_data="night:off")],
    ])


def timezone_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇷🇺 Москва (UTC+3)",       callback_data="tz:Europe/Moscow")],
        [InlineKeyboardButton(text="🇷🇺 Екатеринбург (UTC+5)", callback_data="tz:Asia/Yekaterinburg")],
        [InlineKeyboardButton(text="🇷🇺 Новосибирск (UTC+7)",  callback_data="tz:Asia/Novosibirsk")],
        [InlineKeyboardButton(text="🇷🇺 Владивосток (UTC+10)", callback_data="tz:Asia/Vladivostok")],
        [InlineKeyboardButton(text="🇺🇦 Киев (UTC+2)",         callback_data="tz:Europe/Kiev")],
        [InlineKeyboardButton(text="🇰🇿 Алматы (UTC+6)",       callback_data="tz:Asia/Almaty")],
        [InlineKeyboardButton(text="🌍 Другой — введу сам",    callback_data="tz:manual")],
    ])


def confirm_keyboard(draft_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Опубликовать",  callback_data=f"draft:approve:{draft_id}"),
        InlineKeyboardButton(text="✏️ Ещё раз",       callback_data=f"draft:edit:{draft_id}"),
        InlineKeyboardButton(text="❌ Отклонить",     callback_data=f"draft:reject:{draft_id}"),
    ]])


# ── /start ─────────────────────────────────────────────────────────────────────

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await get_or_create_user(message.from_user.id)
    await message.answer(
        "👋 Привет! Я <b>Autopost Bot</b> — собираю новости из RSS и публикую в ваши каналы после одобрения.\n\n"
        "📋 Как начать:\n"
        "1. Нажмите /channels и добавьте канал\n"
        "2. В процессе добавления вы настроите группу модерации, источники и расписание\n"
        "3. Готово — черновики будут приходить вам на одобрение\n\n"
        "/channels — управление каналами",
        parse_mode="HTML",
    )


# ── /channels ──────────────────────────────────────────────────────────────────

@dp.message(Command("channels"))
async def cmd_channels(message: Message):
    await get_or_create_user(message.from_user.id)
    channels = await get_user_channels(message.from_user.id)
    if not channels:
        await message.answer(
            "У тебя пока нет каналов.\n\nДобавь первый:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="➕ Добавить канал", callback_data="addchannel")
            ]])
        )
        return
    await message.answer(
        f"Твои каналы ({len(channels)}/{MAX_CHANNELS_PER_USER}):",
        reply_markup=channels_keyboard(channels)
    )


@dp.callback_query(F.data == "back_channels")
async def back_channels(callback: CallbackQuery):
    channels = await get_user_channels(callback.from_user.id)
    await callback.message.edit_text(
        f"Твои каналы ({len(channels)}/{MAX_CHANNELS_PER_USER}):",
        reply_markup=channels_keyboard(channels)
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("channel:"))
async def show_channel(callback: CallbackQuery):
    channel_id = int(callback.data.split(":")[1])
    channel    = await get_channel(channel_id)
    if not channel:
        await callback.answer("Канал не найден.", show_alert=True)
        return
    sources = await get_channel_sources(channel_id)
    await callback.message.edit_text(
        f"📢 <b>{channel['name']}</b>\n"
        f"ID: <code>{channel['chat_id']}</code>\n"
        f"Топик: <code>{channel['topic_id']}</code>\n"
        f"Стиль: {channel['prompt_style']}\n"
        f"Источников: {len(sources)}",
        parse_mode="HTML",
        reply_markup=channel_keyboard(channel_id)
    )
    await callback.answer()


# ── Добавить канал ─────────────────────────────────────────────────────────────

@dp.callback_query(F.data == "addchannel")
async def cb_add_channel(callback: CallbackQuery, state: FSMContext):
    count = await count_user_channels(callback.from_user.id)
    if count >= MAX_CHANNELS_PER_USER:
        await callback.answer(f"Максимум {MAX_CHANNELS_PER_USER} каналов.", show_alert=True)
        return
    await state.set_state(AddChannelState.waiting_chat_id)
    await callback.message.answer("Пришли username канала (например @mychannel):")
    await callback.answer()


@dp.message(Command("addchannel"))
async def cmd_add_channel(message: Message, state: FSMContext):
    count = await count_user_channels(message.from_user.id)
    if count >= MAX_CHANNELS_PER_USER:
        await message.answer(f"Максимум {MAX_CHANNELS_PER_USER} каналов.")
        return
    await state.set_state(AddChannelState.waiting_chat_id)
    await message.answer("Пришли username канала (например @mychannel):")


@dp.message(AddChannelState.waiting_chat_id)
async def got_chat_id(message: Message, state: FSMContext):
    chat_id = message.text.strip()
    if not chat_id.startswith("@"):
        await message.answer("Username должен начинаться с @. Попробуй снова:")
        return
    name = chat_id.lstrip("@")
    await state.update_data(chat_id=chat_id, name=name)
    await state.set_state(AddChannelState.waiting_topic_id)
    await message.answer(
         "Все новости будут приходить в специальную группу — там вы сможете просматривать, "
    "редактировать и публиковать их одной кнопкой.\n\n"
    "Если группы ещё нет — создайте её:\n"
    "1. Создайте новую группу в Telegram\n"
    "2. Зайдите в настройки группы → включите <b>Темы</b>\n"
    "3. Добавьте меня (@autopost32_bot) как администратора\n"
    f"4. Создайте тему (топик) которая будет связана с каналом <code>{chat_id}</code>\n\n"
    "Когда группа готова:\n"
    "Зайдите в нужный топик → напишите любое сообщение → нажмите на него → "
    "<b>Копировать ссылку</b> → пришлите её мне.",
    parse_mode="HTML",
)


dp.message(AddChannelState.waiting_topic_id)
async def got_topic_id(message: Message, state: FSMContext):
    text = message.text.strip()
    topic_id = None

    if text.startswith("https://t.me/"):
        parts = text.rstrip("/").split("/")
        try:
            # ссылка вида https://t.me/c/GROUPID/TOPICID/MESSAGEID
            # topic_id — третий элемент после t.me/c/
            if "c" in parts:
                c_index = parts.index("c")
                topic_id = int(parts[c_index + 2])
            else:
                topic_id = int(parts[-1])
        except (ValueError, IndexError):
            pass
    else:
        try:
            topic_id = int(text)
        except ValueError:
            pass

    if not topic_id:
        await message.answer(
            "Не удалось распознать ссылку. Попробуйте ещё раз — "
            "пришлите ссылку на сообщение в топике."
        )
        return

    await state.update_data(topic_id=topic_id)
    await state.set_state(AddChannelState.waiting_prompt_style)
    await message.answer(
        "Выберите стиль публикаций:",
        reply_markup=prompt_style_keyboard()
    )


@dp.callback_query(F.data.startswith("style:"))
async def got_prompt_style(callback: CallbackQuery, state: FSMContext):
    style = callback.data.split(":")[1]
    await state.update_data(prompt_style=style)
    await state.set_state(AddChannelState.waiting_interval)
    await callback.message.edit_text(
        "Как часто публиковать новости?",
        reply_markup=interval_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("interval:"))
async def got_interval(callback: CallbackQuery, state: FSMContext):
    interval = int(callback.data.split(":")[1])
    await state.update_data(interval=interval)
    await state.set_state(AddChannelState.waiting_night_mode)
    await callback.message.edit_text(
        "🌙 Ночной режим — с 23:00 до 8:00 черновики не отправляются.\n\n"
        "Включить?",
        reply_markup=night_mode_keyboard()
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("night:"))

async def got_night_mode(callback: CallbackQuery, state: FSMContext):
    night_mode = callback.data.split(":")[1] == "on"
    await state.update_data(night_mode=night_mode)
    await state.set_state(AddChannelState.waiting_timezone)
    await callback.message.edit_text(
        "Выберите ваш часовой пояс:",
        reply_markup=timezone_keyboard()
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("tz:"))
async def got_timezone(callback: CallbackQuery, state: FSMContext):
    tz = callback.data.split(":")[1]
    if tz == "manual":
        await callback.message.edit_text(
            "Введите часовой пояс вручную.\n\n"
            "Примеры: <code>Europe/Moscow</code>, <code>Asia/Almaty</code>, <code>Europe/Kiev</code>",
            parse_mode="HTML",
        )
        await callback.answer()
        return

    await finish_add_channel(callback, state, tz)
    await callback.answer()


@dp.message(AddChannelState.waiting_timezone)
async def got_timezone_manual(message: Message, state: FSMContext):
    await finish_add_channel(message, state, message.text.strip())


async def finish_add_channel(event, state: FSMContext, timezone: str):
    data    = await state.get_data()
    await state.clear()

    user_id = event.from_user.id

    channel_id = await add_channel(
        user_id=user_id,
        chat_id=data["chat_id"],
        name=data["name"],
        topic_id=data["topic_id"],
        prompt_style=data["prompt_style"],
        interval=data["interval"],
        night_mode=data["night_mode"],
        timezone=timezone,
    )

    text = (
        f"✅ Канал <b>{data['chat_id']}</b> добавлен!\n\n"
        f"⏱ Частота: каждые {data['interval']} ч.\n"
        f"🌙 Ночной режим: {'включён' if data['night_mode'] else 'выключен'}\n"
        f"🕐 Часовой пояс: {timezone}\n\n"
        f"Теперь добавьте RSS источники:\n"
        f"/channels → выберите канал → Добавить источник"
    )

    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, parse_mode="HTML")
    else:
        await event.answer(text, parse_mode="HTML")

# ── Удалить канал ──────────────────────────────────────────────────────────────

@dp.callback_query(F.data.startswith("deletechannel:"))
async def cb_delete_channel(callback: CallbackQuery):
    channel_id = int(callback.data.split(":")[1])
    channel    = await get_channel(channel_id)
    if not channel:
        await callback.answer("Канал не найден.", show_alert=True)
        return
    await delete_channel(channel_id, callback.from_user.id)
    await callback.message.edit_text(f"🗑 Канал <b>{channel['name']}</b> удалён.", parse_mode="HTML")
    await callback.answer()


# ── Источники ──────────────────────────────────────────────────────────────────

@dp.callback_query(F.data.startswith("sources:"))
async def show_sources(callback: CallbackQuery):
    channel_id = int(callback.data.split(":")[1])
    sources    = await get_channel_sources(channel_id)
    if not sources:
        await callback.message.edit_text(
            "Источников пока нет. Добавь первый:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Добавить источник", callback_data=f"addsource:{channel_id}")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data=f"channel:{channel_id}")],
            ])
        )
        await callback.answer()
        return
    await callback.message.edit_text(
        f"RSS источники ({len(sources)}):\nНажми чтобы удалить:",
        reply_markup=sources_keyboard(sources, channel_id)
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("addsource:"))
async def cb_add_source(callback: CallbackQuery, state: FSMContext):
    channel_id = int(callback.data.split(":")[1])
    await state.set_state(AddSourceState.waiting_url)
    await state.update_data(channel_id=channel_id)
    await callback.message.answer("Пришли RSS ссылку (например https://rbc.ru/rss/news):")
    await callback.answer()


@dp.message(AddSourceState.waiting_url)
async def got_source_url(message: Message, state: FSMContext):
    url  = message.text.strip()
    data = await state.get_data()
    await state.clear()

    if not url.startswith("http"):
        await message.answer("Ссылка должна начинаться с http. Попробуй снова через /channels.")
        return

    added = await add_source(data["channel_id"], url)
    if added:
        await message.answer(f"✅ Источник добавлен:\n<code>{url}</code>", parse_mode="HTML")
    else:
        await message.answer("Этот источник уже добавлен.")


@dp.callback_query(F.data.startswith("deletesource:"))
async def cb_delete_source(callback: CallbackQuery):
    _, source_id, channel_id = callback.data.split(":")
    await delete_source(int(source_id), int(channel_id))
    sources = await get_channel_sources(int(channel_id))
    if not sources:
        await callback.message.edit_text(
            "Источников больше нет.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Добавить источник", callback_data=f"addsource:{channel_id}")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data=f"channel:{channel_id}")],
            ])
        )
    else:
        await callback.message.edit_reply_markup(
            reply_markup=sources_keyboard(sources, int(channel_id))
        )
    await callback.answer("Источник удалён.")


# ── /test_post ─────────────────────────────────────────────────────────────────

@dp.message(Command("test_post"))
async def cmd_test_post(message: Message):
    await message.answer("🔄 Запускаю сбор новостей...")
    try:
        from poster import run_cycle
        await run_cycle(bot, MODERATION_GROUP_ID, message.from_user.id)
        await message.answer("✅ Готово — проверяй группу модерации!")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


# ── Модерация: Опубликовать ────────────────────────────────────────────────────

@dp.callback_query(F.data.startswith("draft:approve:"))
async def handle_approve(callback: CallbackQuery):
    draft_id = int(callback.data.split(":")[2])
    draft    = await get_draft_by_id(draft_id)
    if not draft:
        await callback.answer("Черновик не найден.", show_alert=True)
        return
    if draft["status"] in ("published", "rejected"):
        await callback.answer("Уже обработан.", show_alert=True)
        return
    channel = await get_channel(draft["channel_id"])
    if not channel:
        await callback.answer("Канал не найден.", show_alert=True)
        return
    try:
        await bot.send_message(
            chat_id=channel["chat_id"],
            text=draft["content"],
            parse_mode="HTML",
            disable_web_page_preview=False,
        )
        await update_draft_status(draft_id, "published")
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.reply(f"✅ Опубликовано в {channel['chat_id']}")
        await callback.answer()
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)


# ── Модерация: Редактировать ───────────────────────────────────────────────────

@dp.callback_query(F.data.startswith("draft:edit:"))
async def handle_edit(callback: CallbackQuery, state: FSMContext):
    draft_id = int(callback.data.split(":")[2])
    draft    = await get_draft_by_id(draft_id)
    if not draft:
        await callback.answer("Черновик не найден.", show_alert=True)
        return
    await state.set_state(EditState.waiting_for_text)
    await state.update_data(draft_id=draft_id)
    await callback.message.reply(
        "✏️ Пришли новый текст поста:\n\n"
        f"<blockquote>{draft['content']}</blockquote>",
        parse_mode="HTML",
    )
    await callback.answer()


@dp.message(EditState.waiting_for_text)
async def handle_new_text(message: Message, state: FSMContext):
    data     = await state.get_data()
    draft_id = data["draft_id"]
    await update_draft_content(draft_id, message.text)
    await state.clear()
    await message.reply(
        f"Новый текст:\n\n{message.text}",
        reply_markup=confirm_keyboard(draft_id),
    )


# ── Модерация: Отклонить ───────────────────────────────────────────────────────

@dp.callback_query(F.data.startswith("draft:reject:"))
async def handle_reject(callback: CallbackQuery):
    draft_id = int(callback.data.split(":")[2])
    draft    = await get_draft_by_id(draft_id)
    if not draft:
        await callback.answer("Черновик не найден.", show_alert=True)
        return
    if draft["status"] in ("published", "rejected"):
        await callback.answer("Уже обработан.", show_alert=True)
        return
    await update_draft_status(draft_id, "rejected")
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.reply(f"❌ Черновик #{draft_id} отклонён")
    await callback.answer()


# ── Расписание ─────────────────────────────────────────────────────────────────

async def scheduled_posting_loop():
    await asyncio.sleep(60)
    while True:
        try:
            from database import get_pool
            from poster import run_cycle
            pool = await get_pool()
            async with pool.acquire() as conn:
                user_ids = await conn.fetch("SELECT user_id FROM users")
            for row in user_ids:
                await run_cycle(bot, MODERATION_GROUP_ID, row["user_id"])
        except Exception as e:
            logger.error(f"Ошибка цикла постинга: {e}")
        await asyncio.sleep(6 * 60 * 60)


# ── Startup / Webhook ──────────────────────────────────────────────────────────

async def on_startup(app: web.Application):
    await init_db()
    asyncio.create_task(set_webhook_delayed())
    asyncio.create_task(scheduled_posting_loop())


async def set_webhook_delayed():
    await asyncio.sleep(10)
    for attempt in range(5):
        try:
            await bot.set_webhook(url=WEBHOOK_URL, secret_token=WEBHOOK_SECRET)
            logger.warning(f"Webhook set: {WEBHOOK_URL}")
            return
        except Exception as e:
            logger.warning(f"set_webhook attempt {attempt + 1}/5: {e}")
            await asyncio.sleep(5)


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