import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    telegram_bot_token: str
    telegram_chat_id: str
    helius_api_key: str
    etherscan_api_key: str
    max_top_holder_pct: float
    min_liquidity_usd: float
    solana_poll_interval: int
    eth_poll_interval: int

    @property
    def solana_rpc_url(self) -> str:
        return f"https://mainnet.helius-rpc.com/?api-key={self.helius_api_key}"

    @classmethod
    def from_env(cls) -> "Config":
        required = [
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_CHAT_ID",
            "HELIUS_API_KEY",
            "ETHERSCAN_API_KEY",
        ]
        missing = [k for k in required if not os.getenv(k)]
        if missing:
            raise EnvironmentError(
                f"Missing required environment variables: {', '.join(missing)}"
            )
        return cls(
            telegram_bot_token=os.environ["TELEGRAM_BOT_TOKEN"],
            telegram_chat_id=os.environ["TELEGRAM_CHAT_ID"],
            helius_api_key=os.environ["HELIUS_API_KEY"],
            etherscan_api_key=os.environ["ETHERSCAN_API_KEY"],
            max_top_holder_pct=float(os.getenv("MAX_TOP_HOLDER_PCT", "20.0")),
            min_liquidity_usd=float(os.getenv("MIN_LIQUIDITY_USD", "500.0")),
            solana_poll_interval=int(os.getenv("SOLANA_POLL_INTERVAL", "30")),
            eth_poll_interval=int(os.getenv("ETH_POLL_INTERVAL", "15")),
        )
