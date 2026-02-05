"""
Gift Card Payment System for Face Bot
"""

import logging
import secrets
import string
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple

from src import database as db

logger = logging.getLogger(__name__)


class GiftCardManager:
    """Manages gift card operations."""

    def __init__(self):
        self.code_length = 12
        self.code_format = string.ascii_uppercase + string.digits

    @staticmethod
    def generate_code(length: int = 12) -> str:
        """Generate a random gift card code."""
        chars = string.ascii_uppercase + string.digits
        return "".join(secrets.choice(chars) for _ in range(length))

    @staticmethod
    def format_code(code: str) -> str:
        """Format code to standard format (XXXX-XXXX-XXXX)."""
        code = code.upper().replace("-", "")
        if len(code) == 12:
            return f"{code[:4]}-{code[4:8]}-{code[8:]}"
        return code

    async def create_gift_cards(
        self,
        count: int,
        searches_amount: int,
        batch_id: str = None
    ) -> List[Dict]:
        """Create multiple gift cards."""
        created_cards = []
        
        for _ in range(count):
            code = self.generate_code()
            card_data = {
                "code": code,
                "code_formatted": self.format_code(code),
                "searches_amount": searches_amount,
                "batch_id": batch_id,
                "is_redeemed": False,
                "redeemed_by": None,
                "redeemed_at": None,
                "created_at": datetime.utcnow().isoformat()
            }

            result = await db.get_client().insert("gift_cards", card_data)
            if result:
                created_cards.append(result)
                logger.info(f"Created gift card: {code}")
            else:
                logger.error(f"Failed to create gift card: {code}")

        return created_cards

    async def validate_code(self, code: str) -> Optional[Dict]:
        """Validate and get gift card details."""
        code_normalized = code.upper().replace("-", "")

        if len(code_normalized) != 12:
            logger.warning(f"Invalid code format: {code}")
            return None

        try:
            result = await db.get_client().select(
                "gift_cards",
                {"code": code_normalized}
            )
            if result:
                return result[0]
            return None
        except Exception as e:
            logger.error(f"Error validating gift card: {e}")
            return None

    async def redeem_code(
        self,
        telegram_id: int,
        code: str
    ) -> Tuple[bool, str]:
        """Redeem a gift card code and add searches to user."""
        card = await self.validate_code(code)

        if not card:
            return False, "Code not found"

        if card.get("is_redeemed"):
            redeemed_at = card.get("redeemed_at")
            return False, f"Card already redeemed: {redeemed_at}"

        searches_amount = card.get("searches_amount", 0)
        success = await db.add_paid_searches(telegram_id, searches_amount)

        if not success:
            return False, "Error adding searches"

        client = db.get_client()
        await client.update(
            "gift_cards",
            {"code": card["code"]},
            {
                "is_redeemed": True,
                "redeemed_by": telegram_id,
                "redeemed_at": datetime.utcnow().isoformat()
            }
        )

        redemption_data = {
            "telegram_id": telegram_id,
            "gift_card_id": card.get("id"),
            "searches_amount": searches_amount,
            "code": card["code"],
            "redeemed_at": datetime.utcnow().isoformat()
        }
        await client.insert("gift_card_redemptions", redemption_data)

        logger.info(f"Gift card redeemed by user {telegram_id}")

        return True, f"Gift card activated: +{searches_amount} searches!"

    async def get_user_redemptions(self, telegram_id: int) -> List[Dict]:
        """Get user's redemption history."""
        try:
            result = await db.get_client().select(
                "gift_card_redemptions",
                {"telegram_id": telegram_id}
            )
            return result if result else []
        except Exception as e:
            logger.error(f"Error getting user redemptions: {e}")
            return []

    async def get_redemption_stats(self) -> Dict:
        """Get overall redemption statistics."""
        client = db.get_client()
        
        try:
            cards = await client.select("gift_cards")
            total_cards = len(cards) if cards else 0
            redeemed_cards = len([c for c in cards if c.get("is_redeemed")]) if cards else 0
            unredeemed_cards = total_cards - redeemed_cards
            
            total_searches = sum(c.get("searches_amount", 0) for c in cards) if cards else 0
            redeemed_searches = sum(
                c.get("searches_amount", 0)
                for c in cards
                if c.get("is_redeemed")
            ) if cards else 0

            redemptions = await client.select("gift_card_redemptions")
            total_redemptions = len(redemptions) if redemptions else 0

            unique_users = set()
            if redemptions:
                for r in redemptions:
                    unique_users.add(r.get("telegram_id"))

            return {
                "total_cards": total_cards,
                "redeemed_cards": redeemed_cards,
                "unredeemed_cards": unredeemed_cards,
                "total_searches": total_searches,
                "redeemed_searches": redeemed_searches,
                "unredeemed_searches": total_searches - redeemed_searches,
                "total_redemptions": total_redemptions,
                "unique_users": len(unique_users),
            }
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {}

    @staticmethod
    def format_stats(stats: Dict) -> str:
        """Format statistics for display."""
        return (
            f"Gift Card Stats:\n"
            f"Total cards: {stats.get('total_cards', 0)}\n"
            f"Redeemed: {stats.get('redeemed_cards', 0)}\n"
            f"Unredeemed: {stats.get('unredeemed_cards', 0)}"
        )

    async def get_user_stats(self, telegram_id: int) -> str:
        """Get formatted user redemption statistics."""
        try:
            redemptions = await self.get_user_redemptions(telegram_id)
            
            if not redemptions:
                return "No gift cards redeemed yet"

            total_searches = sum(r.get("searches_amount", 0) for r in redemptions)
            return f"Total searches from gift cards: {total_searches}"

        except Exception as e:
            logger.error(f"Error getting user stats: {e}")
            return "Error getting statistics"


gift_card_manager = GiftCardManager()

