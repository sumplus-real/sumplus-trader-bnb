# TRACK-2 Research: Survival-First vs Naive DCA under a Drawdown-Elimination Gate

> This is the research that backs the Track 2 deliverable: a CoinMarketCap Strategy Skill
> (`skills/sumplus-survival-strategy/`) that reads market data and emits a backtestable
> **StrategySpec**. The numbers below are what that spec produces on the bench. Generate a spec with
> `python skills/sumplus-survival-strategy/generate_spec.py`; reproduce the synthetic study with
> `python backtest/run.py` and the real-data study with `python backtest/real_data_live.py`.

## Abstract

We present a controlled, fully-reproducible head-to-head backtest of two
trading strategies over six weeks of hourly bars across a four-asset BSC
universe (WBNB, BTCB, ETH, CAKE). The **champion** is a survival-first,
long-only policy that takes risk only when 1h and 4h momentum agree and
realised volatility is below 4%, scales size 1–3% of NAV (volatility-scaled,
capped at 20% total risky exposure), and defends equity with a three-rung
drawdown ladder (halve at 1.5%, stop opening risk at 3%, flatten to stablecoin
at 4%) backed by per-position 3% stops, 4% targets, and a 48h time-stop. The
**challenger** is the naive DCA / always-long bot most contestants ship: a
fixed-dollar buy on a fixed cadence, with no volatility filter and no drawdown
control of any kind. Both pay identical costs (25 bps fee + 30 bps slippage).

The headline result, reproducible by running `python backtest/run.py` (fixed
seed `20240622`), is decisive. The champion **survives the full six weeks with
a 3.93% maximum drawdown**, comfortably inside both its own 4% internal
hard-kill and the competition's 6% elimination gate, and finishes +7.58%. The
challenger is **eliminated at hour 564** when its drawdown blows through 29%
during the crash; its attractive +34.3% full-period paper return is a mirage,
achievable only by holding through a drawdown the competition forbids. On the
comparable both-alive window (hours 0–564), the champion beats the challenger
on risk-adjusted return: **Sharpe 1.67 vs 0.87, Calmar 0.47 vs 0.12.**

## Thesis

The competition this work supports is structured around a **6%
maximum-drawdown elimination gate**: breach it once and you are disqualified,
regardless of paper PnL. In such a regime the dominant objective is not
return maximisation but **drawdown control and survival**. A strategy that
makes 8% with a 4% drawdown is strictly superior to one that makes 30% with a
25% drawdown, because the second is eliminated the moment its drawdown touches
6% and never gets to keep its 30%. The naive DCA bot is seductive because its
equity curve looks smooth and steep *in a pure uptrend*; its fatal flaw is
having no mechanism to stop bleeding when the regime flips. The champion's
design (multi-signal entry gate, hard exposure cap, per-position stops, and a
layered drawdown ladder) exists to guarantee the equity curve never
approaches the gate, so whatever return it earns is actually **realisable**.

## Methodology

**Data.** Prices are generated deterministically by a discretised geometric
Brownian motion (`backtest/data.py`) driven by `random.Random(20240622)`, so
every run is byte-identical. The six weeks (1008 hourly bars) are partitioned
into four explicit regimes designed to exercise every aspect of the
strategies: a calm uptrend (0–240h), a choppy range (240–540h), a sharp crash
(540–732h) comprising a gradual lead-in followed by a ~12% market-wide
panic-cascade gap at hour 564, and a smooth recovery (732–1008h). Each asset
carries its own beta and volatility scale. A `load_csv(path)` stub is included
so the same pipeline can be re-pointed at real CoinMarketCap historical data
via the Agent Hub without touching strategy code.

**Accounting.** `backtest/portfolio.py` tracks cash + positions, applies the
25 bps fee and 30 bps slippage on every swap (buys fill at `price*(1+slip)`,
sells at `price*(1-slip)`), marks NAV each hour, and maintains the
high-water-mark and running drawdown the ladder reads.

