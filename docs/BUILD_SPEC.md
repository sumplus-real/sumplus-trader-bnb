# Sumplus Trader: BNB Hack Build Spec

> The plan, and the committed strategy. The canonical machine-readable policy lives in
> `config/strategy.json`. Its SHA-256 is published to the agent's ERC-8004 identity before
> code-lock (commit-reveal). Every live decision receipt references that hash, so rule adherence
> becomes something anyone can recompute rather than a claim you take on faith.

---

## 0. What we are building, in one sentence

A self-custody AI trader on BSC that runs unattended for a week and can show, afterward, that it
never broke its own rules. A flight recorder plus a kill switch for autonomous on-chain finance.

## 1. Why this wins (thesis)

The BNB Hack judges (BNB Chain, CoinMarketCap, Trust Wallet) score Track 1 on returns, drawdown,
risk-adjusted performance, and rule adherence, with extra prizes for technical execution,
originality, real-world relevance, and demo. The $10K live-PnL top spot is largely a one-week luck
lottery across 149 tokens under a 6% drawdown gate. We are not betting on alpha. We are betting on
the verifiable trust layer. So we do two things:

1. Ship a live agent that survives the week: capital preserved, zero rule violations on record, a
   smooth equity curve, and the minimum trade count met. That is the living proof.
2. Win the judged dimensions where verifiable financial infrastructure for AI agents is our actual
   product, not a P&L line.

### The three-layer trust stack (one flex per sponsor)

| Layer | Tech | Sponsor it speaks to |
|---|---|---|
| Self-custody signing | TWAK (Trust Wallet Agent Kit). Keys local, dev-defined policy, registration, x402. | Trust Wallet |
| Self-sovereign agent identity | ERC-8004 identity carrying the commit-reveal of the policy hash | BNB Chain |
| Verifiable decision trail | Maria writes hash-chained receipts showing every decision obeyed the committed policy | Sumplus (us) |
| Data provenance | CMC MCP is the only market-data source; each fetch logs an x402 paid-data receipt | CoinMarketCap |

### The signature move: commit-reveal

Before code-lock we publish `sha256(canonical strategy.json) + strategy_module_version` to the
agent's ERC-8004 identity in one transaction. During the unattended week, every Maria decision
receipt embeds that hash. After the week, anyone can recompute the hash from the public repo and
verify the agent obeyed rules that were fixed before the market moved. That turns rule adherence,
the softest of the judged criteria, into a cryptographic check, and it makes the ERC-8004 layer
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

**Two-key safety.** A trade fires only if Maria (ours, verifiable) and TWAK (official, on-chain
spend fence) both allow it. The TWAK integration stays thin: TWAK is the signer, registration, and
x402; Maria is the decision authority. We do not rebuild policy inside TWAK.

**Robustness choice.** The live brain is deterministic and rule-based, not an LLM. A week-long
unattended run rewards a transparent, replayable, fail-closed rule engine over an LLM that can
hallucinate or stall. An optional LLM regime read is advisory only and never required to act; if
its data is stale, the agent just runs the deterministic core.

## 3. Strategy (survival-first): the committed rules

Canonical params live in `config/strategy.json`. Summary:

- **Universe** (eligible, liquid, CMC-listed BEP-20): `WBNB, BTCB, ETH, CAKE`, quoted in
  `USDT`/`USDC`. Up to 3 CMC-trending names can be admitted, but only if they pass liquidity and
  spread filters at decision time; otherwise they are skipped and logged as an abstention.
- **Cadence**: evaluate every `tick_seconds` (default 1800s = 30m); act at most a few times a day.
- **Signal (enter risk)**: trend-following, long-only spot. Take risk only when 1h and 4h momentum
  agree in sign and realized volatility is below `vol_enter_max_pct` (4%). A mixed or high-vol
  regime means hold or de-risk.
- **Sizing**: 1 to 2.5% of NAV per trade, scaled down as volatility rises. Total risky (non-stable)
  exposure capped at `max_risky_exposure_pct` (12%).
- **Drawdown ladder** (the gate is 6%; we stay well clear of it):
  - DD ≥ `1.0%` → halve new-trade size.
  - DD ≥ `2.0%` → open no new risk; only de-risking sells allowed.
  - DD ≥ `3.0%` → stablecoin mode: flatten risky exposure, trade nothing but exits.
  - Hard internal kill at `3.0%`, a 3-point buffer under the 6% elimination gate.
- **Stops and exits**: per-position stop at `stop_loss_pct` (2%); take-profit trim at
  `take_profit_pct` (4%); a time-stop closes stale positions after `max_hold_hours` (48h).
- **Minimum trade count without overtrading**: when no signal fires, a scheduled micro-rebalance
  (tiny, in-policy, toward a target stable/risky ratio) keeps the qualifying trade count above its
  floor, so low conviction never means zero trades. Rate-limited by `max_trades_per_hour` and
  `min_trade_interval_seconds`.
