import base64
import logging
from io import BytesIO

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

from src.config import TELEGRAM_BOT_TOKEN, PRICING, UNLOCK_COST_STARS
from src.facecheck_client import FaceCheckClient
from src import database as db

router = Router()
facecheck = FaceCheckClient()

# Store pending search results temporarily (search_id -> results)
pending_results: dict[str, dict] = {}

WELCOME_MESSAGE = """<b>Face Search Bot</b>

Send me a photo of a person and I'll search for their profiles online.

<b>How it works:</b>
1. Send a photo with a clear face
2. Get your first search FREE
3. Results show where the face appears online

<b>Commands:</b>
/start - Show this message
/info - Check your credits
/buy - Purchase more searches

---

<b>Бот Поиска по Лицу</b>

Отправьте фото человека, и я найду его профили в интернете.

<b>Как это работает:</b>
1. Отправьте фото с четким лицом
2. Первый поиск БЕСПЛАТНО
3. Результаты покажут, где лицо появляется онлайн

<b>Команды:</b>
/start - Показать это сообщение
/info - Проверить кредиты
/buy - Купить поиски

---

<i>Disclaimer: Results are based on visual similarity only. This tool cannot confirm identity. Use responsibly.</i>"""

BUY_MESSAGE = """<b>Buy Search Credits</b>

Choose a package:

1 search = 149 ⭐
5 searches = 649 ⭐ (save 20%)
10 searches = 1199 ⭐ (save 20%)

---

<b>Купить Кредиты</b>

Выберите пакет:

1 поиск = 149 ⭐
5 поисков = 649 ⭐ (экономия 20%)
10 поисков = 1199 ⭐ (экономия 20%)"""


def blur_image(img_bytes: bytes, blur_radius: int = 30) -> bytes:
    """Apply heavy blur to image."""
    img = Image.open(BytesIO(img_bytes))
    blurred = img.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    output = BytesIO()
    blurred.save(output, format="JPEG", quality=70)
    return output.getvalue()


def get_buy_keyboard() -> InlineKeyboardMarkup:
    """Create keyboard for buying searches."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1 search - 149 ⭐", callback_data="buy_1")],
        [InlineKeyboardButton(text="5 searches - 649 ⭐", callback_data="buy_5")],
        [InlineKeyboardButton(text="10 searches - 1199 ⭐", callback_data="buy_10")],
    ])


def get_unlock_keyboard(search_id: str, result_index: int) -> InlineKeyboardMarkup:
    """Create keyboard to unlock a single result."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"Unlock for {UNLOCK_COST_STARS} ⭐",
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
        f"API credits: {api_credits}"
    )


@router.message(Command("buy"))
async def cmd_buy(message: Message):
    await message.answer(BUY_MESSAGE, reply_markup=get_buy_keyboard())


@router.callback_query(F.data.startswith("buy_"))
async def handle_buy(callback: CallbackQuery, bot: Bot):
    amount = int(callback.data.split("_")[1])
    price = PRICING.get(amount)

    if not price:
        await callback.answer("Invalid package")
        return

    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title=f"{amount} Face Search{'es' if amount > 1 else ''}",
        description=f"Purchase {amount} face search credit{'s' if amount > 1 else ''}",
        payload=f"searches_{amount}",
        currency="XTR",  # Telegram Stars
        prices=[LabeledPrice(label=f"{amount} search{'es' if amount > 1 else ''}", amount=price)],
    )
    await callback.answer()


@router.callback_query(F.data.startswith("unlock_"))
async def handle_unlock(callback: CallbackQuery, bot: Bot):
    parts = callback.data.split("_")
    search_id = parts[1]
    result_index = int(parts[2])

    # Send invoice for unlocking
    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title="Unlock Search Result",
        description="Unlock this face match to see the full image and link",
        payload=f"unlock_{search_id}_{result_index}",
        currency="XTR",
        prices=[LabeledPrice(label="Unlock result", amount=UNLOCK_COST_STARS)],
    )
    await callback.answer()


@router.pre_checkout_query()
async def handle_pre_checkout(pre_checkout: PreCheckoutQuery, bot: Bot):
    await bot.answer_pre_checkout_query(pre_checkout.id, ok=True)


@router.message(F.successful_payment)
async def handle_successful_payment(message: Message):
    payload = message.successful_payment.invoice_payload
    payment_id = message.successful_payment.telegram_payment_charge_id
    stars = message.successful_payment.total_amount

    if payload.startswith("searches_"):
        amount = int(payload.split("_")[1])
        await db.add_paid_searches(message.from_user.id, amount)
        await db.record_payment(
            message.from_user.id,
            stars,
            amount,
            payment_id
        )
        await message.answer(
            f"Payment successful! Added {amount} search{'es' if amount > 1 else ''}.\n\n"
            f"Оплата прошла! Добавлено {amount} поиск{'ов' if amount > 1 else ''}."
        )

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
                base64_img = face.get("base64", "")

                caption = f"<b>Unlocked Result</b>\n\nScore: {face.get('score', 0)}%\n{url}"

                if base64_img and base64_img.startswith("data:image"):
                    try:
                        img_data = base64_img.split(",", 1)[1]
                        img_bytes = base64.b64decode(img_data)
                        photo_file = BufferedInputFile(img_bytes, filename="face.jpg")
                        await message.answer_photo(
                            photo_file,
                            caption=caption,
                            link_preview_options=LinkPreviewOptions(is_disabled=True)
                        )
                    except Exception:
                        await message.answer(
                            caption,
                            link_preview_options=LinkPreviewOptions(is_disabled=True)
                        )
                else:
                    await message.answer(caption)

        await db.record_payment(
            message.from_user.id,
            stars,
            0,  # No searches, just unlock
            payment_id
        )


