#!/usr/bin/env python3
"""
Gift Card Generation Utility

Usage:
    python scripts/generate_gift_cards.py --count 100 --searches 5 --batch batch_001
    python scripts/generate_gift_cards.py --import cards.csv
    python scripts/generate_gift_cards.py --stats
"""

import asyncio
import csv
import sys
import argparse
from datetime import datetime
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.gift_card_payment import gift_card_manager
from src import database as db


async def generate_cards(count: int, searches: int, batch_id: str = None):
    """Generate and save gift cards."""
    print(f"Generating {count} gift cards with {searches} searches each...")
    
    if batch_id is None:
        batch_id = f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    cards = await gift_card_manager.create_gift_cards(
        count=count,
        searches_amount=searches,
        batch_id=batch_id
    )
    
    if not cards:
        print("Error: No cards were created")
        return
    
    # Save to CSV
    output_file = f"gift_cards_{batch_id}.csv"
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['Code', 'Formatted', 'Searches', 'Batch', 'Created'])
        writer.writeheader()
        
        for card in cards:
            writer.writerow({
                'Code': card.get('code'),
                'Formatted': card.get('code_formatted'),
                'Searches': card.get('searches_amount'),
                'Batch': card.get('batch_id'),
                'Created': card.get('created_at')
            })
    
    print(f"Successfully created {len(cards)} cards")
    print(f"Saved to: {output_file}")
    print(f"Batch ID: {batch_id}")


async def import_cards(csv_file: str, searches: int, batch_id: str = None):
    """Import gift cards from CSV file."""
    if not Path(csv_file).exists():
        print(f"Error: File {csv_file} not found")
        return
    
    if batch_id is None:
        batch_id = f"import_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    cards = []
    client = db.get_client()
    
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = row.get('Code') or row.get('code')
            
            if not code:
                print("Warning: Skipping row without code")
                continue
            
            card_data = {
                "code": code.upper(),
                "code_formatted": gift_card_manager.format_code(code),
                "searches_amount": searches,
                "batch_id": batch_id,
                "is_redeemed": False,
                "redeemed_by": None,
                "redeemed_at": None,
                "created_at": datetime.utcnow().isoformat()
            }
            
            result = await client.insert("gift_cards", card_data)
            if result:
                cards.append(result)
    
    print(f"Imported {len(cards)} gift cards from {csv_file}")
    print(f"Batch ID: {batch_id}")


async def show_stats():
    """Display gift card statistics."""
    stats = await gift_card_manager.get_redemption_stats()
    
    if not stats:
        print("No statistics available")
        return
    
    print("\n=== GIFT CARD STATISTICS ===\n")
    print(f"Total Cards Created: {stats.get('total_cards', 0)}")
    print(f"Cards Redeemed: {stats.get('redeemed_cards', 0)}")
    print(f"Cards Unredeemed: {stats.get('unredeemed_cards', 0)}")
    print(f"\nTotal Searches Distributed: {stats.get('total_searches', 0)}")
    print(f"Searches Redeemed: {stats.get('redeemed_searches', 0)}")
    print(f"Searches Remaining: {stats.get('unredeemed_searches', 0)}")
    print(f"\nTotal Redemptions: {stats.get('total_redemptions', 0)}")
    print(f"Unique Users: {stats.get('unique_users', 0)}")
    print()


async def main():
    parser = argparse.ArgumentParser(
        description='Gift Card Management Utility'
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # Generate command
    gen_parser = subparsers.add_parser('generate', help='Generate gift cards')
    gen_parser.add_argument('--count', type=int, required=True, help='Number of cards')
    gen_parser.add_argument('--searches', type=int, required=True, help='Searches per card')
    gen_parser.add_argument('--batch', help='Batch ID (optional)')
    
    # Import command
    imp_parser = subparsers.add_parser('import', help='Import gift cards from CSV')
    imp_parser.add_argument('file', help='CSV file path')
    imp_parser.add_argument('--searches', type=int, required=True, help='Searches per card')
    imp_parser.add_argument('--batch', help='Batch ID (optional)')
    
    # Stats command
    subparsers.add_parser('stats', help='Show statistics')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    if args.command == 'generate':
        await generate_cards(args.count, args.searches, args.batch)
    elif args.command == 'import':
        await import_cards(args.file, args.searches, args.batch)
    elif args.command == 'stats':
        await show_stats()


if __name__ == '__main__':
    asyncio.run(main())
