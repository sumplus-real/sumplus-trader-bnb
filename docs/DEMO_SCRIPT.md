# Demo script (~90 seconds, all in the dashboard)

Prep once: `python -m agent.cli simulate 6` then `python -m agent.cli web`, open
`http://127.0.0.1:8800`. Everything below is on that one page.

**0:00 The hook (verification banner, top of page).**
"This is an autonomous trader. The interesting part is not that it trades. It is that it can prove
it stayed inside its mandate." Point at the green **Rule adherence verified** badge and the
committed policy hash. "We published this policy hash on-chain before the market opened. Every
decision references it. You can recompute it from the repo and check it yourself."

**0:20 The trust stack (top right).**
"Three layers. Trust Wallet Agent Kit signs with self-custody, ERC-8004 is the agent's on-chain
identity, and Maria, our layer, is the verifiable decision trail. Data is CoinMarketCap only, paid
per request over x402."

**0:35 Survival (the drawdown gauge plus equity curve).**
"The competition eliminates you at 6% drawdown. This is a six-week stress test with a real crash in
the middle." Point at the gauge: "Peak drawdown 2.8%. The ladder flattened to stablecoins at 3% and
held the line. Never breached. Watch the equity curve dip and recover."

**0:55 Judgement, the decisions not to trade (decision feed plus restraint panel).**
"It shows judgement by knowing when to sit out. Every abstention is a reasoned, hash-chained
receipt." Scroll the feed: trades in green, abstentions in violet with their reason.

**1:10 The black box (click any receipt).**
Click a row. "This is the black-box recorder. Any decision replays deterministically from its
recorded inputs, and the hash recomputes and matches. The trail cannot be quietly rewritten after
the market moves." Point at the three green checks.

**1:25 Close.**
"A self-custody agent that runs unattended, stays inside its risk limits, and can prove it. That is
the trust layer autonomous on-chain finance has been missing." Done.
