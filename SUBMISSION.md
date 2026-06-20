# Sumplus Trader: BNB Hack AI Trading Agent Edition

> A self-custody AI trader on BSC that runs unattended for a week and can prove, afterward, that it
> never broke its own rules. Think flight recorder plus kill switch for autonomous on-chain finance.

Tracks: Track 1 (Autonomous Trading Agents, live) and Track 2 (Strategy research).

---

## The one idea

Every team will put a strategy on Trust Wallet Agent Kit and hope the week goes their way. We do
that part too, but the strategy is the easy part. The hard part, the part nobody shows, is proving
an autonomous agent stayed inside its mandate when no human was watching. That is what Sumplus
builds (verifiable financial infrastructure for AI agents), and it is what this hackathon exists to
make real.

So before the market opens we commit our policy on-chain. Every decision the agent makes for the
next week is a hash-chained receipt that references that commitment. Afterward anyone recomputes
the hash from this repo and confirms the agent obeyed rules that were fixed before the market
moved. Rule adherence stops being a claim you have to take on faith and becomes something you can
check.

## Three-layer trust stack (one flex per host)

| Layer | What it does | Host it speaks to |
|---|---|---|
| Self-custody signing | Trust Wallet Agent Kit. Keys stay local, plus registration and x402. | Trust Wallet |
| Self-sovereign identity | ERC-8004 agent identity, carrying the commit-reveal of the policy hash | BNB Chain |
| Verifiable decision trail | Maria writes hash-chained receipts showing every decision obeyed the committed policy | Sumplus |
| Data provenance | CoinMarketCap MCP is the only market-data source; each fetch logs an x402 paid-data receipt | CoinMarketCap |

## How it trades: survival first

The competition eliminates any agent that breaches roughly 6% drawdown, and it scores
risk-adjusted return alongside rule adherence. So the winning move is not to gamble for the highest
number. It is to stay disciplined and never get eliminated. The strategy, committed in
`config/strategy.json`:

- Long-only spot in a small, liquid universe (WBNB, BTCB, ETH, CAKE against USDT/USDC) on PancakeSwap.
- Enter only when 1h and 4h momentum agree and realized volatility is low. Otherwise hold.
- Risky exposure capped at 12%, position sizes 1 to 2.5% of NAV, scaled by volatility.
- A drawdown ladder that de-risks ahead of the gate: halve at 1%, no new risk at 2%, flatten to
  stablecoins at 3%. That is a 3-point buffer under the 6% elimination line.
- Scheduled micro-rebalances hit the minimum trade count without overtrading.
- Abstention counts as a decision. Every skip is a reasoned, hash-chained receipt, marked to market
  later in the avoided-loss ledger. Knowing when not to act is part of the judgement we want to show.

**Stress test** (6 weeks, calm to chop to crash to recovery, `python -m agent.cli simulate 6`): the
committed live strategy survives a severe crash with a peak drawdown near 2.8%, well inside the 6%
gate, and the receipt chain stays fully intact.

## Track 2: survival beats return-chasing (backtest)

`python backtest/run.py` runs the live committed strategy (champion) head-to-head against a naive
DCA baseline (challenger) over a regime-rich synthetic series:

- Champion: survives all six weeks, peak drawdown 3.93%, finishes +7.58%.
- Challenger: eliminated at hour 564, drawdown blows to 29% in the crash.
- On the window where both are alive: champion Sharpe 1.67 vs challenger 0.87, Calmar 0.47 vs 0.12.

The challenger's flattering full-period return is a mirage. The gate disqualifies it before the
recovery ever arrives. Full write-up in `docs/TRACK2_RESEARCH.md`.

## Run it (no keys, no network)

```bash
pip install -r requirements.txt
python -m agent.cli demo        # guardrail: allow / clamp / reject
python -m agent.cli simulate 6  # drive the real pipeline over a 6-week crash-and-recovery
python -m agent.cli verify      # recompute the committed hash + verify the receipt chain
python -m agent.cli web         # the dashboard at http://127.0.0.1:8800
```

It ships with an offline mock brain, a mock backend, and a deterministic CMC scenario, so anyone
can run the full agent and watch the verifiable trail build. No keys, nothing to install beyond pip.

## The dashboard

`python -m agent.cli web` brings up a board sized for a judge to watch over seven days: the
committed policy hash with a green VERIFIED badge, NAV and a drawdown gauge against the 6% gate, the
equity curve, a streaming decision feed (trades and reasoned abstentions, each one a receipt), and a
black-box replay that recomputes any receipt's hash on demand to show the trail is honest.

## Architecture

```
CMC MCP (x402 receipts) → survival strategy → Maria verifiable policy → hash-chained receipt
                                                       │
                                       trade ──────────┴──────── abstain → avoided-loss ledger
                                         │
                                  TWAK self-custody signer → PancakeSwap (BSC)
```

A trade fires only if both Maria (ours, verifiable) and TWAK (the official on-chain spend fence)
allow it. TWAK stays thin: signer, registration, x402. Maria is the decision authority. The live
loop is hardened for an unattended week, with watchdog restarts, atomic persistent state, RPC
failover, nonce management, stale-data rejection, and fail-closed behavior whenever something looks
wrong.

## Verify our claims

```bash
python -m agent.cli verify
# committed_policy_hash, receipts, chain_intact: true, all_reference_committed_hash: true
python -m pytest -q          # full suite
python backtest/run.py       # the champion-vs-challenger head-to-head
```

## On-chain (live window 6/22–28)

The agent's BSC wallet is registered via `twak compete register`. The policy hash is published to
its ERC-8004 identity before code-lock, and the wallet then trades unattended on PancakeSwap.
Wallet, identity, and the commit-reveal transaction are all linked from the dashboard footer and
`config/proof.json`.

## What ships here, and what doesn't

This repo is the agent itself, open and runnable. Maria (policy and verification) and Arsenal
(routing) are hosted services behind a clean `ExecutionBackend` seam. The repo ships an API client
and an offline mock, so the whole agent runs and stays auditable without putting the backend source
in public.
