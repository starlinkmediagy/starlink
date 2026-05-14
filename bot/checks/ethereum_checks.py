"""
Ethereum safety checks:
  - Mint Function: fetches contract ABI from Etherscan and looks for a mint() function.
    Unverified contracts are flagged UNKNOWN rather than PASS.
  - Holder Concentration: uses Ethplorer free API (no key) for top-holder share.
  - Liquidity Lock: checks LP token top holders via Ethplorer; flags if none of the
    top holders is a known locker / burn address.
"""

import asyncio
import logging

import aiohttp

from .base import CheckResult, CheckStatus

logger = logging.getLogger(__name__)

ETHPLORER_API = "https://api.ethplorer.io"

# Well-known LP locker and burn addresses (lowercase)
KNOWN_LOCKERS: frozenset[str] = frozenset(
    {
        "0x663a5c229c09b049e36dcc11a9b0d4a8eb9db214",  # Unicrypt v2
        "0xe2fe530c047f2d85298b07d9333c05737f1435fb",  # Team Finance
        "0x71b5759d73262fbb223956913ecf4ecc51057641",  # Pink Lock
        "0x407993575c91ce7643a4d4ccacc9a98c36ee1bbe",  # Mudra
        "0x0000000000000000000000000000000000000000",  # zero address
        "0x000000000000000000000000000000000000dead",  # dead address
    }
)


async def check_mint_function(
    session: aiohttp.ClientSession,
    etherscan_api_key: str,
    contract_address: str,
) -> CheckResult:
    url = (
        "https://api.etherscan.io/api"
        f"?module=contract&action=getabi"
        f"&address={contract_address}"
        f"&apikey={etherscan_api_key}"
    )
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            data = await resp.json()

        if data.get("status") != "1":
            return CheckResult(
                "Mint Function", CheckStatus.UNKNOWN, "Contract ABI not verified on Etherscan"
            )

        abi_lower = data["result"].lower()
        has_mint = '"name":"mint"' in abi_lower or '"name": "mint"' in abi_lower
        if has_mint:
            return CheckResult("Mint Function", CheckStatus.FAIL, "mint() found in verified ABI")
        return CheckResult("Mint Function", CheckStatus.PASS, "No mint() in verified ABI")
    except Exception as exc:
        logger.debug("Mint function check error for %s: %s", contract_address, exc)
        return CheckResult("Mint Function", CheckStatus.UNKNOWN, str(exc)[:80])


async def check_holder_concentration(
    session: aiohttp.ClientSession,
    contract_address: str,
    max_pct: float,
) -> CheckResult:
    url = (
        f"{ETHPLORER_API}/getTopTokenHolders/{contract_address}"
        "?apiKey=freekey&limit=10"
    )
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            data = await resp.json()

        holders = data.get("holders", [])
        if not holders:
            return CheckResult(
                "Holder Concentration", CheckStatus.UNKNOWN, "No holder data yet"
            )

        # Ethplorer returns share as a percentage value (e.g. 25.3 means 25.3%)
        top_pct = float(holders[0].get("share", 0))
        if top_pct <= max_pct:
            return CheckResult(
                "Holder Concentration",
                CheckStatus.PASS,
                f"Top holder: {top_pct:.1f}% (max {max_pct:.0f}%)",
            )
        return CheckResult(
            "Holder Concentration",
            CheckStatus.FAIL,
            f"Top holder: {top_pct:.1f}% exceeds {max_pct:.0f}% threshold",
        )
    except Exception as exc:
        logger.debug("Holder concentration check error for %s: %s", contract_address, exc)
        return CheckResult("Holder Concentration", CheckStatus.UNKNOWN, str(exc)[:80])


async def check_liquidity_lock(
    session: aiohttp.ClientSession,
    pair_address: str,
) -> CheckResult:
    url = (
        f"{ETHPLORER_API}/getTopTokenHolders/{pair_address}"
        "?apiKey=freekey&limit=10"
    )
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            data = await resp.json()

        holders = data.get("holders", [])
        if not holders:
            return CheckResult("Liquidity Lock", CheckStatus.UNKNOWN, "No LP holder data yet")

        # Share values are percentages; sum locked shares directly
        locked_pct = sum(
            float(h.get("share", 0))
            for h in holders
            if h.get("address", "").lower() in KNOWN_LOCKERS
        )

        if locked_pct >= 80:
            return CheckResult(
                "Liquidity Lock", CheckStatus.PASS, f"~{locked_pct:.0f}% LP locked/burned"
            )
        if locked_pct > 0:
            return CheckResult(
                "Liquidity Lock",
                CheckStatus.FAIL,
                f"Only ~{locked_pct:.0f}% LP at known lockers",
            )
        return CheckResult(
            "Liquidity Lock", CheckStatus.FAIL, "No LP at any known locker address"
        )
    except Exception as exc:
        logger.debug("Liquidity lock check error for %s: %s", pair_address, exc)
        return CheckResult("Liquidity Lock", CheckStatus.UNKNOWN, str(exc)[:80])


async def run_ethereum_checks(
    etherscan_api_key: str,
    token_address: str,
    pair_address: str,
    max_holder_pct: float,
) -> list[CheckResult]:
    async with aiohttp.ClientSession() as session:
        results = await asyncio.gather(
            check_mint_function(session, etherscan_api_key, token_address),
            check_holder_concentration(session, token_address, max_holder_pct),
            check_liquidity_lock(session, pair_address),
        )
    return list(results)
