from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class CheckStatus(Enum):
    PASS = "✅"
    FAIL = "❌"
    UNKNOWN = "❓"


@dataclass
class CheckResult:
    name: str
    status: CheckStatus
    detail: str = ""


@dataclass
class CoinReport:
    chain: str
    name: str
    symbol: str
    address: str
    pair_address: str
    checks: list[CheckResult] = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        # UNKNOWN checks don't block — only explicit FAILs do
        return all(c.status != CheckStatus.FAIL for c in self.checks)

    @property
    def score(self) -> str:
        passes = sum(1 for c in self.checks if c.status == CheckStatus.PASS)
        return f"{passes}/{len(self.checks)}"

    @property
    def failed_checks(self) -> list[CheckResult]:
        return [c for c in self.checks if c.status == CheckStatus.FAIL]
