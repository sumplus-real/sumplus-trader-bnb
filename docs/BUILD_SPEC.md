# Sumplus Trader — BNB Hack Build Spec

> The plan, and the **committed strategy**. The canonical machine-readable policy lives in
> `config/strategy.json`; its SHA-256 is published to the agent's ERC-8004 identity **before
> code-lock** (commit-reveal). Every live decision receipt references that hash, so "rule
> adherence" becomes a proof anyone can recompute, not a claim.

---

## 0. What we are building, in one sentence

A self-custody AI trader on BSC that can **explain, prove, and constrain every dollar of risk**
while running unattended for a week — the flight recorder and kill-switch standard for
autonomous on-chain finance.

## 1. Why this wins (thesis)

The BNB Hack judges (BNB Chain + CoinMarketCap + Trust Wallet) score Track 1 on returns,
drawdown, **risk-adjusted performance**, and **rule adherence**, plus special prizes for
technical execution / originality / real-world relevance / demo. The $10K live-PnL top spot is a
one-week luck lottery across 149 tokens under a 6% drawdown gate. Our edge is not alpha — it is
the **verifiable trust layer**. We therefore:

1. Ship a live agent that **survives** the week (capital preservation, provably zero rule
   violations, smooth equity curve, minimum trade count met) — the living proof.
2. Win the judged dimensions where "verifiable financial infrastructure for AI agents" is our
   actual product, not a P&L line.

### The three-layer trust stack (one flex per sponsor)

| Layer | Tech | Sponsor it speaks to |
|---|---|---|
| Self-custody signing | **TWAK** (Trust Wallet Agent Kit) — keys local, dev-defined policy, registration, x402 | Trust Wallet |
| Self-sovereign agent identity | **ERC-8004** identity + commit-reveal of the policy hash | BNB Chain |
| Verifiable decision trail | **Maria** — hash-chained receipts proving every decision obeyed the committed policy | Sumplus (us) |
| Data provenance | **CMC MCP** as the *only* market-data source; **x402** receipts logged as paid-data provenance | CoinMarketCap |

### The signature move — commit-reveal (nobody else does this in 16h)

Before code-lock we publish `sha256(canonical strategy.json) + strategy_module_version` to the
agent's ERC-8004 identity in **one transaction**. During the unattended week, every Maria
decision receipt embeds that hash. Post-week, anyone can recompute the hash from the public repo
and verify the agent obeyed rules **fixed before the market moved**. This turns the fluffiest
judged criterion (rule adherence) into a cryptographic proof and makes the ERC-8004 flex
load-bearing instead of decorative.

## 2. Architecture

```
            CMC MCP data  ──(x402 receipt logged)──►  Strategy brain (deterministic, survival-first)
                                                              │  proposes Decision
                                                              ▼
                                    ┌──────────────────────────────────────────┐
                                    │  Maria verifiable policy layer (OURS)      │
                                    │  · rich policy: drawdown ladder, vol-scaled │
                                    │    sizing, per-token budget, regime, rate   │
                                    │  · emits hash-chained Receipt referencing   │
                                    │    the committed policy hash                │
                                    │  · ABSTENTIONS are first-class receipts     │
                                    └───────────────┬──────────────┬────────────┘
                                       approved │              │ abstain → avoided-loss ledger
                                                ▼              ▼
                                    ┌────────────────────┐   (record hypothetical price,
                                    │ TWAK thin adapter   │    mark-to-market later)
                                    │ sign + execute on   │
                                    │ PancakeSwap (BSC)   │   ◄── second, on-chain policy fence
                                    └─────────┬──────────┘
                                              ▼
                                          PancakeSwap V3 / BSC
```

**Two-key safety**: a trade fires only if Maria (ours, verifiable) AND TWAK (official, on-chain
spend fence) both allow. Keep the TWAK integration **thin** — TWAK = signer/registration/x402,
Maria = decision authority. Do not rebuild policy inside TWAK.

**Robustness choice**: the live brain is **deterministic and rule-based**, not an LLM. A
week-long unattended run rewards a transparent, replayable, fail-closed rule engine over an LLM
that can hallucinate or stall. (An optional LLM regime read is advisory only and never required
to act; if its data is stale the agent simply runs the deterministic core.)

## 3. Strategy (survival-first) — the committed rules

Canonical params in `config/strategy.json`. Summary:

- **Universe** (eligible, liquid, CMC-listed BEP-20): `WBNB, BTCB, ETH, CAKE`, quoted in
  `USDT`/`USDC`. Optional ≤3 CMC-trending names admitted only if they pass liquidity + spread
  filters at decision time; otherwise skipped (logged as abstention).
- **Cadence**: evaluate every `tick_seconds` (default 1800s = 30m); act at most a few times/day.
- **Signal (enter risk)**: trend-following, long-only spot. Take risk only when **1h and 4h
  momentum agree** in sign AND **realized volatility is below `vol_enter_max`**. Mixed or
  high-vol regime ⇒ hold/de-risk.
- **Sizing**: `1–3% of NAV` per trade, volatility-scaled (smaller when vol higher). Total risky
  (non-stable) exposure capped at `max_risky_exposure_pct` (15–20%).
- **Drawdown ladder** (gate is 6%; we never approach it):
  - DD ≥ `1.5%` → halve new-trade size.
  - DD ≥ `3.0%` → stop opening risk; only de-risking sells allowed.
  - DD ≥ `4.0%` → **stablecoin mode**: flatten risky exposure, trade nothing but exits.
  - Hard internal kill at `4.0%`, a 2% buffer under the 6% elimination gate.