@router.message(F.photo)
async def handle_photo(message: Message, bot: Bot):
    user = await db.get_or_create_user(
        message.from_user.id,
        message.from_user.username
    )

    # Check if user has credits
    credits = await db.get_user_credits(message.from_user.id)
    total_credits = credits.get("free_searches", 0) + credits.get("paid_searches", 0)

    if total_credits <= 0:
        await message.answer(
            "You have no search credits.\n"
            "Use /buy to purchase more.\n\n"
            "У вас нет кредитов.\n"
            "Используйте /buy для покупки.",
            reply_markup=get_buy_keyboard()
        )
        return

    status_msg = await message.answer("Uploading image... / Загрузка...")

    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    image_bytes = await bot.download_file(file.file_path)

    last_progress_text = ""

    async def on_progress(progress: int):
        nonlocal last_progress_text
        new_text = f"Searching... {progress}% / Поиск... {progress}%"
        if new_text != last_progress_text:
            try:
                await status_msg.edit_text(new_text)
                last_progress_text = new_text
            except TelegramBadRequest:
                pass

    await status_msg.edit_text("Searching... / Поиск...")
    result = await facecheck.find_face(
        image_bytes.read(),
        demo=False,
        on_progress=on_progress
    )

    if not result:
        await status_msg.edit_text("Search failed. Please try again. / Ошибка. Попробуйте снова.")
        return

    if result.get("error"):
        await status_msg.edit_text(f"Error: {result['error']}")
        return

    # Use one credit
    success, is_free = await db.use_search(message.from_user.id)

    output = result.get("output", {})
    faces = output.get("items", [])

    # Build statistics
    searched = output.get('searchedFaces')
    searched_str = f"{searched:,}" if isinstance(searched, int) else "N/A"
    took_sec = output.get('tookSeconds') or 0
    max_score = output.get('max_score') or 0

    credit_type = "FREE" if is_free else "paid"
    stats = (
        f"<b>Search Complete / Поиск завершен</b>\n\n"
        f"Faces scanned: {searched_str}\n"
        f"Time: {took_sec:.1f}s\n"
        f"Max score: {max_score}%\n"
        f"Results: {len(faces)}\n"
        f"Credit used: {credit_type}\n"
    )

    if not faces:
        await status_msg.edit_text(stats + "\n<i>No matches found. / Совпадений не найдено.</i>")
        return

    # Store results for potential unlock
    search_id = result.get("id_search") or str(message.message_id)
    pending_results[search_id] = result

    # For free search, show blurred results
    if is_free:
        await status_msg.edit_text(
            stats + "\n<i>First search is FREE but results are blurred.\n"
            "Pay to unlock each result.\n\n"
            "Первый поиск БЕСПЛАТНО, но результаты размыты.\n"
            "Оплатите, чтобы разблокировать.</i>"
        )

        for i, face in enumerate(faces[:5], 1):
            score = face.get("score", 0)
            base64_img = face.get("base64", "")

            caption = f"<b>#{i}</b> - Score: {score}%\n<i>Link hidden / Ссылка скрыта</i>"

            if base64_img and base64_img.startswith("data:image"):
                try:
                    img_data = base64_img.split(",", 1)[1]
                    img_bytes = base64.b64decode(img_data)
                    blurred = blur_image(img_bytes)
                    photo_file = BufferedInputFile(blurred, filename=f"blurred_{i}.jpg")
                    await message.answer_photo(
                        photo_file,
                        caption=caption,
                        reply_markup=get_unlock_keyboard(search_id, i - 1)
                    )
                except Exception as e:
                    logger.error(f"Blur error: {e}")
                    await message.answer(
                        caption,
                        reply_markup=get_unlock_keyboard(search_id, i - 1)
                    )
            else:
                await message.answer(
                    caption,
                    reply_markup=get_unlock_keyboard(search_id, i - 1)
                )
    else:
        # Paid search - show full results
        await status_msg.edit_text(stats + "\nSending results... / Отправка результатов...")

        for i, face in enumerate(faces[:5], 1):
            score = face.get("score", 0)
            url = face.get("url", "N/A")
            base64_img = face.get("base64", "")

            caption = f"<b>#{i}</b> - Score: {score}%\n{url}"

            if base64_img and base64_img.startswith("data:image"):
                try:
                    img_data = base64_img.split(",", 1)[1]
                    img_bytes = base64.b64decode(img_data)
                    photo_file = BufferedInputFile(img_bytes, filename=f"face_{i}.jpg")
                    await message.answer_photo(
                        photo_file,
                        caption=caption,
                        link_preview_options=LinkPreviewOptions(is_disabled=True)
                    )
                except Exception:
                    await message.answer(
                        caption,
                        link_preview_options=LinkPreviewOptions(is_disabled=True)
                    )
            else:
                await message.answer(
                    caption,
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )

        await status_msg.delete()


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
