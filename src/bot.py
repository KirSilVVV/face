from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message
from aiogram.filters import CommandStart
from aiogram.enums import ParseMode

from src.config import TELEGRAM_BOT_TOKEN
from src.facecheck_client import FaceCheckClient

router = Router()
facecheck = FaceCheckClient()


@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "Face Search Bot\n\n"
        "Send me a photo of a person and I'll try to find them online.\n\n"
        "Note: Using demo mode (limited results)."
    )


@router.message(F.photo)
async def handle_photo(message: Message, bot: Bot):
    await message.answer("Processing image... This may take a moment.")

    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    image_bytes = await bot.download_file(file.file_path)

    result = await facecheck.find_face(image_bytes.read(), demo=True)

    if not result:
        await message.answer("Search failed. Please try again.")
        return

    if result.get("error"):
        await message.answer(f"Error: {result['error']}")
        return

    faces = result.get("output", {}).get("items", [])

    if not faces:
        await message.answer("No matches found.")
        return

    response_lines = ["Found matches:\n"]
    for i, face in enumerate(faces[:5], 1):
        score = face.get("score", 0)
        url = face.get("url", "N/A")
        response_lines.append(f"{i}. Score: {score}%\n   {url}\n")

    await message.answer("\n".join(response_lines), disable_web_page_preview=True)


@router.message()
async def handle_other(message: Message):
    await message.answer("Please send a photo to search.")


def create_bot() -> tuple[Bot, Dispatcher]:
    bot = Bot(token=TELEGRAM_BOT_TOKEN, parse_mode=ParseMode.HTML)
    dp = Dispatcher()
    dp.include_router(router)
    return bot, dp
