import base64
import logging
from io import BytesIO

import httpx
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message, LinkPreviewOptions, BufferedInputFile,
    CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    LabeledPrice, PreCheckoutQuery
)
from aiogram.filters import CommandStart, Command
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramBadRequest

from PIL import Image, ImageFilter

logger = logging.getLogger(__name__)

from src.config import (
    TELEGRAM_BOT_TOKEN, SEARCH_COST_STARS, SEARCH_PACK_5_STARS,
    UNLOCK_SINGLE_STARS, UNLOCK_ALL_STARS, ADMIN_CHAT_ID,
    API_BALANCE_ALERT_THRESHOLD
)
from src.facecheck_client import FaceCheckClient
from src import database as db
from src import vk_client

router = Router()
facecheck = FaceCheckClient()

# Version for debugging deployments
BOT_VERSION = "v4.0-new-pricing"

# Track if low balance alert was already sent (to avoid spam)
_low_balance_alert_sent = False


async def check_api_balance_and_alert(bot: Bot):
    """Check FaceCheck API balance and send alert if low."""
    global _low_balance_alert_sent

    if not ADMIN_CHAT_ID:
        return

    try:
        info = await facecheck.get_info()
        if not info:
            return

        remaining = info.get('remaining_credits', 0)

        if remaining <= API_BALANCE_ALERT_THRESHOLD and not _low_balance_alert_sent:
            await bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"⚠️ <b>Внимание! Низкий баланс FaceCheck API</b>\n\n"
                     f"Осталось кредитов: <b>{remaining}</b>\n"
                     f"Порог алерта: {API_BALANCE_ALERT_THRESHOLD}\n\n"
                     f"Пополните баланс на facecheck.id"
            )
            _low_balance_alert_sent = True
            logger.warning(f"Low API balance alert sent: {remaining} credits remaining")

        elif remaining > API_BALANCE_ALERT_THRESHOLD:
            _low_balance_alert_sent = False  # Reset flag when balance is OK

    except Exception as e:
        logger.error(f"Balance check error: {e}")

# Store pending search results temporarily (search_id -> results)
pending_results: dict[str, dict] = {}

# Store pending photos for paid search (user_id -> image_bytes)
pending_photos: dict[int, bytes] = {}

# Store last search_id for each user (for /debug command)
last_search_by_user: dict[int, str] = {}

WELCOME_MESSAGE = f"""<b>🔍 Бот Поиска по Лицу</b>

Отправьте фото — найду профили в интернете.

<b>💎 Цены:</b>
• Первый поиск: <b>БЕСПЛАТНО</b> (10 результатов, ссылки скрыты)
• Открыть 1 ссылку: {UNLOCK_SINGLE_STARS} ⭐
• Открыть ВСЕ 10 ссылок: {UNLOCK_ALL_STARS} ⭐
• Новый поиск: {SEARCH_COST_STARS} ⭐ (10 результатов со ссылками)
• Пакет 5 поисков: {SEARCH_PACK_5_STARS} ⭐ (экономия {SEARCH_COST_STARS * 5 - SEARCH_PACK_5_STARS} ⭐)

<b>Команды:</b>
/start - Это сообщение
/buy - Купить поиски
/info - Ваши кредиты

<b>⚠️ Важно:</b>
• Бот работает только с публичными источниками
• Результаты — предположительные совпадения, не подтверждение личности
• Используйте только с согласия человека на фото
• Изображения не сохраняются после обработки"""


def blur_image(img_bytes: bytes, blur_radius: int = 30) -> bytes:
    """Apply heavy blur to image."""
    img = Image.open(BytesIO(img_bytes))
    blurred = img.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    output = BytesIO()
    blurred.save(output, format="JPEG", quality=70)
    return output.getvalue()


async def fetch_image_from_url(url: str) -> bytes | None:
    """Fetch image from URL."""
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.get(url)
            if response.status_code == 200:
                content_type = response.headers.get("content-type", "")
                if "image" in content_type or url.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.gif')):
                    return response.content
    except Exception as e:
        logger.error(f"Failed to fetch image from {url}: {e}")
    return None


async def get_image_bytes(face: dict) -> bytes | None:
    """Get image bytes from face result - try base64 first, then URL."""
    # Try base64 first
    base64_img = face.get("base64", "")
    if base64_img and base64_img.startswith("data:image"):
        try:
            img_data = base64_img.split(",", 1)[1]
            return base64.b64decode(img_data)
        except Exception as e:
            logger.error(f"Base64 decode error: {e}")

    # Try image_url or thumb_url from API
    for url_field in ["image_url", "thumb_url", "url"]:
        url = face.get(url_field)
        if url and url.startswith("http"):
            img_bytes = await fetch_image_from_url(url)
            if img_bytes:
                return img_bytes

    return None


