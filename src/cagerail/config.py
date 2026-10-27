"""Guard configuration — every limit is a fraction of current equity
unless stated otherwise, so the cage scales with the account."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class GuardConfig:
    # Per-order ceiling: one order may not exceed this fraction of equity.
    max_order_pct: float = 0.10
    # Per-symbol ceiling: gross exposure on one symbol after the fill.
    max_position_pct: float = 0.25
    # Portfolio ceiling: total gross exposure after the fill.
    max_total_exposure_pct: float = 0.80
    # Daily brake: halt when the day's PnL falls below -this fraction of
    # the equity at day start.
    daily_loss_limit_pct: float = 0.03
    # Drawdown brake: halt when equity falls this fraction below its peak.
    max_drawdown_pct: float = 0.15
    # Activity caps.
    max_trades_per_day: int = 50
    # After this many consecutive losing fills, cool down.
    max_consecutive_losses: int = 3
    cooldown_seconds: int = 3600
    # Orders larger than this fraction of equity need explicit human
    # approval (Decision.action == "REQUIRE_APPROVAL").
    require_approval_above_pct: float = 0.20
    # If set, only these symbols may be traded.
    allowed_symbols: list[str] | None = None

    def __post_init__(self):
        for name in ("max_order_pct", "max_position_pct", "max_total_exposure_pct",
                     "daily_loss_limit_pct", "max_drawdown_pct",
                     "require_approval_above_pct"):
            v = getattr(self, name)
            if not (0 < v <= 1):
                raise ValueError(f"{name} must be in (0, 1], got {v}")
        if self.max_trades_per_day < 1:
            raise ValueError("max_trades_per_day must be >= 1")
        if self.max_consecutive_losses < 1:
            raise ValueError("max_consecutive_losses must be >= 1")
        if self.cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be >= 0")

    @classmethod
    def from_dict(cls, data: dict) -> "GuardConfig":
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown config keys: {sorted(unknown)}")
        return cls(**data)

    @classmethod
    def from_json(cls, path: str | Path) -> "GuardConfig":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def to_dict(self) -> dict:
        return asdict(self)
