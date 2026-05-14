"""
Solana safety checks:
  - Mint Authority: parses raw SPL token mint account (getAccountInfo) to see if
    mintAuthorityOption == 0 (revoked). Active mint authority means devs can print
    unlimited tokens.
  - Holder Concentration: top holder % via getTokenLargestAccounts + getTokenSupply.
  - Liquidity Lock: delegated to rugcheck.xyz free API which indexes Raydium LP locks.
"""

import asyncio
import base64
import logging
import struct

import aiohttp

from .base import CheckResult, CheckStatus

logger = logging.getLogger(__name__)

RUGCHECK_API = "https://api.rugcheck.xyz/v1"

# Risk names returned by rugcheck that indicate unlocked LP
_LP_RISK_NAMES = {"lp not locked", "unlocked lp", "large lp unlock", "lp not burned"}


async def check_mint_authority(
    session: aiohttp.ClientSession, rpc_url: str, mint: str
) -> CheckResult:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getAccountInfo",
        "params": [mint, {"encoding": "base64"}],
    }
    try:
        async with session.post(
            rpc_url, json=payload, timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            data = await resp.json()

        value = data.get("result", {}).get("value")
        if not value:
            return CheckResult("Mint Authority", CheckStatus.UNKNOWN, "Account not found")

        raw = base64.b64decode(value["data"][0])
        if len(raw) < 4:
            return CheckResult("Mint Authority", CheckStatus.UNKNOWN, "Unexpected account size")

        # SPL Token Mint layout: first 4 bytes are COption<Pubkey>
        # 0 = None (revoked), 1 = Some (active)
        mint_authority_option = struct.unpack_from("<I", raw, 0)[0]
        if mint_authority_option == 0:
            return CheckResult("Mint Authority", CheckStatus.PASS, "Revoked")

        authority_b58 = _b58encode(raw[4:36])
        return CheckResult(
            "Mint Authority", CheckStatus.FAIL, f"Active: {authority_b58[:12]}..."
        )
    except Exception as exc:
        logger.debug("Mint authority check error for %s: %s", mint, exc)
        return CheckResult("Mint Authority", CheckStatus.UNKNOWN, str(exc)[:80])


async def check_holder_concentration(
    session: aiohttp.ClientSession,
    rpc_url: str,
    mint: str,
    max_pct: float,
) -> CheckResult:
    try:
        async with session.post(
            rpc_url,
            json={"jsonrpc": "2.0", "id": 1, "method": "getTokenLargestAccounts", "params": [mint]},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            accounts_data = await resp.json()

        async with session.post(
            rpc_url,
            json={"jsonrpc": "2.0", "id": 2, "method": "getTokenSupply", "params": [mint]},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            supply_data = await resp.json()

        largest = accounts_data.get("result", {}).get("value", [])
        total_supply = int(
            supply_data.get("result", {}).get("value", {}).get("amount", "0") or "0"
        )

        if not largest or total_supply == 0:
            return CheckResult("Holder Concentration", CheckStatus.UNKNOWN, "No supply data")

        top_amount = int(largest[0]["amount"])
        top_pct = (top_amount / total_supply) * 100

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
        logger.debug("Holder concentration check error for %s: %s", mint, exc)
        return CheckResult("Holder Concentration", CheckStatus.UNKNOWN, str(exc)[:80])


async def check_liquidity_lock(
    session: aiohttp.ClientSession, mint: str
) -> CheckResult:
    try:
        url = f"{RUGCHECK_API}/tokens/{mint}/report/summary"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status == 404:
                return CheckResult(
                    "Liquidity Lock", CheckStatus.UNKNOWN, "Not yet indexed by rugcheck"
                )
            if resp.status != 200:
                return CheckResult(
                    "Liquidity Lock", CheckStatus.UNKNOWN, f"rugcheck HTTP {resp.status}"
                )
            data = await resp.json()

        risks = data.get("risks", [])
        lp_risks = [r for r in risks if r.get("name", "").lower() in _LP_RISK_NAMES]

        if lp_risks:
            return CheckResult(
                "Liquidity Lock", CheckStatus.FAIL, lp_risks[0].get("name", "LP issue")
            )

        score = data.get("score_normalised", data.get("score", "?"))
        return CheckResult(
            "Liquidity Lock", CheckStatus.PASS, f"No LP unlock risks (rugcheck score: {score})"
        )
    except Exception as exc:
        logger.debug("Liquidity lock check error for %s: %s", mint, exc)
        return CheckResult("Liquidity Lock", CheckStatus.UNKNOWN, str(exc)[:80])


async def run_solana_checks(
    rpc_url: str, mint: str, max_holder_pct: float
) -> list[CheckResult]:
    async with aiohttp.ClientSession() as session:
        results = await asyncio.gather(
            check_mint_authority(session, rpc_url, mint),
            check_holder_concentration(session, rpc_url, mint, max_holder_pct),
            check_liquidity_lock(session, mint),
        )
    return list(results)


def _b58encode(data: bytes) -> str:
    ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    n = int.from_bytes(data, "big")
    encoded: list[str] = []
    while n > 0:
        n, rem = divmod(n, 58)
        encoded.append(ALPHABET[rem])
    for byte in data:
        if byte != 0:
            break
        encoded.append(ALPHABET[0])
    return "".join(reversed(encoded))
