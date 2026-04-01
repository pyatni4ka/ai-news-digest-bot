from __future__ import annotations

import argparse
import asyncio
import json

from aiogram import Dispatcher

from digest_bot.bot.handlers import build_router
from digest_bot.config import load_settings
from digest_bot.scheduler import DigestScheduler
from digest_bot.service import DigestService


async def _run_bot() -> None:
    settings = load_settings()
    service = DigestService(settings)
    scheduler = DigestScheduler(service)
    dispatcher = Dispatcher()
    dispatcher.include_router(build_router(service))
    scheduler.start()
    try:
        await dispatcher.start_polling(service.bot)
    finally:
        await scheduler.shutdown()
        await service.close()


async def _auth_telegram() -> None:
    settings = load_settings()
    service = DigestService(settings)
    try:
        await service.telegram_collector.interactive_auth()
    finally:
        await service.close()


async def _export_telegram_session() -> None:
    settings = load_settings()
    service = DigestService(settings)
    try:
        print(await service.telegram_collector.export_session_string())
    finally:
        await service.close()


async def _sync_only() -> None:
    settings = load_settings()
    service = DigestService(settings)
    try:
        stats = await service.sync_sources()
        for key, value in stats.items():
            print(f"{key}: {value}")
    finally:
        await service.close()


async def _check_llm() -> None:
    settings = load_settings()
    service = DigestService(settings)
    try:
        print(json.dumps(await service.llm_status(), ensure_ascii=False, indent=2))
    finally:
        await service.close()


async def _build_digest(slot: str, send: bool) -> None:
    settings = load_settings()
    service = DigestService(settings)
    try:
        digest_id = await service.build_digest(slot)
        print(f"digest_id={digest_id}")
        if send:
            await service.send_digest(digest_id)
    finally:
        await service.close()


async def _run_slot(slot: str) -> None:
    settings = load_settings()
    service = DigestService(settings)
    try:
        if slot == "monthly":
            await service.sync_sources(lookback_hours=24 * 31)
        elif slot == "weekly":
            await service.sync_sources(lookback_hours=24 * 8)
        elif slot == "today":
            await service.sync_sources(lookback_hours=30)
        elif slot == "morning":
            await service.sync_sources(lookback_hours=16)
        elif slot == "evening":
            await service.sync_sources(lookback_hours=12)
        else:
            await service.sync_sources()
        digest_id = await service.build_digest(slot)
        print(f"digest_id={digest_id}")
        await service.send_digest(digest_id)
    finally:
        await service.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="AI news digest bot")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("bot", help="Run the Telegram bot with scheduler")
    subparsers.add_parser("auth-telegram", help="Authorize the Telethon session")
    subparsers.add_parser(
        "export-telegram-session",
        help="Print Telethon StringSession for VPS/cloud deploys",
    )
    subparsers.add_parser("sync", help="Fetch sources and persist new items")
    subparsers.add_parser("check-llm", help="Validate LLM backend credentials and model availability")
    run_parser = subparsers.add_parser(
        "run-slot",
        help="Sync, build and send a digest for a single slot",
    )
    run_parser.add_argument(
        "--slot",
        choices=["morning", "evening", "manual", "monthly", "weekly", "today"],
        default="manual",
    )

    digest_parser = subparsers.add_parser("digest", help="Build a digest from stored items")
    digest_parser.add_argument(
        "--slot",
        choices=["morning", "evening", "manual", "monthly", "weekly", "today"],
        default="manual",
    )
    digest_parser.add_argument("--send", action="store_true")

    args = parser.parse_args()
    if args.command == "bot":
        asyncio.run(_run_bot())
        return
    if args.command == "auth-telegram":
        asyncio.run(_auth_telegram())
        return
    if args.command == "export-telegram-session":
        asyncio.run(_export_telegram_session())
        return
    if args.command == "sync":
        asyncio.run(_sync_only())
        return
    if args.command == "check-llm":
        asyncio.run(_check_llm())
        return
    if args.command == "run-slot":
        asyncio.run(_run_slot(args.slot))
        return
    if args.command == "digest":
        asyncio.run(_build_digest(args.slot, args.send))


if __name__ == "__main__":
    main()
