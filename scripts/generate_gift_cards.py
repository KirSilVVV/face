#!/usr/bin/env python3
"""
Gift Card Generator for Face Bot

Usage:
    python scripts/generate_gift_cards.py batch 100 5      # Create 100 codes x 5 searches
    python scripts/generate_gift_cards.py stats             # Show statistics
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.gift_card_payment import gift_card_manager
from src import database as db


async def batch_create(count: int, searches: int):
    """Create batch of gift cards."""
    print(f"Creating {count} gift cards with {searches} searches each...\n")

    cards = await gift_card_manager.create_gift_cards(
        count=count,
        searches_amount=searches
    )

    if not cards:
        print("❌ Error: No cards were created")
        return

    for i, card in enumerate(cards, 1):
        code = card.get('code', 'UNKNOWN')
        print(f"✓ {code}")

        if i % 10 == 0:
            print(f"  Progress: {i}/{count}")

    print(f"\n✅ Successfully created {len(cards)} gift cards!")


async def show_stats():
    """Show gift card statistics."""
    stats = await gift_card_manager.get_redemption_stats()

    print("\n📊 Gift Card Statistics:")
    print(f"  Total codes: {stats.get('total_codes', 0)}")
    print(f"  Used: {stats.get('used_codes', 0)}")
    print(f"  Unused: {stats.get('unused_codes', 0)}")
    print(f"  Activation rate: {stats.get('activation_rate', 0):.1f}%")
    print(f"  Remaining searches: {stats.get('remaining_searches', 0)}")
    print()


async def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    command = sys.argv[1]

    if command == "batch":
        if len(sys.argv) < 4:
            print("Usage: batch <count> <searches>")
            print("Example: batch 100 5")
            return

        count = int(sys.argv[2])
        searches = int(sys.argv[3])
        await batch_create(count, searches)

    elif command == "stats":
        await show_stats()

    else:
        print(f"Unknown command: {command}")
        print(__doc__)


if __name__ == "__main__":
    asyncio.run(main())
