---
name: sumplus-survival-strategy
description: |
  Generates a survival-first, backtestable trading StrategySpec for BSC majors from CoinMarketCap
  market data. Reads regime (fear/greed, global metrics), per-asset 1h/4h momentum, and realised
  volatility, then emits a StrategySpec whose risk budget is dialled by regime: it takes risk only
  when momentum agrees and volatility is low, caps exposure, and de-risks on a drawdown ladder that
  sits well inside a hard elimination gate. Output is a machine-readable StrategySpec (JSON) plus a
  reproducible backtest, not a live agent.
  Trigger: "trading strategy", "strategy spec", "backtestable strategy", "survival strategy",
  "risk-managed strategy", "BSC strategy", "/sumplus-survival-strategy"
license: MIT
compatibility: ">=1.0.0"
user-invocable: true
allowed-tools:
  - mcp__cmc-mcp__search_cryptos
  - mcp__cmc-mcp__get_crypto_quotes_latest
  - mcp__cmc-mcp__get_crypto_technical_analysis
  - mcp__cmc-mcp__get_crypto_marketcap_technical_analysis
  - mcp__cmc-mcp__get_global_metrics_latest
  - mcp__cmc-mcp__trending_crypto_narratives
---

# Sumplus Survival-First Strategy Skill

This Skill turns CoinMarketCap market data into a **StrategySpec**: a complete, machine-readable,
backtestable description of a long-only spot strategy for a small universe of BSC majors. The
design goal is capital preservation under a hard drawdown-elimination gate. The Skill does not place
trades. It produces the spec and the evidence; a separate live agent (Track 1) can execute it.

## When to use

Use this Skill whenever someone asks for a trading strategy, a strategy spec, a risk-managed or
"survival-first" approach, or a backtestable quant idea for BSC majors (WBNB, BTCB, ETH, CAKE).

## What it produces

A single `StrategySpec` object (see `strategyspec.schema.json` and `strategyspec.example.json`),
plus a one-line summary of the regime read that shaped it. The StrategySpec is the deliverable; it
is consumed unchanged by the backtester in `backtest/` and by the live executor in `agent/`.

## Core principle

In a contest (or any mandate) that eliminates an account the moment its drawdown crosses a gate, the
dominant objective is not the highest return. It is to never be eliminated while staying disciplined.
A strategy that makes 8% with a 3% drawdown beats one that makes 30% with a 25% drawdown, because the
second is disqualified before it can keep the 30%. So every parameter below is set to keep the equity
curve far from the gate.

## Workflow

### 1. Read the regime from CoinMarketCap

Pull, in order:

- `get_global_metrics_latest` -> fear/greed index and total-market trend. This sets the **regime**:
  - extreme greed or bearish breakdown -> `risk_off` (scale exposure down)
  - neutral / mild -> `neutral`
  - constructive uptrend with healthy breadth -> `risk_on` (base exposure)
- For each asset in the universe, `get_crypto_quotes_latest` (price, % change 1h/24h) and
  `get_crypto_technical_analysis` -> 1h and 4h momentum and a realised-volatility read.
- Optionally `trending_crypto_narratives` to admit up to 3 extra liquid trending names that pass the
  liquidity and spread filters; otherwise stay with the four majors.

### 2. Map the regime to a risk budget

The regime scales one knob, the risky-exposure cap, leaving the survival mechanics fixed:

| regime    | max risky exposure | rationale                                   |
|-----------|--------------------|---------------------------------------------|
| risk_on   | 12%                | base budget; momentum + low vol present     |
| neutral   | 8%                  | trimmed; mixed signals                      |
| risk_off  | 4%                  | minimal; extreme greed or bearish breakdown |

The drawdown ladder, stops, sizing band, and gate buffer do not move with regime. Only the ceiling
on how much risk can be on at once.

### 3. Emit the StrategySpec

Fill the StrategySpec with:

- **universe**: WBNB, BTCB, ETH, CAKE, quoted in USDT/USDC, long-only spot on PancakeSwap.
- **entry signal**: take risk only when 1h and 4h momentum agree in sign and realised vol < 4%.
- **sizing**: 1 to 2.5% of NAV per trade, volatility-scaled; total risky exposure capped per the
  regime table above.
- **drawdown ladder**: halve size at 1% drawdown, open no new risk at 2%, flatten to stablecoins at
  3%. Internal hard kill at 3%, a 3-point buffer under a 6% elimination gate.
- **exits**: 2% stop-loss, 4% take-profit, 48h time-stop.
- **min-activity**: a tiny in-policy micro-rebalance keeps a minimum trade count without churning.

Return the StrategySpec as JSON. Do not place any trade.

### 4. Point to the proof

Every StrategySpec this Skill emits is backtestable with no edits:

```bash
python backtest/run.py                 # synthetic regime-rich head-to-head (champion vs naive DCA)
python backtest/real_data_live.py      # the same committed spec on 3 recent weeks of REAL data
```

Report the headline: on a regime-rich synthetic series the spec survives a crash with a peak
drawdown under 4% while a naive DCA baseline is eliminated; on three recent real-data weeks it stayed
inside the gate every week (worst-week drawdown under 1%) while the naive baseline breached the gate.

## Generating a spec programmatically

`generate_spec.py` runs the whole workflow and prints a StrategySpec. It uses the CoinMarketCap MCP /
API when a key is present, and a deterministic offline scenario otherwise, so it always runs:

```bash
python skills/sumplus-survival-strategy/generate_spec.py            # offline mock regime
python skills/sumplus-survival-strategy/generate_spec.py --fng 82   # force a fear/greed value
```

## Honesty notes

- The Skill optimises for survival, not for maximum return. On a trendless tape it will sit mostly in
  stablecoins and return near zero rather than force trades.
- The regime-to-exposure mapping is deliberately simple and legible. The point of the spec is that a
  reviewer can read every rule and reproduce every number, not that it is a black box.
