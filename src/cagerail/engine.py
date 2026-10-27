"""The cage: every order intent passes through Cage.check() before it may
reach a broker. The cage never places orders — it only allows, resizes,
denies, or demands a human approval, and it remembers everything.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .config import GuardConfig


@dataclass
class Intent:
    """An order a strategy/agent wants to place."""
    symbol: str
    side: str            # "buy" | "sell"
    notional: float      # order value in account currency (> 0)
    agent: str = "bot"   # who wants this (strategy name / agent id)

    def __post_init__(self):
        if self.side not in ("buy", "sell"):
            raise ValueError(f"side must be 'buy' or 'sell', got {self.side!r}")
        if self.notional <= 0:
            raise ValueError("notional must be > 0")


@dataclass
class Decision:
    action: str                      # ALLOW | RESIZE | DENY | REQUIRE_APPROVAL
    allowed_notional: float          # 0 when denied
    reasons: list[str] = field(default_factory=list)
    rule: str | None = None          # the rule that decided, if any


class Cage:
    def __init__(self, config: GuardConfig, equity: float):
        if equity <= 0:
            raise ValueError("equity must be > 0")
        self.config = config
        self.equity = equity
        self.peak_equity = equity
        self.positions: dict[str, float] = {}   # symbol -> signed notional (long > 0)
        self.halted = False
        self.halt_reason: str | None = None
        self.cooldown_until: float = 0.0
        self.consecutive_losses = 0
        self._day: str | None = None
        self._day_start_equity = equity
        self.daily_pnl = 0.0
        self.trades_today = 0
        self.audit: list[dict] = []

    # ---------- state helpers ----------

    def _roll_day(self, ts: float) -> None:
        day = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
        if day != self._day:
            self._day = day
            self._day_start_equity = self.equity
            self.daily_pnl = 0.0
            self.trades_today = 0

    def gross(self, symbol: str | None = None) -> float:
        if symbol is not None:
            return abs(self.positions.get(symbol, 0.0))
        return sum(abs(v) for v in self.positions.values())

    def _log(self, ts: float, event: dict) -> None:
        self.audit.append({
            "ts": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
            "session": "cagerail",
            **event,
        })

    def _halt(self, reason: str, ts: float) -> None:
        if not self.halted:
            self.halted = True
            self.halt_reason = reason
            self._log(ts, {"agent": "cagerail", "type": "error", "message": f"HALT: {reason}"})

    def reset_halt(self) -> None:
        """Human post-mortem done: release the cage (drawdown peak resets)."""
        self.halted = False
        self.halt_reason = None
        self.peak_equity = self.equity

    # ---------- brakes ----------

    def _check_brakes(self, ts: float) -> None:
        if self.peak_equity > 0:
            dd = (self.peak_equity - self.equity) / self.peak_equity
            if dd >= self.config.max_drawdown_pct:
                self._halt(f"max drawdown breached: {dd:.1%} >= {self.config.max_drawdown_pct:.1%}", ts)
                return
        if self._day_start_equity > 0:
            loss = -self.daily_pnl / self._day_start_equity
            if loss >= self.config.daily_loss_limit_pct:
                self._halt(f"daily loss limit breached: {loss:.1%} >= "
                           f"{self.config.daily_loss_limit_pct:.1%}", ts)

    # ---------- the gate ----------

    def check(self, intent: Intent, ts: float | None = None,
              approved: bool = False) -> Decision:
        ts = time.time() if ts is None else ts
        self._roll_day(ts)
        cfg = self.config
        eq = self.equity

        def decide(action, allowed, reasons, rule=None):
            d = Decision(action=action, allowed_notional=round(allowed, 2),
                         reasons=reasons, rule=rule)
            self._log(ts, {
                "agent": intent.agent, "type": "tool_call", "tool": "order.intent",
                "args": {"symbol": intent.symbol, "side": intent.side,
                         "notional": intent.notional},
                "decision": action, "allowed_notional": d.allowed_notional,
                "rule": rule, "reasons": reasons,
            })
            if action == "REQUIRE_APPROVAL":
                pass
            return d

        if cfg.allowed_symbols is not None and intent.symbol not in cfg.allowed_symbols:
            return decide("DENY", 0, [f"{intent.symbol} is not in allowed_symbols"],
                          "symbol-allowlist")

        # Risk-reducing orders (closing/reducing exposure) always pass,
        # even while halted or cooling down: getting out is the safe move.
        signed = self.positions.get(intent.symbol, 0.0)
        reducing = (intent.side == "sell" and signed > 0) or \
                   (intent.side == "buy" and signed < 0)
        if reducing:
            return decide("ALLOW", min(intent.notional, abs(signed)),
                          ["risk-reducing order"], "risk-reducing")

        if self.halted:
            return decide("DENY", 0, [f"cage halted: {self.halt_reason}"], "halted")
        if ts < self.cooldown_until:
            return decide("DENY", 0, [f"cooldown active for "
                                      f"{int(self.cooldown_until - ts)}s more "
                                      f"(consecutive losses)"], "cooldown")
        if self.trades_today >= cfg.max_trades_per_day:
            return decide("DENY", 0, [f"daily trade cap reached "
                                      f"({cfg.max_trades_per_day})"], "trade-cap")

        allowed = intent.notional
        reasons: list[str] = []
        rule = None

        order_cap = cfg.max_order_pct * eq
        if allowed > order_cap:
            allowed = order_cap
            reasons.append(f"order capped at {cfg.max_order_pct:.0%} of equity "
                           f"(${order_cap:,.2f})")
            rule = "order-cap"

        room = cfg.max_position_pct * eq - self.gross(intent.symbol)
        if allowed > room:
            allowed = max(room, 0.0)
            reasons.append(f"symbol exposure capped at {cfg.max_position_pct:.0%} of equity")
            rule = "position-cap"

        room_total = cfg.max_total_exposure_pct * eq - self.gross()
        if allowed > room_total:
            allowed = max(room_total, 0.0)
            reasons.append(f"total exposure capped at {cfg.max_total_exposure_pct:.0%} of equity")
            rule = "exposure-cap"

        if allowed <= 0:
            return decide("DENY", 0, reasons or ["no room under the caps"], rule)

        if allowed > cfg.require_approval_above_pct * eq and not approved:
            return decide("REQUIRE_APPROVAL", allowed,
                          reasons + [f"order exceeds {cfg.require_approval_above_pct:.0%} "
                                     f"of equity: human approval required"],
                          "approval-threshold")

        return decide("RESIZE" if allowed < intent.notional else "ALLOW",
                      allowed, reasons, rule)

    # ---------- bookkeeping ----------

    def record_fill(self, intent: Intent, filled_notional: float,
                    pnl: float = 0.0, ts: float | None = None) -> None:
        """Record an executed fill so positions, PnL and brakes stay true."""
        ts = time.time() if ts is None else ts
        self._roll_day(ts)
        delta = filled_notional if intent.side == "buy" else -filled_notional
        self.positions[intent.symbol] = self.positions.get(intent.symbol, 0.0) + delta
        self.trades_today += 1
        self.daily_pnl += pnl
        self.equity += pnl
        self.peak_equity = max(self.peak_equity, self.equity)
        if pnl < 0:
            self.consecutive_losses += 1
            if self.consecutive_losses >= self.config.max_consecutive_losses:
                self.cooldown_until = ts + self.config.cooldown_seconds
                self._log(ts, {"agent": "cagerail", "type": "error",
                               "message": f"cooldown started: {self.consecutive_losses} "
                                          f"consecutive losses"})
        elif pnl > 0:
            self.consecutive_losses = 0
        self._check_brakes(ts)

    def record_equity(self, equity: float, ts: float | None = None) -> None:
        """Mark-to-market update (drives the drawdown brake)."""
        ts = time.time() if ts is None else ts
        self._roll_day(ts)
        if self._day is not None and equity != self.equity:
            self.daily_pnl += equity - self.equity
        self.equity = equity
        self.peak_equity = max(self.peak_equity, equity)
        self._check_brakes(ts)

    # ---------- audit ----------

    def export_audit(self, path: str | Path) -> None:
        """Write the audit trail as JSONL in the whoapproved event schema,
        so any session can be replayed and audited after the fact."""
        with Path(path).open("w", encoding="utf-8") as f:
            for e in self.audit:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
