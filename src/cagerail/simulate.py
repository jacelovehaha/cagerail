"""Deterministic demo: the same reckless dip-buying strategy, the same
market — once naked, once inside the cage.

Market: 300 daily bars. A calm uptrend, then a 25-day crash (-3%/day drift).
Strategy: every time the price drops >=2% below the last buy price, buy
again with 50% of current equity. No stops, no limits. This is the classic
way retail bots die.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .config import GuardConfig
from .engine import Cage, Intent

START_EQUITY = 10_000.0
BARS = 300
CRASH_START, CRASH_END = 180, 205


def price_series(seed: int = 7) -> list[float]:
    rng = random.Random(seed)
    prices = [100.0]
    for i in range(1, BARS):
        if CRASH_START <= i < CRASH_END:
            drift, vol = -0.030, 0.020
        else:
            drift, vol = 0.0004, 0.012
        prices.append(max(1.0, prices[-1] * (1 + drift + rng.gauss(0, vol))))
    return prices


@dataclass
class SimResult:
    final_equity: float
    max_drawdown: float
    trades: int
    halted: bool
    halt_reason: str | None


def run(caged: bool, seed: int = 7) -> SimResult:
    prices = price_series(seed)
    cash, shares = START_EQUITY, 0.0
    cage = Cage(GuardConfig(), START_EQUITY) if caged else None
    last_buy: float | None = None
    equity_curve = [START_EQUITY]
    trades = 0
    day0 = 1_700_000_000.0  # fixed epoch so runs are reproducible

    for i, price in enumerate(prices):
        ts = day0 + i * 86_400
        equity = cash + shares * price
        if cage:
            cage.record_equity(equity, ts=ts)
        equity_curve.append(equity)

        dip = last_buy is not None and price <= last_buy * 0.98
        first = last_buy is None
        if not (dip or first):
            continue

        equity = cash + shares * price
        if equity <= 0:
            break
        notional = 0.50 * equity
        if cage:
            d = cage.check(Intent("DEMO", "buy", notional, agent="dip-buyer"), ts=ts)
            if d.action in ("DENY", "REQUIRE_APPROVAL"):
                continue
            notional = d.allowed_notional
        qty = notional / price
        cash -= notional
        shares += qty
        trades += 1
        last_buy = price
        if cage:
            cage.record_fill(Intent("DEMO", "buy", notional, agent="dip-buyer"),
                             notional, pnl=0.0, ts=ts)

    final = cash + shares * prices[-1]
    equity_curve.append(final)
    peak, max_dd = equity_curve[0], 0.0
    for e in equity_curve:
        peak = max(peak, e)
        if peak > 0:
            max_dd = max(max_dd, (peak - e) / peak)
    return SimResult(
        final_equity=final, max_drawdown=max_dd, trades=trades,
        halted=bool(cage and cage.halted),
        halt_reason=cage.halt_reason if cage else None,
    )


def demo_text() -> str:
    naked = run(caged=False)
    caged = run(caged=True)
    lines = [
        "cagerail demo — same strategy, same market (300 daily bars, crash on days 180-205)",
        "strategy: buy the dip with 50% of equity at every -2% step. No stops.",
        "",
        f"{'':10s} {'final equity':>13s} {'max drawdown':>13s} {'trades':>7s}",
        f"{'naked':10s} ${naked.final_equity:>12,.2f} {naked.max_drawdown:>12.1%} {naked.trades:>7d}",
        f"{'caged':10s} ${caged.final_equity:>12,.2f} {caged.max_drawdown:>12.1%} {caged.trades:>7d}",
        "",
        f"cage halted: {caged.halted} ({caged.halt_reason})",
        "The strategy didn't change. The cage is what made it survivable.",
    ]
    return "\n".join(lines)
