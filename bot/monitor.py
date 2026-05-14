"""
Polls GeckoTerminal's /new_pools endpoint for Solana and Ethereum every N seconds.
For each pool not yet seen:
  1. Skip if liquidity < MIN_LIQUIDITY_USD (dust pools / honeypots with no liquidity).
  2. Run chain-specific safety checks concurrently.
  3. Call on_coin(report) only when no check returns FAIL.

GeckoTerminal free tier: 30 req/min, no API key required.
"""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

import aiohttp

from checks.base import CoinReport
from checks.ethereum_checks import run_ethereum_checks
from checks.solana_checks import run_solana_checks
from config import Config

logger = logging.getLogger(__name__)

GECKOTERMINAL = "https://api.geckoterminal.com/api/v2"
GT_HEADERS = {"Accept": "application/json;version=20230302"}

# GeckoTerminal network slugs
CHAIN_TO_NETWORK = {
    "solana": "solana",
    "ethereum": "eth",
}

OnCoinCallback = Callable[[CoinReport], Coroutine[Any, Any, None]]


class CoinMonitor:
    def __init__(self, config: Config) -> None:
        self.config = config
        # Tracks seen GeckoTerminal pool IDs and token addresses to avoid duplicates
        self._seen: set[str] = set()

    async def run(self, on_coin: OnCoinCallback) -> None:
        logger.info(
            "Bot started | chains: solana(%ds), ethereum(%ds) | "
            "min_liquidity=$%.0f | max_top_holder=%.0f%%",
            self.config.solana_poll_interval,
            self.config.eth_poll_interval,
            self.config.min_liquidity_usd,
            self.config.max_top_holder_pct,
        )
        await asyncio.gather(
            self._poll_loop("solana", on_coin, self.config.solana_poll_interval),
            self._poll_loop("ethereum", on_coin, self.config.eth_poll_interval),
        )

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    async def _poll_loop(
        self, chain: str, on_coin: OnCoinCallback, interval: int
    ) -> None:
        while True:
            try:
                await self._fetch_new_pools(chain, on_coin)
            except Exception as exc:
                logger.error("%s poll error: %s", chain, exc)
            await asyncio.sleep(interval)

    async def _fetch_new_pools(self, chain: str, on_coin: OnCoinCallback) -> None:
        network = CHAIN_TO_NETWORK[chain]
        url = f"{GECKOTERMINAL}/networks/{network}/new_pools?include=base_token"

        async with aiohttp.ClientSession(headers=GT_HEADERS) as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    logger.warning("GeckoTerminal %s returned HTTP %s", chain, resp.status)
                    return
                payload = await resp.json()

        # Build a lookup from GeckoTerminal token ID → token attributes
        included_tokens: dict[str, dict] = {
            item["id"]: item
            for item in payload.get("included", [])
            if item.get("type") == "token"
        }

        for pool in payload.get("data", []):
            pool_id: str = pool.get("id", "")
            if pool_id in self._seen:
                continue

            attrs = pool.get("attributes", {})

            # Skip pools below minimum liquidity threshold early
            try:
                liquidity = float(attrs.get("reserve_in_usd") or 0)
            except (TypeError, ValueError):
                liquidity = 0.0

            if liquidity < self.config.min_liquidity_usd:
                self._seen.add(pool_id)
                continue

            # Resolve base token info from the `included` sideload
            base_ref = pool.get("relationships", {}).get("base_token", {}).get("data", {})
            token_id = base_ref.get("id", "")
            token_info = included_tokens.get(token_id, {})
            token_attrs = token_info.get("attributes", {})

            token_address: str = token_attrs.get("address", "")
            if not token_address or token_address in self._seen:
                self._seen.add(pool_id)
                continue

            self._seen.add(pool_id)
            self._seen.add(token_address)

            pair_address: str = attrs.get("address", "")
            name: str = token_attrs.get("name") or "Unknown"
            symbol: str = token_attrs.get("symbol") or "???"

            logger.info(
                "New %s pool: %s (%s…) liquidity=$%.0f",
                chain,
                symbol,
                token_address[:8],
                liquidity,
            )

            # Dispatch checks as a background task so polling is never blocked
            asyncio.create_task(
                self._check_and_notify(
                    chain, name, symbol, token_address, pair_address, liquidity, on_coin
                )
            )

    async def _check_and_notify(
        self,
        chain: str,
        name: str,
        symbol: str,
        token_address: str,
        pair_address: str,
        liquidity: float,
        on_coin: OnCoinCallback,
    ) -> None:
        try:
            if chain == "solana":
                checks = await run_solana_checks(
                    self.config.solana_rpc_url,
                    token_address,
                    self.config.max_top_holder_pct,
                )
            else:
                checks = await run_ethereum_checks(
                    self.config.etherscan_api_key,
                    token_address,
                    pair_address,
                    self.config.max_top_holder_pct,
                )

            report = CoinReport(
                chain=chain,
                name=name,
                symbol=symbol,
                address=token_address,
                pair_address=pair_address,
                checks=checks,
                extra={"liquidity_usd": liquidity},
            )

            if report.passed:
                logger.info("PASSED %s: %s on %s", report.score, symbol, chain)
                await on_coin(report)
            else:
                failed_names = [c.name for c in report.failed_checks]
                logger.info("FAILED %s [%s]: %s on %s", report.score, failed_names, symbol, chain)

        except Exception as exc:
            logger.error("Check error for %s (%s): %s", symbol, token_address, exc)
