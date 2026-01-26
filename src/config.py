import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
FACECHECK_API_KEY = os.getenv("FACECHECK_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

FACECHECK_BASE_URL = "https://facecheck.id/api"

# Pricing in Telegram Stars (TEST: 1 star each, change back later)
PRICING = {
    1: 1,      # 1 search = 1 star (TEST)
    5: 5,      # 5 searches = 5 stars (TEST)
    10: 10,    # 10 searches = 10 stars (TEST)
}

# Unlock single result cost (TEST: 1 star, change back later)
UNLOCK_COST_STARS = 1