**Champion (`backtest/champion.py`).** A self-contained reference implementation of the same
survival mechanisms the live agent runs. The parameters here are the backtest calibration; the
live committed policy in `config/strategy.json` is a *stricter* variant (12% exposure cap vs 20%,
a 1/2/3% drawdown ladder vs 1.5/3/4%, 2% stops) which survives its own 6-week live simulation with
an even smaller ~2.8% peak drawdown. The mechanisms are identical; the live agent is more
conservative. Each hour it
emits one decision at a time (the runner loops up to four times, mirroring the
live `max_trades_per_hour`); the cascade, in priority order, is: (0) if the
book has been fully flat for a 24h cooldown, re-baseline the internal HWM so a
stale pre-crash peak cannot permanently lock the strategy out of the market;
(1) if drawdown ≥ 4%, flatten to stablecoin; (2) per-position exits (3%
stop-loss, 4% take-profit, 48h time-stop); (3) if drawdown ≥ 3%, open no new
risk; (4) new entries when 1h+4h momentum agree and realised vol < 4%, sized
volatility-scaled in [1%, 3%] and halved on the 1.5% rung, total risky
exposure capped at 20%; (5) a tiny $12 micro-rebalance toward a 15% risky
ratio to keep the trade count healthy. The flatten rung is deliberately a
**backstop**: in this scenario it does not fire, because the shallower rungs
and per-position 3% stops already contain the drawdown. That is defence-in-depth
working as designed.

**Challenger (`backtest/challenger.py`).** Buys a fixed $120 notional every 6
hours, rotating through the four assets. No filter, no stop, no drawdown
awareness.

**Metrics (`backtest/metrics.py`).** Pure functions: total return, max
drawdown (peak-to-trough on the NAV curve), annualised Sharpe (rf = 0), and a
**period-based Calmar** (total return / max drawdown over the window). We
deliberately do **not** annualise return for Calmar, because annualising a
six-week window yields absurd figures (+840%/yr) that obscure the actual
competition outcome. We also report an **elimination analysis**: the first hour
at which each strategy's drawdown crosses the 6% gate.

## Head-to-Head Results

**(A) Full-period metrics** (the challenger's numbers include its void,
post-elimination paper recovery):

| metric                 | champion | challenger |
|------------------------|---------:|-----------:|
| total return (%)       |    7.58  |     34.30  |
| max drawdown (%)       |    3.93  |     29.03  |
| Sharpe (annualised)    |    5.85  |      5.34  |
| Calmar (period)        |    1.93  |      1.18  |
| trade count            |   373    |     83     |

**(B) Competition-window metrics** (both strategies alive, hours 0–564, the
moment the challenger is eliminated, the only fair risk-adjusted comparison):

| metric                 | champion | challenger |
|------------------------|---------:|-----------:|
| total return (%)       |    1.36  |      2.09  |
| max drawdown (%)       |    2.92  |     17.15  |
| Sharpe (annualised)    |    1.67  |      0.87  |
| Calmar (period)        |    0.47  |      0.12  |

**(C) Max drawdown (%) by regime** (continuous global high-water-mark):

| regime        | champion | challenger |
|---------------|---------:|-----------:|
| calm_uptrend  |    0.49  |      1.58  |
| choppy_range  |    0.83  |      3.08  |
| sharp_crash   |    3.93  |     29.03  |
| recovery      |    3.90  |     27.20  |

