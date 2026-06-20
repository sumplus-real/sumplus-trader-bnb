# Sumplus Trader — BNB Hack: AI Trading Agent Edition

> A self-custody AI trader on BSC that can **explain, prove, and constrain every dollar of risk**
> while running unattended for a week. The flight recorder and kill-switch standard for
> autonomous on-chain finance.

Tracks: **Track 1** (Autonomous Trading Agents, live) + **Track 2** (Strategy research).

---

## The one idea

Every team will put a strategy on Trust Wallet Agent Kit and hope the week goes their way. We do
that too — but the agent is the easy part. The hard part, the part nobody shows, is *proving* an
autonomous agent stayed inside its mandate when no human was watching. That is our product
(Sumplus: verifiable financial infrastructure for AI agents), and it is exactly what this
hackathon exists to make real.

So before the market opens we **commit our policy on-chain**, and every decision the agent makes
for a week is a hash-chained receipt that references that commitment. Afterwards, anyone
recomputes the hash from this repo and verifies the agent obeyed rules fixed *before* the market
moved. "Rule adherence" stops being a claim and becomes a proof.

## Three-layer trust stack (one flex per host)

| Layer | What | Host it speaks to |
|---|---|---|
| Self-custody signing | **Trust Wallet Agent Kit** — keys stay local, registration, x402 | Trust Wallet |
| Self-sovereign identity | **ERC-8004** agent identity + **commit-reveal** of the policy hash | BNB Chain |
| Verifiable decision trail | **Maria** — hash-chained receipts proving every decision obeyed the committed policy | Sumplus |
| Data provenance | **CoinMarketCap MCP** is the *only* market-data source; **x402** receipts logged as paid-data provenance | CoinMarketCap |

## How it trades — survival first

The competition eliminates any agent that breaches ~6% drawdown, and scores risk-adjusted return
+ rule adherence. The winning move is not to gamble for the highest return; it is to **never be
eliminated** while staying disciplined. The strategy (committed in `config/strategy.json`):

- Long-only spot in a small, liquid universe (WBNB, BTCB, ETH, CAKE vs USDT/USDC) on PancakeSwap.
- Enter only when 1h and 4h momentum **agree** and realized volatility is low; otherwise hold.
- Risky exposure capped at 12%, sizes 1–2.5% of NAV, volatility-scaled.
- A drawdown ladder that de-risks *earlier* than the gate: halve at 1%, no-new-risk at 2%,
  flatten to stablecoins at 3% — a 3-point buffer under the 6% elimination line.
- Scheduled micro-rebalances guarantee the minimum trade count without overtrading.
- **Abstention is first-class**: every skip is a reasoned, hash-chained receipt, marked to
  market later (the avoided-loss ledger). The agent proves judgement by knowing when *not* to act.

**Stress test (6 weeks, calm → chop → crash → recovery, `python -m agent.simulate 6`):** the
committed strategy survives a severe crash with a **peak drawdown of ~2.8–3.7%, never breaching
the 6% gate**, with a fully intact, verifiable receipt chain.

## Track 2 — survival beats return-chasing (backtest)

`python backtest/run.py` runs the live committed strategy (champion) head-to-head against a naive
DCA baseline (challenger) over a regime-rich synthetic series:

- Champion: **survives** all six weeks, peak drawdown **3.93%**, finishes **+7.58%**.
- Challenger: **eliminated at hour 564**, drawdown blows to 29% in the crash.
- On the window where both are alive: champion Sharpe **1.67** vs challenger **0.87**, Calmar **0.47** vs **0.12**.

The challenger's flattering full-period return is a mirage — the gate disqualifies it before the
recovery. Full write-up: `docs/TRACK2_RESEARCH.md`.

## Run it (no keys, no network)

```bash
pip install -r requirements.txt
python -m agent.cli demo        # guardrail: allow / clamp / reject
python -m agent.cli simulate 6  # drive the real pipeline over a 6-week crash-and-recovery
python -m agent.cli verify      # recompute the committed hash + verify the receipt chain
python -m agent.cli web         # the dashboard → http://127.0.0.1:8800
```

Ships with an offline mock brain + mock backend and a deterministic CMC scenario, so anyone can
run the full agent and watch the verifiable trail build — no keys, no install beyond pip.

## The dashboard

`python -m agent.cli web` — a live board sized for a judge to watch over seven days: the committed
policy hash with a green VERIFIED badge, NAV + a drawdown gauge against the 6% gate, the equity
curve, a streaming decision feed (trades + reasoned abstentions, each a receipt), and a
**black-box replay** that recomputes any receipt's hash on demand to prove the trail is honest.

## Architecture

```
CMC MCP (x402 receipts) → survival strategy → Maria verifiable policy → hash-chained receipt
                                                       │
                                       trade ──────────┴──────── abstain → avoided-loss ledger
                                         │
                                  TWAK self-custody signer → PancakeSwap (BSC)
```

Two-key safety: a trade fires only if Maria (ours, verifiable) and TWAK (official, on-chain spend
fence) both allow. TWAK is kept thin — signer + registration + x402; Maria is the decision
authority. The live loop is ops-hardened for an unattended week: watchdog restarts, atomic
persistent state, RPC failover, nonce management, stale-data rejection, fail-closed on doubt.

## Verify our claims

```bash
python -m agent.cli verify
# committed_policy_hash, receipts, chain_intact: true, all_reference_committed_hash: true
python -m pytest -q          # full suite
python backtest/run.py       # the champion-vs-challenger head-to-head
```

## On-chain (live window 6/22–28)

The agent's BSC wallet is registered via `twak compete register`; the policy hash is published to
its ERC-8004 identity before code-lock; the wallet then trades unattended on PancakeSwap. Wallet,
identity, and commit-reveal transaction are linked from the dashboard footer and `config/proof.json`.

## Open-source boundary

This repo is the agent — open and runnable. Maria (policy/verification) and Arsenal (routing) are
hosted services behind a clean `ExecutionBackend` seam; the repo ships an API client plus an
offline mock so the whole agent runs and is auditable without exposing backend source.
