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

from src.config import TELEGRAM_BOT_TOKEN, SEARCH_COST_STARS, UNLOCK_COST_STARS
from src.facecheck_client import FaceCheckClient
from src import database as db
from src import vk_client

router = Router()
facecheck = FaceCheckClient()

# Version for debugging deployments
BOT_VERSION = "v3.2-vk-names"

# Store pending search results temporarily (search_id -> results)
pending_results: dict[str, dict] = {}

# Store pending photos for paid search (user_id -> image_bytes)
pending_photos: dict[int, bytes] = {}

# Store last search_id for each user (for /debug command)
last_search_by_user: dict[int, str] = {}

WELCOME_MESSAGE = """<b>🔍 Face Search Bot</b>

Send me a photo of a person and I'll search for their profiles online.

<b>How it works:</b>
1. Send a photo with a clear face
2. First search is <b>FREE</b> (10 results, links hidden)
3. Unlock any link for {unlock_cost} ⭐
4. After trial: {search_cost} ⭐ per search (5 results with links)

<b>Commands:</b>
/start - Show this message
/info - Check your status
/debug - Show all results from last search

---

<b>🔍 Бот Поиска по Лицу</b>

Отправьте фото человека, и я найду его профили в интернете.

<b>Как это работает:</b>
1. Отправьте фото с четким лицом
2. Первый поиск <b>БЕСПЛАТНО</b> (10 результатов, ссылки скрыты)
3. Открыть любую ссылку за {unlock_cost} ⭐
4. После триала: {search_cost} ⭐ за поиск (5 результатов со ссылками)

---

<i>Disclaimer: Results are based on visual similarity only. This tool cannot confirm identity. Use responsibly.</i>""".format(
    unlock_cost=UNLOCK_COST_STARS,
    search_cost=SEARCH_COST_STARS
)


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

    lines = ["<b>👤 Найденные имена / Found names:</b>\n"]
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
            text=f"🔍 Search / Поиск - {SEARCH_COST_STARS} ⭐",
            callback_data="paid_search"
        )],
    ])


