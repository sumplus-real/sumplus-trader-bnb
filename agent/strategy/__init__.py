"""Survival-first strategy: the committed trading rules.

Deterministic and replayable on purpose — a week-long unattended run rewards a transparent rule
engine over an LLM that can hallucinate or stall. signals.py turns market data into a regime
read; survival.py turns the regime + portfolio into one intent (enter / exit / rebalance / hold).
"""
