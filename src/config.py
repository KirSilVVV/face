import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
FACECHECK_API_KEY = os.getenv("FACECHECK_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

FACECHECK_BASE_URL = "https://facecheck.id/api"

# Pricing in Telegram Stars
PRICING = {
    1: 149,    # 1 search = 149 stars
    5: 649,    # 5 searches = 649 stars
    10: 1199,  # 10 searches = 1199 stars
}

# Unlock single result cost
UNLOCK_COST_STARS = 149
