"""Maria verifiable policy layer.

Three jobs, in increasing order of what makes this submission different:
  1. engine.py   — the deterministic policy that allows / clamps / rejects every decision.
  2. receipt.py  — a tamper-evident, hash-chained receipt for EVERY decision (incl. abstentions).
  3. canonical.py / commit.py — the commit-reveal: the policy hash published to the agent's
     ERC-8004 identity BEFORE code-lock, which every receipt references. "Rule adherence" stops
     being a claim and becomes something anyone can recompute and verify.
"""
