# cagerail

**The cage for trading bots and AI agents.**

Position limits, loss brakes, cooldowns and a kill switch that sit between
any strategy — hand-written or LLM-driven — and the broker. The strategy
proposes; the cage disposes: every order intent comes back as
`ALLOW`, `RESIZE`, `DENY`, or `REQUIRE_APPROVAL`, with the reason attached.

```bash
pip install -e .
cagerail demo
```

```text
cagerail demo — same strategy, same market (300 daily bars, crash on days 180-205)
strategy: buy the dip with 50% of equity at every -2% step. No stops.

            final equity  max drawdown  trades
naked      $   -4,232.00       132.0%      10
caged      $    8,900.16        14.9%       3

The strategy didn't change. The cage is what made it survivable.
```

## Why this exists

Read the 2026 post-mortems of AI trading blowups and a pattern repeats:
the model made a bad call is *never* the story. The story is custody and
permissions — an agent that could move 100% of a balance eventually did.
As [one widely-read analysis](https://medium.com/@xgramio/from-chatbot-to-counterparty-how-ai-trading-actually-grew-up-in-2026-31883b17d7ed)
put it: *"Retail agents shipped the intelligence and skipped the cage."*
Institutions survive their agents because the cage — position limits,
daily loss limits, kill switches, four-eyes approval — already exists.
Regulators noticed too: agentic trading is heading for high-risk
classification under the EU AI Act, and Singapore's agentic-AI framework
(Jan 2026) keeps organisations legally accountable for their agents.

Meanwhile the algo-trading market keeps growing (~$27B in 2026) and every
framework sells *strategies*. Almost nobody sells the brakes. **cagerail
is the brakes.**

## What the cage enforces

| guard | default | effect |
|---|---|---|
| per-order cap | 10% of equity | oversized orders are resized, not trusted |
| per-symbol cap | 25% of equity | one position can't become the whole account |
| total exposure cap | 80% of equity | gross exposure ceiling across symbols |
| daily loss brake | −3% of day-start equity | latching halt until a human reviews |
| drawdown brake | −15% from peak equity | latching halt; `reset_halt()` after post-mortem |
| consecutive-loss cooldown | 3 losses → 1h | stops revenge-trading loops |
| daily trade cap | 50/day | runaway loops hit a wall |
| approval threshold | >20% of equity | big orders return `REQUIRE_APPROVAL` |
| symbol allowlist | optional | nothing outside the list trades |

Risk-reducing orders (closing a position) always pass — even while halted.
Getting out is the safe move.

## Use it

```python
from cagerail import Cage, GuardConfig, Intent

cage = Cage(GuardConfig.from_json("examples/cage.json"), equity=10_000)

d = cage.check(Intent("BTCUSD", "buy", 8_000, agent="my-llm-agent"))
# Decision(action="RESIZE", allowed_notional=1000.0, rule="order-cap", ...)

if d.action in ("ALLOW", "RESIZE"):
    fill = broker.place("BTCUSD", "buy", d.allowed_notional)
    cage.record_fill(Intent("BTCUSD", "buy", d.allowed_notional),
                     d.allowed_notional, pnl=fill.realized_pnl)

cage.record_equity(broker.equity())   # mark-to-market: drives the brakes
cage.export_audit("audit.jsonl")      # whoapproved-compatible audit trail
```

Or from the shell:

```bash
cagerail check --equity 10000 --symbol BTCUSD --side buy --notional 8000
# {"action": "RESIZE", "allowed_notional": 1000.0, "rule": "order-cap", ...}
```

## Audit trail

Every decision is logged with its rule and reasons, in the same event
schema as [whoapproved](https://github.com/jacelovehaha/whoapproved) —
so "who approved this trade, and what did the cage say?" is answerable
months later, from evidence.

## Business model

The core cage is MIT-licensed and free — safety shouldn't be a luxury.
Planned paid layers (the subscription is for the *watchtower*, not the lock):

- **cagerail Monitor** (hosted): live dashboards, halt alerts to
  Telegram/WhatsApp/email, multi-account rollups.
- **cagerail Team**: shared approval workflows (four-eyes for big orders),
  audit exports for compliance.

## Roadmap

- MCP server mode: expose the cage as a tool any LLM agent must call first
- Broker/exchange adapters (CCXT, Alpaca) with reference integrations
- Freqtrade / Jesse middleware examples
- Volatility-adaptive caps (tighten automatically in turbulent markets)

## Disclaimer

cagerail is risk tooling, not financial advice and not a strategy. A cage
limits how fast a bad strategy can hurt you; it cannot make a bad strategy
good. Test on paper before you trust it with a cent.

## License

MIT
