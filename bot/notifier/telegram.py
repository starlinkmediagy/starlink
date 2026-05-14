import logging

import aiohttp

from checks.base import CheckStatus, CoinReport

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"

_CHAIN_EXPLORER = {
    "solana": "https://solscan.io/token/{}",
    "ethereum": "https://etherscan.io/token/{}",
}

_CHAIN_DEX = {
    "solana": "https://raydium.io/swap/?outputCurrency={}",
    "ethereum": "https://app.uniswap.org/#/swap?outputCurrency={}",
}

_CHAIN_DEXSCREENER = {
    "solana": "https://dexscreener.com/solana/{}",
    "ethereum": "https://dexscreener.com/ethereum/{}",
}

_CHAIN_EMOJI = {
    "solana": "☀️",
    "ethereum": "💎",
}


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id

    async def send_coin_report(self, report: CoinReport) -> None:
        message = _format_report(report)
        await self._post(message)

    async def _post(self, text: str) -> None:
        url = f"{TELEGRAM_API}/bot{self._bot_token}/sendMessage"
        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, json=payload, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.error("Telegram error %s: %s", resp.status, body[:200])
        except Exception as exc:
            logger.error("Failed to send Telegram message: %s", exc)


def _format_report(report: CoinReport) -> str:
    chain_name = report.chain.capitalize()
    emoji = _CHAIN_EMOJI.get(report.chain, "🔗")

    explorer = _CHAIN_EXPLORER[report.chain].format(report.address)
    dex = _CHAIN_DEX[report.chain].format(report.address)
    dexscreener = _CHAIN_DEXSCREENER[report.chain].format(report.pair_address)

    liquidity = report.extra.get("liquidity_usd", 0)
    liquidity_str = f"${liquidity:,.0f}" if liquidity else "N/A"

    addr = report.address
    addr_short = f"{addr[:6]}...{addr[-4:]}"

    checks_lines = "\n".join(
        f"  {c.status.value} *{c.name}*: {c.detail}" for c in report.checks
    )

    # Warn if any checks were UNKNOWN so user knows the data was incomplete
    unknowns = [c.name for c in report.checks if c.status == CheckStatus.UNKNOWN]
    caveat = ""
    if unknowns:
        caveat = f"\n⚠️ _Could not verify: {', '.join(unknowns)}_"

    return (
        f"{emoji} *{chain_name} — New Coin Passed Checks* {emoji}\n"
        f"\n"
        f"*{report.name}* (${report.symbol})\n"
        f"`{addr_short}`\n"
        f"Liquidity: {liquidity_str} | Score: {report.score}\n"
        f"\n"
        f"*Safety Checks:*\n{checks_lines}"
        f"{caveat}\n"
        f"\n"
        f"[Explorer]({explorer})  |  [Swap]({dex})  |  [Chart]({dexscreener})"
    )
