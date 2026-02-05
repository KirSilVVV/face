"""
Gift Card Handlers for Aiogram Bot
"""

from aiogram import F, Router
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import logging

from src.gift_card_payment import gift_card_manager
from src.config import ADMIN_CHAT_ID
from src import database as db

logger = logging.getLogger(__name__)


class GiftCardStates(StatesGroup):
    """FSM states for gift card processing."""
    waiting_for_code = State()


async def cmd_redeem(message: Message, state: FSMContext):
    """Start gift card redemption process."""
    await state.set_state(GiftCardStates.waiting_for_code)
    await message.answer(
        "Enter gift card code:\n\n"
        "Code format: XXXX-XXXX-XXXX or XXXXXXXXXXXX\n\n"
        "/cancel - Cancel"
    )


async def process_gift_code(message: Message, state: FSMContext):
    """Process gift card code entered by user."""
    code = message.text.strip()
    
    if not code or len(code.replace("-", "")) != 12:
        await message.answer(
            "Invalid code format.\n\n"
            "Code must contain 12 characters.\n"
            "Try again or /cancel"
        )
        return
    
    success, msg = await gift_card_manager.redeem_code(message.from_user.id, code)
    
    await message.answer(msg)
    
    if success:
        await db.track_event(
            message.from_user.id,
            "gift_card_redeemed",
            {"code": code}
        )
    
    await state.clear()


async def cmd_cancel(message: Message, state: FSMContext):
    """Cancel current operation."""
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("Nothing to cancel.")
        return
    
    await state.clear()
    await message.answer("Operation cancelled.")


async def cmd_giftcards_stats(message: Message):
    """Show gift card statistics (admin only)."""
    if str(message.from_user.id) != str(ADMIN_CHAT_ID):
        await message.answer("Access denied.")
        return
    
    stats = await gift_card_manager.get_redemption_stats()
    stats_text = gift_card_manager.format_stats(stats)
    
    await message.answer(stats_text)


async def cmd_myredemptions(message: Message):
    """Show users redemption history."""
    stats_text = await gift_card_manager.get_user_stats(message.from_user.id)
    await message.answer(stats_text)


async def callback_redeem(query, state: FSMContext):
    """Handle redeem button callback."""
    await query.answer()
    await state.set_state(GiftCardStates.waiting_for_code)
    await query.message.answer(
        "🎁 <b>Активировать подарочную карту</b>\n\n"
        "Отправьте код:\n\n"
        "Формат: XXXX-XXXX-XXXX\n\n"
        "/cancel - Отмена"
    )


def register_gift_card_handlers(router: Router):
    """Register all gift card handlers to the router."""
    router.message.register(cmd_redeem, Command("redeem"))
    router.callback_query.register(callback_redeem, F.data == "cmd_redeem")
    router.message.register(process_gift_code, GiftCardStates.waiting_for_code)
    router.message.register(cmd_cancel, Command("cancel"))
    router.message.register(cmd_giftcards_stats, Command("giftcards"))
    router.message.register(cmd_myredemptions, Command("myredemptions"))

