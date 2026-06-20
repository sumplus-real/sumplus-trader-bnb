"""The Maria policy engine — the decision authority.

Deterministic. Pure function of (decision, portfolio, market, committed config). It does not
chase returns; it constrains risk. The strategy proposes; this engine allows / clamps / rejects,
and the result is written to the hash-chained receipt log. The same rules are committed on-chain
(policy hash) before code-lock, so every verdict is checkable after the fact.

Order of checks (fail-closed, cheapest-and-hardest first):
  1. stale data        -> reject (never act on data older than max_data_age_seconds)
  2. rule adherence    -> reject (token/pair not in the committed whitelist)
  3. drawdown ladder   -> reject risk-increasing trades per the current rung
  4. risky exposure    -> reject/clamp trades that breach the exposure cap
  5. rate limit        -> reject (too many trades / too soon)
  6. size caps         -> clamp to min(usd cap, pct-of-NAV cap)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PortfolioView:
    nav_usd: float
    drawdown_pct: float = 0.0
    risky_exposure_pct: float = 0.0      # fraction of NAV in non-stable tokens, 0..1
    trades_last_hour: int = 0
    seconds_since_last_trade: float = 1e9


@dataclass
class MarketView:
    data_age_s: float = 0.0
    regime: str = "neutral"              # risk_on | neutral | risk_off


@dataclass
class PolicyVerdict:
    action: str                          # allow | clamp | reject
    kind: str                            # trade | clamp | reject | abstain | hold | exit
    final_amount_usd: float
    reason: str
    ladder_rung: str = "none"            # none | halve_size | no_new_risk | stablecoin_mode
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.action in ("allow", "clamp")


class PolicyEngine:
    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.risk = cfg["risk"]
        self.quote = {t.upper() for t in cfg.get("quote_tokens", ["USDT", "USDC"])}
        self.allowed_tokens = {t.upper() for t in cfg.get("allowed_tokens", [])}
        self.allowed_pairs = {
            (p["chain"], p["from"].upper(), p["to"].upper())
            for p in cfg.get("allowed_pairs", [])
        }
        self.ladder = sorted(cfg.get("drawdown_ladder", []), key=lambda r: r["at_pct"])
        self.max_data_age = cfg.get("data", {}).get("max_data_age_seconds", 600)

    # ── helpers ────────────────────────────────────────────────────────────
    def _is_stable(self, token: str) -> bool:
        return token.upper() in self.quote

    def _risk_increasing(self, decision) -> bool:
        # spending a stable to acquire a non-stable = taking on market risk
        return decision.side == "buy" and self._is_stable(decision.from_token) and not self._is_stable(decision.to_token)

    def _risk_reducing(self, decision) -> bool:
        # selling a non-stable back to a stable = de-risking
        return decision.side == "sell" and not self._is_stable(decision.from_token) and self._is_stable(decision.to_token)

    def _ladder_rung(self, drawdown_pct: float) -> str:
        rung = "none"
        for r in self.ladder:
            if drawdown_pct >= r["at_pct"]:
                rung = r["action"]
        return rung

    # ── the check ──────────────────────────────────────────────────────────
    def check(self, decision, portfolio: PortfolioView, market: MarketView) -> PolicyVerdict:
        if not decision.is_trade():
            return PolicyVerdict("allow", "hold", 0.0, "hold — no action")

        ft, tt = decision.from_token.upper(), decision.to_token.upper()
        rung = self._ladder_rung(portfolio.drawdown_pct)

        # 1. stale data — never act on stale market data
        if market.data_age_s > self.max_data_age:
            return PolicyVerdict("reject", "reject", 0.0,
                                 f"stale data: {market.data_age_s:.0f}s > {self.max_data_age}s cap",
                                 ladder_rung=rung)

        # 2. rule adherence — committed whitelist
        if ft not in self.allowed_tokens or tt not in self.allowed_tokens:
            bad = ft if ft not in self.allowed_tokens else tt
            return PolicyVerdict("reject", "reject", 0.0,
                                 f"rule adherence: token {bad} not in committed whitelist",
                                 ladder_rung=rung)
        if (decision.chain, ft, tt) not in self.allowed_pairs:
            return PolicyVerdict("reject", "reject", 0.0,
                                 f"rule adherence: pair {ft}->{tt} on {decision.chain} not committed",
                                 ladder_rung=rung)

        # 3. drawdown ladder
        if rung == "stablecoin_mode" and not self._risk_reducing(decision):
            return PolicyVerdict("reject", "reject", 0.0,
                                 f"stablecoin mode (drawdown {portfolio.drawdown_pct:.2f}%): only de-risking sells allowed",
                                 ladder_rung=rung)
        if rung == "no_new_risk" and self._risk_increasing(decision):
            return PolicyVerdict("reject", "reject", 0.0,
                                 f"no-new-risk rung (drawdown {portfolio.drawdown_pct:.2f}%): risk-increasing trade blocked",
                                 ladder_rung=rung)

        # 4. risky exposure cap (only constrains risk-increasing trades)
        max_risky = float(self.risk.get("max_risky_exposure_pct", 0.20))
        if self._risk_increasing(decision) and portfolio.nav_usd > 0:
            add_pct = decision.amount_usd / portfolio.nav_usd
            room_pct = max(0.0, max_risky - portfolio.risky_exposure_pct)
            if room_pct <= 0:
                return PolicyVerdict("reject", "reject", 0.0,
                                     f"risky exposure {portfolio.risky_exposure_pct*100:.0f}% at cap {max_risky*100:.0f}%",
                                     ladder_rung=rung)
            if add_pct > room_pct:
                clamped = room_pct * portfolio.nav_usd
                return self._finalise(decision, portfolio, clamped, rung,
                                      f"clamped to exposure room ({room_pct*100:.1f}% of NAV)")

        # 5. rate limit
        if portfolio.trades_last_hour >= self.risk["max_trades_per_hour"]:
            return PolicyVerdict("reject", "reject", 0.0,
                                 f"rate limit: {portfolio.trades_last_hour} trades this hour >= {self.risk['max_trades_per_hour']}",
                                 ladder_rung=rung)
        if portfolio.seconds_since_last_trade < self.risk["min_trade_interval_seconds"]:
            return PolicyVerdict("reject", "reject", 0.0,
                                 f"rate limit: {portfolio.seconds_since_last_trade:.0f}s since last < {self.risk['min_trade_interval_seconds']}s",
                                 ladder_rung=rung)

        # 6. size caps (+ halve_size rung)
        return self._finalise(decision, portfolio, decision.amount_usd, rung, "within policy")

    def _finalise(self, decision, portfolio: PortfolioView, amount: float, rung: str,
                  base_reason: str) -> PolicyVerdict:
        max_single = float(self.risk["max_single_trade_usd"])
        max_by_pct = portfolio.nav_usd * float(self.risk.get("max_single_trade_pct", 0.03))
        cap = min(max_single, max_by_pct) if portfolio.nav_usd > 0 else max_single
        if rung == "halve_size":
            cap = cap / 2.0
        clamped = False
        final = amount
        if final > cap:
            final, clamped = cap, True
        if clamped or "clamped" in base_reason:
            note = base_reason if "clamped" in base_reason else f"clamped {amount:.2f}->{final:.2f} to respect caps"
            if rung == "halve_size":
                note += " (drawdown ladder: size halved)"
            return PolicyVerdict("clamp", "clamp", round(final, 2), note, ladder_rung=rung)
        return PolicyVerdict("allow", "trade", round(final, 2), base_reason, ladder_rung=rung)