**Interpretation by regime.** In the calm uptrend both strategies make money;
the naive bot looks better (it is ~fully invested while the champion caps at
20%), and its drawdown is a tame 1.58%. This is the trap: the naive approach
*rewards* itself in good regimes. In the choppy range the champion's
momentum-agreement gate keeps it largely flat while the naive bot accumulates,
nudging the challenger's drawdown to 3.08%. The regimes diverge violently in
the crash: the champion's 3% stops and 3% no-new-risk rung engage during the
gradual lead-in, and when the hour-564 cascade gaps its remaining risk through
the stops, the realised loss is contained by the 20% exposure cap. Max
drawdown is **3.93%**, survival never in doubt. The uncontrolled challenger,
~90% long, is driven straight through the 6% gate to a 29% drawdown. It is
eliminated at hour 564 with a realised return of just +2.09%, disqualified
and unable to participate in the recovery that follows. The champion, having
re-armed after its flat-cooldown, re-enters the smooth recovery and compounds
to +7.58%.

## Real-Data Validation (three recent weeks)

The synthetic study above is calibrated to be qualitatively realistic, but it is synthetic. To check
the spec against the actual market, `backtest/real_data_live.py` runs the **exact live committed
policy** (12% exposure cap, 1/2/3% ladder, 3% internal kill, 2% stops, driven through the real
`agent.core.tick` pipeline) over three recent calendar weeks of **real hourly Binance closes** for
the same universe (WBNB←BNB, BTCB←BTC, ETH, CAKE). This is the policy whose hash is committed
on-chain, on real data, with no parameter changes.

| week (UTC) | return | peak drawdown | 6% gate | trades |
|------------|-------:|--------------:|---------|-------:|
| 05-30 → 06-06 | -0.36% | 0.81% | survived | 12 |
| 06-06 → 06-13 | +0.58% | 0.14% | survived | 16 |
| 06-13 → 06-20 | +0.15% | 0.55% | survived | 11 |

For contrast, a naive DCA baseline run on the most recent week returned -3.73% and **breached the 6%
gate at hour 125** (peak drawdown 8.83%), eliminated. The survival-first policy stayed inside the
gate every week, with a worst-week peak drawdown of 0.81%, using barely a seventh of the drawdown
budget.

Two honest readings. First, the protective machinery is not an artifact of the synthetic crash: on
real recent data it never approaches the gate, and the naive approach that most contestants ship is
eliminated this very week. Second, these three weeks were trendless to slightly-down, so the strategy
mostly sat in stablecoins and finished roughly flat (about +0.4% combined). It preserved capital; it
did not manufacture a return the market did not offer. That is the intended behaviour under a gate:
the trade count (11–16/week) also confirms the live brain trades sparingly, unlike the reference
champion's heavier micro-rebalancing.

## Limitations & Next Steps

The most important limitation is that the price series are **synthetic**. The
regimes are hand-calibrated to be qualitatively realistic (a
gradual-then-cascade crash is how real liquidation events unfold) and the four
assets share a market beta, but they are not real market data. The obvious
next step is to re-run the identical pipeline on actual CoinMarketCap data for
the competition window via the Agent Hub's CMC MCP. The `load_csv(path)`
loader already exists for this. A second limitation is the hourly decision
cadence: a truly instantaneous flash crash could gap through the hourly mark
before any rung evaluates; the 20% exposure cap and per-position stop limit
this, but a sub-hourly loop would tighten it further. Third, the 4%
stablecoin-flatten rung did not fire here (the shallower rungs did the work);
validating it needs a deliberately more severe stress test. Finally, the
champion's 373 trades reflect its tight 4% take-profit and 48h time-stop;
on-chain fee assumptions warrant sensitivity analysis.

## Conclusion

In a competition judged on returns **conditional on surviving a 6% drawdown
gate**, capital preservation is the prerequisite for any return to count. The champion's layered defence caps its
worst drawdown at 3.93% (2.07 points of headroom), delivers superior
risk-adjusted return on the comparable both-alive window (Sharpe 1.67 vs 0.87,
Calmar 0.47 vs 0.12), and finishes +7.58%. The naive challenger is eliminated
at hour 564; its headline +34.3% is void. Survival-first wins not by making
more in the good times, but by being allowed to keep what it makes in the bad
times. All numbers are reproducible from `backtest/results.json`.
