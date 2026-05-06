"""
Magari Scout — unified runner.

Usage:
  python scripts/run_scout.py                                    # BE Forward only (no accounts set)
  python scripts/run_scout.py --accounts dealer1,dealer2         # BE Forward + Instagram
  python scripts/run_scout.py --makes Toyota,Nissan,BMW          # specific makes from BE Forward
  python scripts/run_scout.py --max-posts 50 --max-per-make 30
"""
import asyncio
import argparse
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

from services.magari_scout import run_scout, TARGET_ACCOUNTS


async def main():
    parser = argparse.ArgumentParser(description="Magari Scout — BE Forward + Instagram scraper")
    parser.add_argument("--accounts",      type=str, help="Comma-separated Instagram usernames")
    parser.add_argument("--makes",         type=str, help="Comma-separated car makes for BE Forward (default: Toyota,Nissan,Honda,Mitsubishi,Subaru,Mazda)")
    parser.add_argument("--max-posts",     type=int, default=30,  help="Max Instagram posts per account")
    parser.add_argument("--max-per-make",  type=int, default=20,  help="Max BE Forward listings per make")
    args = parser.parse_args()

    accounts = args.accounts.split(",") if args.accounts else TARGET_ACCOUNTS
    makes    = args.makes.split(",")    if args.makes    else None

    print(f"\n🚗 Magari Scout")
    print(f"   BE Forward makes : {', '.join(makes) if makes else 'Toyota, Nissan, Honda, Mitsubishi, Subaru, Mazda'}")
    print(f"   Instagram accounts: {', '.join(f'@{a}' for a in accounts) if accounts else 'none configured'}")
    print(f"   Max/make: {args.max_per_make} | Max/account: {args.max_posts}\n")

    saved = await run_scout(
        accounts=accounts or None,
        makes=makes,
        max_posts_instagram=args.max_posts,
        max_per_make_beforward=args.max_per_make,
    )
    print(f"\n✅ Done — {saved} listings saved to Supabase")


if __name__ == "__main__":
    asyncio.run(main())
