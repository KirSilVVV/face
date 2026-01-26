import base64
from io import BytesIO

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, LinkPreviewOptions, BufferedInputFile
from aiogram.filters import CommandStart, Command
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from src.config import TELEGRAM_BOT_TOKEN
from src.facecheck_client import FaceCheckClient

router = Router()
facecheck = FaceCheckClient()


@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "<b>Face Search Bot</b>\n\n"
        "Send me a photo of a person and I'll try to find them online.\n\n"
        "Commands:\n"
        "/info - Check account credits\n\n"
        "<i>Note: Using demo mode (limited to ~100k faces)</i>"
    )


@router.message(Command("info"))
async def cmd_info(message: Message):
    info = await facecheck.get_info()
    if not info:
        await message.answer("Failed to get account info.")
        return

    await message.answer(
        f"<b>Account Info</b>\n\n"
        f"Indexed faces: {info.get('faces', 'N/A'):,}\n"
        f"Remaining credits: {info.get('remaining_credits', 'N/A')}\n"
        f"Can search: {'Yes' if info.get('has_credits_to_search') else 'No'}\n"
        f"Engine online: {'Yes' if info.get('is_online') else 'No'}"
    )


@router.message(F.photo)
async def handle_photo(message: Message, bot: Bot):
    status_msg = await message.answer("Uploading image...")

    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    image_bytes = await bot.download_file(file.file_path)

    async def on_progress(progress: int):
        await status_msg.edit_text(f"Searching... {progress}%")

    await status_msg.edit_text("Searching... 0%")
    result = await facecheck.find_face(
        image_bytes.read(),
        demo=True,
        on_progress=on_progress
    )

    if not result:
        await status_msg.edit_text("Search failed. Please try again.")
        return

    if result.get("error"):
        await status_msg.edit_text(f"Error: {result['error']}")
        return

    output = result.get("output", {})
    faces = output.get("items", [])

    # Build statistics
    stats = (
        f"<b>Search Complete</b>\n\n"
        f"Faces scanned: {output.get('searchedFaces', 'N/A'):,}\n"
        f"Time: {output.get('tookSeconds', 0):.1f}s\n"
        f"Max score: {output.get('max_score', 0)}%\n"
        f"Results: {len(faces)}\n"
    )

    if not faces:
        await status_msg.edit_text(stats + "\n<i>No matches found.</i>")
        return

    await status_msg.edit_text(stats + "\nSending results...")

    # Send top 5 results with images
    for i, face in enumerate(faces[:5], 1):
        score = face.get("score", 0)
        url = face.get("url", "N/A")
        base64_img = face.get("base64", "")

        caption = f"<b>#{i}</b> - Score: {score}%\n{url}"

        if base64_img and base64_img.startswith("data:image"):
            try:
                # Extract base64 data after the comma
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
    await message.answer("Please send a photo to search.")


def create_bot() -> tuple[Bot, Dispatcher]:
    bot = Bot(
        token=TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()
    dp.include_router(router)
    return bot, dp
