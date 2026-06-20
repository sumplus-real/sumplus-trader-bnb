# sumplus-survival-strategy (CMC Strategy Skill, Track 2)

A CoinMarketCap Strategy Skill for the BNB Hack Strategy Skills track. It reads market data from the
CoinMarketCap Agent Hub and emits a **StrategySpec**: a complete, machine-readable, backtestable
description of a survival-first long-only strategy for BSC majors. It ships a spec, not a live agent.

## Files

| File | What it is |
|------|-----------|
| `SKILL.md` | The Skill itself, in CMC/Agent-Skill format (frontmatter + workflow). Drop it into an agent's skills directory. |
| `generate_spec.py` | Runnable core. Reads a regime (fear/greed + momentum + vol from CMC, mock offline) and prints a StrategySpec. |
| `strategyspec.schema.json` | JSON Schema for the StrategySpec, including the survival invariant (every ladder rung sits inside the gate). |
| `strategyspec.example.json` | A generated example StrategySpec. |
| `test_skill.py` | Tests: regime mapping, spec well-formedness, and that the emitted spec runs on the backtester. |

## Try it (no key, no network)

```bash
python skills/sumplus-survival-strategy/generate_spec.py            # emit a StrategySpec (offline regime)
python skills/sumplus-survival-strategy/generate_spec.py --fng 88   # extreme greed -> risk_off, exposure 4%
python -m pytest skills/sumplus-survival-strategy/test_skill.py -q  # tests
```

With a CoinMarketCap key set (`CMC_API_KEY`), the same script reads live regime and momentum from the
Agent Hub. Without one it uses a deterministic offline scenario so a reviewer can always run it.

## How the Skill turns data into a strategy

1. Read regime from CMC: fear/greed index, global trend, and per-asset 1h/4h momentum + realised vol.
2. Map regime to a single knob, the risky-exposure ceiling: `risk_on` 12%, `neutral` 8%, `risk_off` 4%.
   Extreme greed, a bearish breakdown, or high volatility forces `risk_off`.
3. Emit the StrategySpec with the fixed survival mechanics: momentum-agreement entry, a 1/2/3%
   drawdown ladder, 2% stop / 4% take-profit / 48h time-stop, and a 3-point buffer under a 6% gate.

## Backtestable, with no edits

The emitted StrategySpec maps straight onto the backtester (`generate_spec.to_backtest_cfg`). Two
runs reproduce the evidence:

```bash
python backtest/run.py                 # synthetic regime-rich head-to-head vs a naive DCA baseline
python backtest/real_data_live.py      # the committed spec on 3 recent weeks of REAL Binance data
```

Headline: on the synthetic series the spec survives a crash with a peak drawdown under 4% while the
naive DCA baseline is eliminated; on three recent real-data weeks it stayed inside the 6% gate every
week (worst-week drawdown under 1%) while the naive baseline breached the gate. Full write-up in
`docs/TRACK2_RESEARCH.md`.

## Relationship to the live agent (Track 1)

The StrategySpec is the same policy the Track 1 live agent commits on-chain (`config/strategy.json`)
and trades. Track 2 ships the spec and its proof; Track 1 executes it under self-custody. One
strategy, verifiable on both sides.