def get_unlock_keyboard(search_id: str, result_index: int) -> InlineKeyboardMarkup:
    """Create keyboard to unlock a single result link."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"🔓 Unlock link / Открыть ссылку - {UNLOCK_COST_STARS} ⭐",
            callback_data=f"unlock_{search_id}_{result_index}"
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
        f"<b>Your Credits / Ваши кредиты</b>\n\n"
        f"Free searches: {free}\n"
        f"Paid searches: {paid}\n"
        f"Total: {total}\n\n"
        f"API credits: {api_credits}\n"
        f"Bot version: {BOT_VERSION}"
    )


@router.message(Command("buy"))
async def cmd_buy(message: Message):
    credits = await db.get_user_credits(message.from_user.id)
    free = credits.get("free_searches", 0)

    if free > 0:
        await message.answer(
            f"You still have {free} FREE search(es)! Just send a photo.\n\n"
            f"У вас еще есть {free} БЕСПЛАТНЫЙ поиск! Просто отправьте фото."
        )
    else:
        await message.answer(
            f"<b>Paid Search / Платный поиск</b>\n\n"
            f"Each search costs {SEARCH_COST_STARS} ⭐\n"
            f"You get 5 results with direct links.\n\n"
            f"Каждый поиск стоит {SEARCH_COST_STARS} ⭐\n"
            f"Вы получите 5 результатов с прямыми ссылками.\n\n"
            f"Send a photo to start / Отправьте фото для начала"
        )


@router.message(Command("reset"))
async def cmd_reset(message: Message):
    """Reset user credits for testing."""
    success = await db.reset_user_credits(message.from_user.id)
    if success:
        await message.answer(
            "✅ Credits reset! You now have 1 free search.\n\n"
            "✅ Кредиты сброшены! У вас 1 бесплатный поиск."
        )
    else:
        await message.answer("Failed to reset credits. / Не удалось сбросить кредиты.")


@router.message(Command("debug"))
async def cmd_debug(message: Message):
    """Show all results from last search (for debugging)."""
    user_id = message.from_user.id

    if user_id not in last_search_by_user:
        await message.answer(
            "No recent search found. Send a photo first.\n\n"
            "Поиск не найден. Сначала отправьте фото."
        )
        return

    search_id = last_search_by_user[user_id]

    if search_id not in pending_results:
        await message.answer(
            "Search results expired. Do a new search.\n\n"
            "Результаты поиска устарели. Сделайте новый поиск."
        )
        return

    result = pending_results[search_id]
    output = result.get("output", {})
    faces = output.get("items", [])

    if not faces:
        await message.answer("No results in last search. / Нет результатов в последнем поиске.")
        return

    # Build text list of ALL results
    lines = [f"<b>🔍 Debug: All {len(faces)} results</b>\n"]

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
        title="Face Search / Поиск по лицу",
        description=f"Search for face matches (5 results with links) / Поиск совпадений (5 результатов со ссылками)",
        payload="paid_search",
        currency="XTR",
        prices=[LabeledPrice(label="Face Search", amount=SEARCH_COST_STARS)],
    )
    await callback.answer()


@router.callback_query(F.data.startswith("unlock_"))
async def handle_unlock(callback: CallbackQuery, bot: Bot):
    parts = callback.data.split("_")
    search_id = parts[1]
    result_index = int(parts[2])

    # Send invoice for unlocking the link
    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title="Unlock Link / Открыть ссылку",
        description="Get the source link for this face match / Получить ссылку на источник",
        payload=f"unlock_{search_id}_{result_index}",
        currency="XTR",
        prices=[LabeledPrice(label="Unlock link", amount=UNLOCK_COST_STARS)],
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
                "Payment received but no photo found. Please send a new photo.\n\n"
                "Оплата получена, но фото не найдено. Отправьте новое фото."
            )
            return

        image_bytes = pending_photos.pop(user_id)
        await execute_paid_search(message, bot, image_bytes)

    elif payload.startswith("unlock_"):
        parts = payload.split("_")
        search_id = parts[1]
        result_index = int(parts[2])

        # Get stored results
        if search_id in pending_results:
            results = pending_results[search_id]
            faces = results.get("output", {}).get("items", [])

            if result_index < len(faces):
                face = faces[result_index]
                url = face.get("url", "N/A")

                await message.answer(
                    f"🔓 <b>Link Unlocked / Ссылка открыта</b>\n\n"
                    f"Score: {face.get('score', 0)}%\n"
                    f"🔗 {url}",
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )
        else:
            await message.answer(
                "Results expired. Please do a new search.\n\n"
                "Результаты устарели. Сделайте новый поиск."
            )

        await db.record_payment(user_id, stars, 0, payment_id)


async def execute_paid_search(message: Message, bot: Bot, image_bytes: bytes):
    """Execute a paid search and show 5 results with links."""
    status_msg = await message.answer("🔍 Searching... / Поиск...")

    last_progress_text = ""

    async def on_progress(progress: int):
        nonlocal last_progress_text
        new_text = f"🔍 Searching... {progress}% / Поиск... {progress}%"
        if new_text != last_progress_text:
            try:
                await status_msg.edit_text(new_text)
                last_progress_text = new_text
            except TelegramBadRequest:
                pass

    result = await facecheck.find_face(image_bytes, demo=False, on_progress=on_progress)

    if not result:
        await status_msg.edit_text("Search failed. Please try again.\n\nОшибка поиска. Попробуйте снова.")
        return

    if result.get("error"):
        await status_msg.edit_text(f"Error: {result['error']}")
        return

    output = result.get("output", {})
    faces = output.get("items", [])

    searched = output.get('searchedFaces')
    searched_str = f"{searched:,}" if isinstance(searched, int) else "N/A"
    took_sec = output.get('tookSeconds') or 0

    stats = (
        f"<b>✅ Search Complete / Поиск завершен</b>\n\n"
        f"Faces scanned: {searched_str}\n"
        f"Time: {took_sec:.1f}s\n"
        f"Results: {min(len(faces), 5)}\n"
    )

    if not faces:
        await status_msg.edit_text(stats + "\n<i>No matches found. / Совпадений не найдено.</i>")
        return

    # Store search results for /debug command
    search_id = result.get("id_search") or str(message.message_id)
    pending_results[search_id] = result
    last_search_by_user[message.from_user.id] = search_id

    await status_msg.edit_text(stats + "\nSending results... / Отправка результатов...")

    # Paid search: show 5 results with links
    for i, face in enumerate(faces[:5], 1):
        score = face.get("score", 0)
        url = face.get("url", "N/A")

        caption = f"<b>#{i}</b> - Score: {score}%\n🔗 {url}"

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
    names = await extract_names_from_results(faces[:5])
    await send_name_summary(message, names)


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
            title="Face Search / Поиск по лицу",
            description=f"Search for face matches (5 results with links)\nПоиск совпадений (5 результатов со ссылками)",
            payload="paid_search",
            currency="XTR",
            prices=[LabeledPrice(label="Face Search", amount=SEARCH_COST_STARS)],
        )


async def execute_free_search(message: Message, bot: Bot, image_bytes: bytes):
    """Execute a free search and show 10 results with hidden links."""
    status_msg = await message.answer("🔍 Searching... / Поиск...")

    last_progress_text = ""

    async def on_progress(progress: int):
        nonlocal last_progress_text
        new_text = f"🔍 Searching... {progress}% / Поиск... {progress}%"
        if new_text != last_progress_text:
            try:
                await status_msg.edit_text(new_text)
                last_progress_text = new_text
            except TelegramBadRequest:
                pass

    result = await facecheck.find_face(image_bytes, demo=False, on_progress=on_progress)

    if not result:
        await status_msg.edit_text("Search failed. Please try again.\n\nОшибка поиска. Попробуйте снова.")
        return

    if result.get("error"):
        await status_msg.edit_text(f"Error: {result['error']}")
        return

    # Use free search credit
    await db.use_search(message.from_user.id)

    output = result.get("output", {})
    faces = output.get("items", [])

    searched = output.get('searchedFaces')
    searched_str = f"{searched:,}" if isinstance(searched, int) else "N/A"
    took_sec = output.get('tookSeconds') or 0

    stats = (
        f"<b>✅ FREE Search Complete / Бесплатный поиск завершен</b>\n\n"
        f"Faces scanned: {searched_str}\n"
        f"Time: {took_sec:.1f}s\n"
        f"Results: {min(len(faces), 10)}\n"
    )

    if not faces:
        await status_msg.edit_text(stats + "\n<i>No matches found. / Совпадений не найдено.</i>")
        return

    search_id = result.get("id_search") or str(message.message_id)
    pending_results[search_id] = result
    last_search_by_user[message.from_user.id] = search_id

    await status_msg.edit_text(
        stats + f"\n<i>🔒 Links are hidden. Unlock each for {UNLOCK_COST_STARS} ⭐\n"
        f"Ссылки скрыты. Открыть каждую за {UNLOCK_COST_STARS} ⭐</i>"
    )

    # Free search: show 10 results with hidden links
    for i, face in enumerate(faces[:10], 1):
        score = face.get("score", 0)

        caption = f"<b>#{i}</b> - Score: {score}%\n🔒 <i>Link hidden / Ссылка скрыта</i>"

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

    # Extract and show names from VK profiles
    names = await extract_names_from_results(faces[:10])
    await send_name_summary(message, names)


@router.message()
async def handle_other(message: Message):
    await message.answer(
        "Please send a photo to search.\n"
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
