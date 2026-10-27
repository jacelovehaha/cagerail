"""Command-line interface.

    cagerail demo
    cagerail check --equity 10000 --symbol BTCUSD --side buy --notional 8000
    cagerail check --config examples/cage.json --equity 10000 \
                   --symbol BTCUSD --side buy --notional 1500
"""

from __future__ import annotations

import argparse
import json
import sys

from .config import GuardConfig
from .engine import Cage, Intent
from .simulate import demo_text


def cmd_demo(_args: argparse.Namespace) -> int:
    print(demo_text())
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    cfg = GuardConfig.from_json(args.config) if args.config else GuardConfig()
    cage = Cage(cfg, equity=args.equity)
    if args.position:
        cage.positions[args.symbol] = args.position
    d = cage.check(Intent(args.symbol, args.side, args.notional, agent=args.agent),
                   approved=args.approved)
    print(json.dumps({
        "action": d.action,
        "allowed_notional": d.allowed_notional,
        "rule": d.rule,
        "reasons": d.reasons,
    }, indent=2))
    return 0 if d.action in ("ALLOW", "RESIZE") else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="cagerail",
        description="The cage for trading bots and AI agents: limits, brakes, kill switches.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pd = sub.add_parser("demo", help="run the naked-vs-caged simulation")
    pd.set_defaults(func=cmd_demo)

    pc = sub.add_parser("check", help="evaluate one order intent against the cage")
    pc.add_argument("--config", help="JSON config file (defaults: built-in guard)")
    pc.add_argument("--equity", type=float, required=True)
    pc.add_argument("--symbol", required=True)
    pc.add_argument("--side", choices=("buy", "sell"), required=True)
    pc.add_argument("--notional", type=float, required=True)
    pc.add_argument("--position", type=float, default=0.0,
                    help="existing signed position notional in this symbol")
    pc.add_argument("--agent", default="cli")
    pc.add_argument("--approved", action="store_true",
                    help="a human has approved this order")
    pc.set_defaults(func=cmd_check)

    args = p.parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
