import json
import tempfile
import unittest
from pathlib import Path

from cagerail.config import GuardConfig
from cagerail.engine import Cage, Intent

T0 = 1_700_000_000.0  # 2023-11-14, all tests stay on this UTC day unless moved


def cage(equity=10_000.0, **kw):
    return Cage(GuardConfig(**kw), equity)


class TestCaps(unittest.TestCase):
    def test_small_order_allowed(self):
        d = cage().check(Intent("BTC", "buy", 500), ts=T0)
        self.assertEqual(d.action, "ALLOW")
        self.assertEqual(d.allowed_notional, 500)

    def test_order_cap_resizes(self):
        d = cage().check(Intent("BTC", "buy", 5_000), ts=T0)
        self.assertEqual(d.action, "RESIZE")
        self.assertEqual(d.allowed_notional, 1_000)  # 10% of 10k
        self.assertEqual(d.rule, "order-cap")

    def test_position_cap_resizes(self):
        c = cage()
        c.positions["BTC"] = 2_000
        d = c.check(Intent("BTC", "buy", 1_000), ts=T0)
        self.assertEqual(d.action, "RESIZE")
        self.assertEqual(d.allowed_notional, 500)  # room to 25% cap
        self.assertEqual(d.rule, "position-cap")

    def test_exposure_cap_denies_when_full(self):
        c = cage()
        c.positions["ETH"] = 8_000  # 80% total already
        d = c.check(Intent("BTC", "buy", 500), ts=T0)
        self.assertEqual(d.action, "DENY")
        self.assertEqual(d.rule, "exposure-cap")

    def test_symbol_allowlist(self):
        d = cage(allowed_symbols=["BTC"]).check(Intent("DOGE", "buy", 100), ts=T0)
        self.assertEqual(d.action, "DENY")
        self.assertEqual(d.rule, "symbol-allowlist")


class TestApproval(unittest.TestCase):
    CFG = dict(max_order_pct=0.5, max_position_pct=0.9,
               max_total_exposure_pct=1.0, require_approval_above_pct=0.2)

    def test_large_order_requires_approval(self):
        d = cage(**self.CFG).check(Intent("BTC", "buy", 3_000), ts=T0)
        self.assertEqual(d.action, "REQUIRE_APPROVAL")
        self.assertEqual(d.allowed_notional, 3_000)

    def test_approved_large_order_allowed(self):
        d = cage(**self.CFG).check(Intent("BTC", "buy", 3_000), ts=T0, approved=True)
        self.assertEqual(d.action, "ALLOW")


class TestBrakes(unittest.TestCase):
    def test_drawdown_halt_latches_and_blocks_buys(self):
        c = cage()
        c.record_equity(8_400, ts=T0)  # -16% from peak >= 15%
        self.assertTrue(c.halted)
        d = c.check(Intent("BTC", "buy", 100), ts=T0)
        self.assertEqual(d.action, "DENY")
        self.assertEqual(d.rule, "halted")

    def test_risk_reducing_sell_passes_while_halted(self):
        c = cage()
        c.positions["BTC"] = 3_000
        c.record_equity(8_400, ts=T0)
        self.assertTrue(c.halted)
        d = c.check(Intent("BTC", "sell", 1_000), ts=T0)
        self.assertEqual(d.action, "ALLOW")
        self.assertEqual(d.rule, "risk-reducing")

    def test_daily_loss_halt(self):
        c = cage()
        c.record_fill(Intent("BTC", "buy", 500), 500, pnl=-350, ts=T0)  # -3.5% day
        self.assertTrue(c.halted)
        self.assertIn("daily loss", c.halt_reason)

    def test_cooldown_after_consecutive_losses(self):
        c = cage()
        for i in range(3):
            c.record_fill(Intent(f"S{i}", "buy", 100), 100, pnl=-10, ts=T0)
        self.assertFalse(c.halted)
        d = c.check(Intent("BTC", "buy", 100), ts=T0 + 10)
        self.assertEqual(d.action, "DENY")
        self.assertEqual(d.rule, "cooldown")
        d2 = c.check(Intent("BTC", "buy", 100), ts=T0 + 3_700)
        self.assertEqual(d2.action, "ALLOW")

    def test_trade_cap(self):
        c = cage(max_trades_per_day=2)
        for i in range(2):
            c.record_fill(Intent(f"S{i}", "buy", 100), 100, pnl=5, ts=T0)
        d = c.check(Intent("BTC", "buy", 100), ts=T0)
        self.assertEqual(d.action, "DENY")
        self.assertEqual(d.rule, "trade-cap")

    def test_reset_halt_releases(self):
        c = cage()
        c.record_equity(8_000, ts=T0)
        self.assertTrue(c.halted)
        c.reset_halt()
        self.assertFalse(c.halted)
        d = c.check(Intent("BTC", "buy", 100), ts=T0)
        self.assertEqual(d.action, "ALLOW")


class TestAuditAndConfig(unittest.TestCase):
    def test_audit_export_schema(self):
        c = cage()
        c.check(Intent("BTC", "buy", 500), ts=T0)
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "audit.jsonl"
            c.export_audit(p)
            rows = [json.loads(x) for x in p.read_text().splitlines()]
        self.assertEqual(len(rows), 1)
        for key in ("ts", "session", "agent", "type"):
            self.assertIn(key, rows[0])
        self.assertEqual(rows[0]["tool"], "order.intent")

    def test_config_validation(self):
        with self.assertRaises(ValueError):
            GuardConfig(max_order_pct=1.5)
        with self.assertRaises(ValueError):
            GuardConfig.from_dict({"nope": 1})


if __name__ == "__main__":
    unittest.main()