- **Stops / exits**: per-position stop at `stop_loss_pct`; take-profit trim at `take_profit_pct`;
  time-stop closes stale positions after `max_hold_hours`.
- **Minimum trade count without overtrading**: a scheduled **micro-rebalance** (tiny,
  in-policy, toward a target stable/risky ratio) guarantees the floor of qualifying trades when
  no signal fires, so low conviction never means zero trades. Rate-limited by
  `max_trades_per_hour` and `min_trade_interval_seconds`.
- **Rule adherence by construction**: only universe tokens, only allowed pairs, only sizes
  within caps. Anything else is rejected by the Maria policy and never reaches TWAK.

## 4. Maria verifiable layer (core IP)

- `policy/engine.py` — deterministic policy evaluating a Decision against the full ruleset
  above; returns allow / clamp / reject with a structured reason. Pure function of
  (decision, portfolio, drawdown, regime, committed-config).
- `policy/receipt.py` — every evaluation (including holds/abstentions) emits a **Receipt**:
  `{seq, ts, prev_hash, decision, verdict, policy_hash, inputs_digest}`, where
  `hash = sha256(prev_hash + canonical(body))`. Receipts form a tamper-evident chain
  (`receipts.jsonl`). Breaking any record breaks every hash after it.
- `policy/commit.py` — computes `policy_hash = sha256(canonical(strategy.json))`, builds the
  ERC-8004 commit-reveal payload, and verifies a receipt chain against a committed hash
  (the public verifier judges can run).

## 5. Abstention / avoided-loss ledger

- `abstention/ledger.py` — each skip records reason (`stale_data | vol_spike | thin_liquidity |
  drawdown_proximity | slippage_mismatch | regime_conflict`), the hypothetical execution price,
  and later marks it to market. Produces an **avoided-loss** running total: proof that restraint
  preserved capital. Reframes low trade volume as risk intelligence, not inactivity.

## 6. Ops hardening (the make-or-break for an unattended week)

`ops/` — judges forgive modest returns, not a broken agent:
- **watchdog**: heartbeat file + supervisor that restarts the loop; restart-safe (idempotent
  from persisted state).
- **rpc**: multiple BSC RPC endpoints with health check + failover.
- **nonce**: local nonce tracking, pending-tx reconciliation, stuck-tx replace.
- **state**: persistent positions/HWM/receipt-seq on disk; crash → resume exactly.
- **reconcile**: periodic on-chain balance reconciliation vs internal state; divergence →
  fail-closed (stop trading, keep recording).
- **guards**: slippage cap per trade, stale-data rejection (CMC timestamp age), min-liquidity
  check before any swap.

## 7. Data — CMC MCP + x402

- `data/cmc.py` — CMC MCP as the only market-data source (12 tools: quotes, % changes, trending,
  TA, on-chain metrics). Mock fallback so the agent runs offline with no key.
- Each fetch logs an **x402 receipt** (paid-data provenance) into the trail.

## 8. TWAK + ERC-8004

- `execution/twak_backend.py` — thin adapter implementing the ExecutionBackend seam over the
  `twak` CLI / SDK: sign + execute swap, read balances. Mock path for offline.
- `identity/erc8004.py` — register the agent identity; `identity/commit.py` publishes the
  policy hash (commit-reveal). Real runs need Node ≥ 22.14, the agent key, and gas (human steps).

## 9. The dashboard (UI — must look sharp)

`web/` — dark, glass, real-time, sized for a judge to watch over 7 days:
- **Hero**: the three-layer trust stack, the committed policy hash + live "verified ✓" badge,
  the agent's ERC-8004 identity, BscScan links.
- **Live state**: NAV, drawdown gauge vs the 6% gate (with the internal 4% kill marked), risky
  exposure, current regime.
- **Decision feed**: trades (green) and abstentions (amber, with reason) streaming, each a
  receipt with its hash.
- **Avoided-loss ledger**: running total of losses dodged by restraint.
- **Black-box replay**: pick any decision → replay it deterministically from its recorded
  inputs → identical verdict, proving the trail is honest.

## 10. Track 2 — backtestable research (champion vs challenger)

`backtest/` — head-to-head on CMC historical data: **champion** (this strategy + Maria policy)
vs **challenger** (naive TWAK-style DCA/limit baseline). Report risk-adjusted return, max
drawdown, equity curves. Written up as `docs/TRACK2_RESEARCH.md`. The adversarial comparison is
**backtest-only** (a random live week could let the dumb baseline win and undercut the thesis
on-chain); full live capital goes on the champion.

## 11. Scope & human-only steps

I build and offline-test everything (no keys, mock brain + mock backend, full test suite).
Steps that need Jakob's hands (real money / his auth / his browser):
1. Fund the dedicated BSC agent wallet (~$500).
2. Create the public GitHub repo + deploy key; I push.
3. Node 22 + `twak` install, `twak compete register` (before Jun 22).
4. Send the ERC-8004 commit-reveal tx (gas) before code-lock.
5. Record the demo video.
6. Submit the DoraHacks BUIDL form (T1 + T2).

## 12. Non-negotiables

- Never breach 6% drawdown (internal hard kill at 4%).
- Only universe tokens / allowed pairs / capped sizes — rule adherence by construction.
- Deterministic, replayable, fail-closed. The committed hash is the source of truth.
- Mantle submission is a separate repo and untouched.