- **Rule adherence by construction**: only universe tokens, only allowed pairs, only sizes within
  caps. Anything else is rejected by the Maria policy and never reaches TWAK.

## 4. Maria verifiable layer (core IP)

- `policy/engine.py`: deterministic policy that evaluates a Decision against the full ruleset above
  and returns allow / clamp / reject with a structured reason. A pure function of (decision,
  portfolio, drawdown, regime, committed-config).
- `policy/receipt.py`: every evaluation, holds and abstentions included, emits a Receipt
  `{seq, ts, prev_hash, decision, verdict, policy_hash, inputs_digest}`, where
  `hash = sha256(prev_hash + canonical(body))`. The receipts form a tamper-evident chain in
  `receipts.jsonl`. Break any record and every hash after it breaks too.
- `policy/commit.py`: computes `policy_hash = sha256(canonical(strategy.json))`, builds the
  ERC-8004 commit-reveal payload, and verifies a receipt chain against a committed hash. This is
  the public verifier judges can run.

## 5. Abstention / avoided-loss ledger

- `abstention/ledger.py`: each skip records a reason (`stale_data | vol_spike | thin_liquidity |
  drawdown_proximity | slippage_mismatch | regime_conflict`), the hypothetical execution price, and
  marks it to market later. It keeps a running avoided-loss total, so restraint that preserved
  capital is visible in the record. Low trade volume reads as risk intelligence rather than as
  inactivity.

## 6. Ops hardening (make-or-break for an unattended week)

`ops/`: judges forgive a modest return more readily than a broken agent.
- **watchdog**: heartbeat file plus a supervisor that restarts the loop; restart-safe and
  idempotent from persisted state.
- **rpc**: multiple BSC RPC endpoints with health check and failover.
- **nonce**: local nonce tracking, pending-tx reconciliation, stuck-tx replace.
- **state**: positions, HWM, and receipt-seq persisted to disk; after a crash it resumes exactly.
- **reconcile**: periodic on-chain balance reconciliation against internal state; on divergence it
  fails closed, stops trading, and keeps recording.
- **guards**: per-trade slippage cap, stale-data rejection (by CMC timestamp age), and a
  min-liquidity check before any swap.

## 7. Data: CMC MCP + x402

- `data/cmc.py`: CMC MCP is the only market-data source (quotes, % changes, trending, TA, on-chain
  metrics). A mock fallback lets the agent run offline with no key.
- Each fetch logs an x402 receipt as paid-data provenance into the trail.

## 8. TWAK + ERC-8004

- `execution/twak_backend.py`: a thin adapter over the `twak` CLI/SDK that implements the
  ExecutionBackend seam (sign and execute a swap, read balances). It has a mock path for offline.
- `identity/`: register the agent identity and publish the policy hash (commit-reveal). Real runs
  need Node ≥ 22.14, the agent key, and gas. Those are human steps.

## 9. The dashboard (UI: must look sharp)

`agent/web.py`: dark, glass, real-time, sized for a judge to watch over seven days.
- **Hero**: the three-layer trust stack, the committed policy hash with a live verified badge, the
  agent's ERC-8004 identity, BscScan links.
- **Live state**: NAV, a drawdown gauge against the 6% gate (with the internal 3% kill marked),
  risky exposure, current regime.
- **Decision feed**: trades (green) and abstentions (with reason) streaming, each one a receipt
  with its hash.
- **Avoided-loss ledger**: a running total of the losses restraint dodged.
- **Black-box replay**: pick any decision, replay it deterministically from its recorded inputs,
  get an identical verdict, and see the trail is honest.

## 10. Track 2: backtestable research (champion vs challenger)

`backtest/`: a head-to-head over a regime-rich synthetic series. The champion is this strategy plus
the Maria policy; the challenger is a naive DCA baseline. We report risk-adjusted return, max
drawdown, and equity curves, written up in `docs/TRACK2_RESEARCH.md`. The comparison is
backtest-only, because a single random live week could let the dumb baseline win and undercut the
thesis on-chain. Full live capital goes on the champion.

## 11. Scope and human-only steps

I build and offline-test everything (no keys, mock brain plus mock backend, full test suite). The
steps that need Jakob's hands (real money, his auth, his browser):
1. Fund the dedicated BSC agent wallet (~$500).
2. Create the public GitHub repo and add the deploy key; I push.
3. Install Node 22 and `twak`, then `twak compete register` (before Jun 22).
4. Send the ERC-8004 commit-reveal tx (gas) before code-lock.
5. Deploy the dashboard as a public link for the demo field.
6. Submit the DoraHacks BUIDL form (T1 and T2).

## 12. Non-negotiables

- Never breach 6% drawdown (internal hard kill at 3%).
- Only universe tokens, allowed pairs, capped sizes. Rule adherence by construction.
- Deterministic, replayable, fail-closed. The committed hash is the source of truth.
- The Mantle submission is a separate repo and stays untouched.