async def extract_names_from_results(faces: list[dict]) -> dict[str, str]:
    """Extract names from VK profiles in search results."""
    urls = [face.get("url", "") for face in faces if face.get("url")]
    return await vk_client.extract_names_from_urls(urls)


async def send_name_summary(message: Message, names: dict[str, str]):
    """Send summary of found names."""
    if not names:
        return

    lines = ["<b>👤 Найденные имена:</b>\n"]
    for url, name in names.items():
        lines.append(f"• <b>{name}</b>\n  {url}")

    await message.answer(
        "\n".join(lines),
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )


def get_search_keyboard() -> InlineKeyboardMarkup:
    """Create keyboard for buying a paid search."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"🔍 Поиск - {SEARCH_COST_STARS} ⭐",
            callback_data="paid_search"
        )],
    ])


def get_unlock_keyboard(search_id: str, result_index: int) -> InlineKeyboardMarkup:
    """Create keyboard to unlock a single result link."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"🔓 Открыть - {UNLOCK_SINGLE_STARS} ⭐",
            callback_data=f"unlock_{search_id}_{result_index}"
        )],
    ])


def get_unlock_all_keyboard(search_id: str) -> InlineKeyboardMarkup:
    """Create keyboard to unlock all results at once."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"🔓 Открыть ВСЕ 10 - {UNLOCK_ALL_STARS} ⭐",
            callback_data=f"unlock_all_{search_id}"
        )],
    ])


@router.message(CommandStart())
async def cmd_start(message: Message):
    user = await db.get_or_create_user(
        message.from_user.id,
        message.from_user.username
    )
    await message.answer(WELCOME_MESSAGE)


@router.message(Command("info"))
async def cmd_info(message: Message):
    credits = await db.get_user_credits(message.from_user.id)
    free = credits.get("free_searches", 0)
    paid = credits.get("paid_searches", 0)
    total = free + paid

    info = await facecheck.get_info()
    api_credits = "N/A"
    if info:
        api_credits = info.get('remaining_credits', 'N/A')

    await message.answer(
        f"<b>Ваши кредиты</b>\n\n"
        f"Бесплатные поиски: {free}\n"
        f"Платные поиски: {paid}\n"
        f"Всего: {total}\n\n"
        f"API кредиты: {api_credits}\n"
        f"Версия бота: {BOT_VERSION}"
    )


@router.message(Command("buy"))
async def cmd_buy(message: Message):
    credits = await db.get_user_credits(message.from_user.id)
    free = credits.get("free_searches", 0)
    paid = credits.get("paid_searches", 0)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"🔍 1 поиск - {SEARCH_COST_STARS} ⭐",
            callback_data="buy_1_search"
        )],
        [InlineKeyboardButton(
            text=f"🎁 5 поисков - {SEARCH_PACK_5_STARS} ⭐ (экономия {SEARCH_COST_STARS * 5 - SEARCH_PACK_5_STARS} ⭐)",
            callback_data="buy_5_searches"
        )],
    ])

    await message.answer(
        f"<b>💎 Купить поиски</b>\n\n"
        f"Ваши кредиты: {free + paid} ({free} бесп. + {paid} платн.)\n\n"
        f"Каждый поиск даёт 10 результатов со ссылками.",
        reply_markup=keyboard
    )


@router.message(Command("reset"))
async def cmd_reset(message: Message):
    """Reset user credits for testing."""
    success = await db.reset_user_credits(message.from_user.id)
    if success:
        await message.answer(
            "✅ Кредиты сброшены! У вас 1 бесплатный поиск."
        )
    else:
        await message.answer("Не удалось сбросить кредиты.")


@router.message(Command("debug"))
async def cmd_debug(message: Message):
    """Show all results from last search (for debugging)."""
    user_id = message.from_user.id

    if user_id not in last_search_by_user:
        await message.answer(
            "Поиск не найден. Сначала отправьте фото."
        )
        return

    search_id = last_search_by_user[user_id]

    if search_id not in pending_results:
        await message.answer(
            "Результаты поиска устарели. Сделайте новый поиск."
        )
        return

    result = pending_results[search_id]
    output = result.get("output", {})
    faces = output.get("items", [])

    if not faces:
        await message.answer("Нет результатов в последнем поиске.")
        return

    # Build text list of ALL results
    lines = [f"<b>🔍 Отладка: Все {len(faces)} результатов</b>\n"]

    for i, face in enumerate(faces, 1):
        score = face.get("score", 0)
        url = face.get("url", "N/A")
        lines.append(f"{i}. [{score}%] {url}")

    # Split into chunks if too long (Telegram limit ~4096 chars)
    full_text = "\n".join(lines)

    if len(full_text) <= 4000:
        await message.answer(full_text, link_preview_options=LinkPreviewOptions(is_disabled=True))
    else:
        # Send in chunks
        chunk_lines = []
        chunk_len = 0
        for line in lines:
            if chunk_len + len(line) + 1 > 4000:
                await message.answer("\n".join(chunk_lines), link_preview_options=LinkPreviewOptions(is_disabled=True))
                chunk_lines = []
                chunk_len = 0
            chunk_lines.append(line)
            chunk_len += len(line) + 1

        if chunk_lines:
            await message.answer("\n".join(chunk_lines), link_preview_options=LinkPreviewOptions(is_disabled=True))


@router.callback_query(F.data == "paid_search")
async def handle_paid_search_request(callback: CallbackQuery, bot: Bot):
    """User wants to do a paid search - send invoice."""
    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title="Поиск по лицу",
        description="10 результатов со ссылками",
        payload="paid_search",
        currency="XTR",
        prices=[LabeledPrice(label="Поиск по лицу", amount=SEARCH_COST_STARS)],
    )
    await callback.answer()


@router.callback_query(F.data == "buy_1_search")
async def handle_buy_1_search(callback: CallbackQuery, bot: Bot):
    """Buy 1 search credit."""
    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title="1 Поиск",
        description="10 результатов со ссылками",
        payload="buy_1_search",
        currency="XTR",
        prices=[LabeledPrice(label="1 Поиск", amount=SEARCH_COST_STARS)],
    )
    await callback.answer()


@router.callback_query(F.data == "buy_5_searches")
async def handle_buy_5_searches(callback: CallbackQuery, bot: Bot):
    """Buy 5 searches pack."""
    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title="Пакет 5 поисков",
        description=f"Всего 50 результатов, экономия {SEARCH_COST_STARS * 5 - SEARCH_PACK_5_STARS} ⭐",
        payload="buy_5_searches",
        currency="XTR",
        prices=[LabeledPrice(label="5 Поисков", amount=SEARCH_PACK_5_STARS)],
    )
    await callback.answer()


@router.callback_query(F.data.startswith("unlock_all_"))
async def handle_unlock_all(callback: CallbackQuery, bot: Bot):
    """Unlock all 10 results at once."""
    search_id = callback.data.replace("unlock_all_", "")
    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title="Открыть все 10",
        description="Получить все 10 ссылок",
        payload=f"unlock_all_{search_id}",
        currency="XTR",
        prices=[LabeledPrice(label="Открыть все", amount=UNLOCK_ALL_STARS)],
    )
    await callback.answer()


@router.callback_query(F.data.startswith("unlock_"))
async def handle_unlock(callback: CallbackQuery, bot: Bot):
    # Skip if it's unlock_all (handled separately)
    if callback.data.startswith("unlock_all_"):
        return

    parts = callback.data.split("_")
    search_id = parts[1]
    result_index = int(parts[2])

    # Send invoice for unlocking the link
    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title="Открыть ссылку",
        description="Получить ссылку на источник",
        payload=f"unlock_{search_id}_{result_index}",
        currency="XTR",
        prices=[LabeledPrice(label="Открыть ссылку", amount=UNLOCK_SINGLE_STARS)],
    )
    await callback.answer()


@router.pre_checkout_query()
async def handle_pre_checkout(pre_checkout: PreCheckoutQuery, bot: Bot):
    await bot.answer_pre_checkout_query(pre_checkout.id, ok=True)


@router.message(F.successful_payment)
async def handle_successful_payment(message: Message, bot: Bot):
    payload = message.successful_payment.invoice_payload
    payment_id = message.successful_payment.telegram_payment_charge_id
    stars = message.successful_payment.total_amount
    user_id = message.from_user.id

    if payload == "paid_search":
        # User paid for a search - now execute it
        await db.record_payment(user_id, stars, 1, payment_id)

        if user_id not in pending_photos:
            await message.answer(
                "Оплата получена, но фото не найдено. Отправьте новое фото."
            )
            return

        image_bytes = pending_photos.pop(user_id)
        await execute_paid_search(message, bot, image_bytes)

    elif payload == "buy_1_search":
        # Add 1 search credit
        await db.add_paid_searches(user_id, 1)
        await db.record_payment(user_id, stars, 1, payment_id)
        await message.answer(
            "✅ <b>1 поиск добавлен!</b>\n"
            "Отправьте фото для начала."
        )

    elif payload == "buy_5_searches":
        # Add 5 search credits
        await db.add_paid_searches(user_id, 5)
        await db.record_payment(user_id, stars, 5, payment_id)
        await message.answer(
            "✅ <b>5 поисков добавлено!</b>\n"
            "Отправьте фото для начала."
        )

    elif payload.startswith("unlock_all_"):
        search_id = payload.replace("unlock_all_", "")

        if search_id in pending_results:
            results = pending_results[search_id]
            faces = results.get("output", {}).get("items", [])[:10]

            lines = ["🔓 <b>Все ссылки открыты</b>\n"]
            for i, face in enumerate(faces, 1):
                score = face.get("score", 0)
                url = face.get("url", "N/A")
                lines.append(f"{i}. [{score}%] {url}")

            await message.answer(
                "\n".join(lines),
                link_preview_options=LinkPreviewOptions(is_disabled=True)
            )
        else:
            await message.answer(
                "Результаты устарели. Сделайте новый поиск."
            )

        await db.record_payment(user_id, stars, 0, payment_id)

    elif payload.startswith("unlock_"):
        parts = payload.split("_")
        search_id = parts[1]
        result_index = int(parts[2])

        if search_id in pending_results:
            results = pending_results[search_id]
            faces = results.get("output", {}).get("items", [])

            if result_index < len(faces):
                face = faces[result_index]
                url = face.get("url", "N/A")

                await message.answer(
                    f"🔓 <b>Ссылка открыта</b>\n\n"
                    f"Совпадение: {face.get('score', 0)}%\n"
                    f"🔗 {url}",
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )
        else:
            await message.answer(
                "Результаты устарели. Сделайте новый поиск."
            )

        await db.record_payment(user_id, stars, 0, payment_id)


async def execute_paid_search(message: Message, bot: Bot, image_bytes: bytes):
    """Execute a paid search and show 5 results with links."""
    status_msg = await message.answer("🔍 Поиск...")

    last_progress_text = ""

    async def on_progress(progress: int):
        nonlocal last_progress_text
        new_text = f"🔍 Поиск... {progress}%"
        if new_text != last_progress_text:
            try:
                await status_msg.edit_text(new_text)
                last_progress_text = new_text
            except TelegramBadRequest:
                pass

    result = await facecheck.find_face(image_bytes, demo=False, on_progress=on_progress)

    if not result:
        await status_msg.edit_text("Ошибка поиска. Попробуйте снова.")
        return

    if result.get("error"):
        await status_msg.edit_text(f"Ошибка: {result['error']}")
        return

    output = result.get("output", {})
    faces = output.get("items", [])

    searched = output.get('searchedFaces')
    searched_str = f"{searched:,}" if isinstance(searched, int) else "N/A"
    took_sec = output.get('tookSeconds') or 0

    stats = (
        f"<b>✅ Поиск завершен</b>\n\n"
        f"Просканировано лиц: {searched_str}\n"
        f"Время: {took_sec:.1f}с\n"
        f"Результатов: {min(len(faces), 10)}\n"
    )

    if not faces:
        await status_msg.edit_text(stats + "\n<i>Совпадений не найдено.</i>")
        return

    # Store search results for /debug command
    search_id = result.get("id_search") or str(message.message_id)
    pending_results[search_id] = result
    last_search_by_user[message.from_user.id] = search_id

    await status_msg.edit_text(stats + "\nОтправка результатов...")

    # Paid search: show 10 results with links
    for i, face in enumerate(faces[:10], 1):
        score = face.get("score", 0)
        url = face.get("url", "N/A")

        caption = f"<b>#{i}</b> - Совпадение: {score}%\n🔗 {url}"

        img_bytes = await get_image_bytes(face)
        if img_bytes:
            try:
                photo_file = BufferedInputFile(img_bytes, filename=f"face_{i}.jpg")
                await message.answer_photo(
                    photo_file,
                    caption=caption,
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )
            except Exception as e:
                logger.error(f"Send photo error: {e}")
                await message.answer(caption, link_preview_options=LinkPreviewOptions(is_disabled=True))
        else:
            await message.answer(caption, link_preview_options=LinkPreviewOptions(is_disabled=True))

    await status_msg.delete()

    # Extract and show names from VK profiles
    names = await extract_names_from_results(faces[:10])
    await send_name_summary(message, names)

    # Check API balance and alert if low
    await check_api_balance_and_alert(bot)


@router.message(F.photo)
async def handle_photo(message: Message, bot: Bot):
    user = await db.get_or_create_user(
        message.from_user.id,
        message.from_user.username
    )

    credits = await db.get_user_credits(message.from_user.id)
    free_searches = credits.get("free_searches", 0)

    # Download the photo
    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    image_data = await bot.download_file(file.file_path)
    image_bytes = image_data.read()

    if free_searches > 0:
        # FREE SEARCH: 10 results with hidden links
        await execute_free_search(message, bot, image_bytes)
    else:
        # PAID SEARCH: Store photo and request payment
        pending_photos[message.from_user.id] = image_bytes
        await bot.send_invoice(
            chat_id=message.from_user.id,
            title="Поиск по лицу",
            description="10 результатов со ссылками",
            payload="paid_search",
            currency="XTR",
            prices=[LabeledPrice(label="Поиск по лицу", amount=SEARCH_COST_STARS)],
        )


async def execute_free_search(message: Message, bot: Bot, image_bytes: bytes):
    """Execute a free search and show 10 results with hidden links."""
    status_msg = await message.answer("🔍 Поиск...")

    last_progress_text = ""

    async def on_progress(progress: int):
        nonlocal last_progress_text
        new_text = f"🔍 Поиск... {progress}%"
        if new_text != last_progress_text:
            try:
                await status_msg.edit_text(new_text)
                last_progress_text = new_text
            except TelegramBadRequest:
                pass

    result = await facecheck.find_face(image_bytes, demo=False, on_progress=on_progress)

    if not result:
        await status_msg.edit_text("Ошибка поиска. Попробуйте снова.")
        return

    if result.get("error"):
        await status_msg.edit_text(f"Ошибка: {result['error']}")
        return

    # Use free search credit
    await db.use_search(message.from_user.id)

    output = result.get("output", {})
    faces = output.get("items", [])

    searched = output.get('searchedFaces')
    searched_str = f"{searched:,}" if isinstance(searched, int) else "N/A"
    took_sec = output.get('tookSeconds') or 0

    stats = (
        f"<b>✅ Бесплатный поиск завершен</b>\n\n"
        f"Просканировано лиц: {searched_str}\n"
        f"Время: {took_sec:.1f}с\n"
        f"Результатов: {min(len(faces), 10)}\n"
    )

    if not faces:
        await status_msg.edit_text(stats + "\n<i>Совпадений не найдено.</i>")
        return

    search_id = result.get("id_search") or str(message.message_id)
    pending_results[search_id] = result
    last_search_by_user[message.from_user.id] = search_id

    await status_msg.edit_text(
        stats + f"\n<i>🔒 Ссылки скрыты. Открыть 1 за {UNLOCK_SINGLE_STARS} ⭐ или ВСЕ за {UNLOCK_ALL_STARS} ⭐</i>"
    )

    # Free search: show 10 results with hidden links
    for i, face in enumerate(faces[:10], 1):
        score = face.get("score", 0)

        caption = f"<b>#{i}</b> - Совпадение: {score}%\n🔒 <i>Ссылка скрыта</i>"

        img_bytes = await get_image_bytes(face)
        if img_bytes:
            try:
                photo_file = BufferedInputFile(img_bytes, filename=f"face_{i}.jpg")
                await message.answer_photo(
                    photo_file,
                    caption=caption,
                    reply_markup=get_unlock_keyboard(search_id, i - 1)
                )
            except Exception as e:
                logger.error(f"Send photo error: {e}")
                await message.answer(caption, reply_markup=get_unlock_keyboard(search_id, i - 1))
        else:
            await message.answer(caption, reply_markup=get_unlock_keyboard(search_id, i - 1))

    # Add "Unlock All" button
    await message.answer(
        f"💡 <b>Совет:</b> Откройте все 10 ссылок сразу за {UNLOCK_ALL_STARS} ⭐ (экономия {UNLOCK_SINGLE_STARS * 10 - UNLOCK_ALL_STARS} ⭐)",
        reply_markup=get_unlock_all_keyboard(search_id)
    )

    # Extract and show names from VK profiles
    names = await extract_names_from_results(faces[:10])
    await send_name_summary(message, names)

    # Check API balance and alert if low
    await check_api_balance_and_alert(bot)


@router.message()
async def handle_other(message: Message):
    await message.answer(
        "Пожалуйста, отправьте фото для поиска."
    )


def create_bot() -> tuple[Bot, Dispatcher]:
    bot = Bot(
        token=TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()
    dp.include_router(router)
    return bot, dp
