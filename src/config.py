import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
FACECHECK_API_KEY = os.getenv("FACECHECK_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

FACECHECK_BASE_URL = "https://facecheck.id/api"

# Paid search cost (after free trial)
SEARCH_COST_STARS = 3

# Unlock single result link cost (for free search results)
UNLOCK_COST_STARS = 2
