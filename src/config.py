import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
FACECHECK_API_KEY = os.getenv("FACECHECK_API_KEY")

FACECHECK_BASE_URL = "https://facecheck.id/api"
