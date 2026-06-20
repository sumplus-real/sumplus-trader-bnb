# Sumplus Trader

> A self-custody AI trader on BSC that can **explain, prove, and constrain every dollar of risk**
> while running unattended — built for the BNB Hack: AI Trading Agent Edition.

The pitch is not "look at my returns." It is **verifiable safe autonomy**: the agent commits its
policy on-chain before the market opens, then every decision for a week is a hash-chained receipt
that references that commitment. Anyone can recompute the hash from this repo and verify the agent
obeyed rules fixed before the market moved.

Three-layer trust stack: **TWAK** (self-custody signing) · **ERC-8004** (agent identity +
commit-reveal) · **Maria** (verifiable decision trail). Data from **CoinMarketCap MCP** only, paid
via **x402**.

## Quickstart (no keys, no network)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python -m agent.cli demo        # guardrail: allow / clamp / reject
python -m agent.cli simulate 6  # drive the real pipeline over a 6-week crash-and-recovery
python -m agent.cli verify      # recompute the committed hash + verify the receipt chain
python -m agent.cli web         # dashboard → http://127.0.0.1:8800
python -m pytest -q             # full test suite
python backtest/run.py          # Track 2: champion vs challenger head-to-head
```

Out of the box everything runs offline: a deterministic mock brain, mock execution backend, and a
mock CMC scenario. Add keys + `EXECUTION_BACKEND=twak` to go live.

## Layout

- `agent/strategy/` — the survival-first strategy (signals + intent), committed in `config/strategy.json`
- `agent/policy/` — **Maria verifiable layer**: policy engine, hash-chained receipts, commit-reveal
- `agent/abstention/` — the avoided-loss ledger (restraint as a feature)
- `agent/data/` — CoinMarketCap MCP client + x402 receipts (the only data source)
- `agent/execution/` — `ExecutionBackend` seam: TWAK adapter · Maria client · offline mock
- `agent/ops/` — unattended-week hardening: watchdog, RPC failover, nonce, persistent state, reconcile
- `agent/identity/` — ERC-8004 registration + commit-reveal publisher
- `agent/core.py` — the decision tick where every layer meets · `agent/simulate.py` — synthetic-week driver
- `agent/web.py` — the dashboard · `agent/run_live.py` — the live unattended loop
- `backtest/` — Track 2 head-to-head · `docs/` — BUILD_SPEC, TRACK2_RESEARCH, HUMAN_STEPS

## Verifiability

`config/strategy.json` is the committed policy. Its SHA-256 (comments stripped, keys sorted,
compact) is published to the agent's ERC-8004 identity before code-lock. Every receipt in
`receipts.jsonl` references it; `python -m agent.cli verify` recomputes and checks the chain.

## Open-source boundary

This repo is the agent. Maria and Arsenal are hosted services behind `ExecutionBackend`; the repo
ships only a client + an offline mock, so the full agent is runnable and auditable without exposing
backend source. `.env` is gitignored.

## Safety

The agent trades a **dedicated, freshly funded** wallet only. Risky exposure is capped at 12% and a
drawdown ladder flattens to stablecoins at 3% — a 3-point buffer under the 6% elimination gate. In
a 6-week crash-and-recovery stress test the strategy never breaches the gate.
