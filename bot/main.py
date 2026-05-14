"""
Blockchain Coin Detection Bot
==============================
Monitors new Solana and Ethereum token launches via GeckoTerminal.
Runs three safety checks per coin:
  - Mint authority revoked
  - Top-holder concentration below threshold
  - Liquidity is locked

Sends a Telegram alert only when a coin passes all checks (no FAILs).

Usage:
    cp .env.example .env   # fill in your API keys
    pip install -r requirements.txt
    python main.py
"""

import asyncio
import logging
import sys

from config import Config
from monitor import CoinMonitor
from checks.base import CoinReport
from notifier.telegram import TelegramNotifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


async def main() -> None:
    try:
        config = Config.from_env()
    except EnvironmentError as exc:
        logger.error("Configuration error: %s", exc)
        sys.exit(1)

    notifier = TelegramNotifier(config.telegram_bot_token, config.telegram_chat_id)

    async def on_coin(report: CoinReport) -> None:
        await notifier.send_coin_report(report)

    monitor = CoinMonitor(config)
    await monitor.run(on_coin)


if __name__ == "__main__":
    asyncio.run(main())
